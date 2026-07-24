from __future__ import annotations

from collections import defaultdict

from experience.aggregator import ExperiencePatternAggregator, get_pattern_aggregator
from experience.models import (
    RankedRecommendation,
    RecommendationStatistics,
    canonicalize_recommendation_id,
    recommendation_label_from_id,
)
from experience.statistics import ExperienceStatisticsEngine, get_statistics_engine


class ExperienceAwareRanker:
    def __init__(
        self,
        statistics: ExperienceStatisticsEngine,
        aggregator: ExperiencePatternAggregator,
        *,
        similarity_weight: float = 0.70,
        metadata_weight: float = 0.30,
        success_influence: float = 0.25,
        resolution_influence: float = 0.10,
        confidence_influence: float = 0.05,
        prior_alpha: float = 2.0,
        prior_beta: float = 2.0,
    ):
        self.statistics = statistics
        self.aggregator = aggregator
        self.similarity_weight = similarity_weight
        self.metadata_weight = metadata_weight
        self.success_influence = success_influence
        self.resolution_influence = resolution_influence
        self.confidence_influence = confidence_influence
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta

    def rank(
        self,
        knowledge_object,
        similar_incidents: list[dict],
        *,
        fallback_recommendation: str = "",
        fallback_fix_type: str = "",
        fallback_confidence: float = 0.0,
    ) -> list[RankedRecommendation]:
        candidate_map: dict[str, dict] = defaultdict(
            lambda: {
                "recommendation": "",
                "similarities": [],
                "confidences": [],
                "count": 0,
                "service_match": False,
                "component_match": False,
                "failure_match": False,
                "severity_match": False,
            }
        )

        for incident in similar_incidents:
            recommendation = incident.get("fix", "") or fallback_recommendation
            recommendation_id = canonicalize_recommendation_id(
                recommendation= recommendation,
                fix_type=incident.get("fix_type", ""),
            )
            entry = candidate_map[recommendation_id]
            entry["recommendation"] = recommendation or recommendation_label_from_id(recommendation_id)
            entry["similarities"].append(float(incident.get("similarity", 0.0)))
            entry["confidences"].append(float(incident.get("confidence", 0.0)))
            entry["count"] += 1
            entry["service_match"] = entry["service_match"] or (
                incident.get("service", "").lower() == getattr(knowledge_object, "service", "").lower()
            )
            entry["component_match"] = entry["component_match"] or (
                incident.get("component", "").lower() == getattr(knowledge_object, "component", "").lower()
            )
            entry["failure_match"] = entry["failure_match"] or (
                incident.get("failure_type", "").lower() == getattr(knowledge_object, "failure_type", "").lower()
            )
            entry["severity_match"] = entry["severity_match"] or (
                incident.get("severity", "").lower() == getattr(knowledge_object, "severity", "").lower()
            )

        if fallback_recommendation or fallback_fix_type:
            fallback_id = canonicalize_recommendation_id(
                recommendation=fallback_recommendation,
                fix_type=fallback_fix_type,
            )
            entry = candidate_map[fallback_id]
            entry["recommendation"] = fallback_recommendation or recommendation_label_from_id(fallback_id)
            if not entry["confidences"]:
                entry["confidences"].append(fallback_confidence)

        relevant_patterns = self.aggregator.get_relevant_patterns(knowledge_object)
        pattern_by_recommendation = {pattern.best_recommendation_id: pattern for pattern in relevant_patterns}

        ranked: list[RankedRecommendation] = []
        for recommendation_id, entry in candidate_map.items():
            stats = self.statistics.get_recommendation_statistics(recommendation_id)
            pattern = pattern_by_recommendation.get(recommendation_id)
            similarity_score = max(entry["similarities"]) if entry["similarities"] else 0.0
            success_score = round(stats.success_rate / 100, 3) if stats.times_used else 0.5
            adjusted_success_score = self._bayesian_success(stats)
            resolution_score = self._normalize_resolution(stats)
            confidence_base = stats.avg_confidence if stats.avg_confidence > 0 else max(entry["confidences"], default=fallback_confidence)
            confidence_score = round(max(0.0, min(confidence_base, 1.0)), 3)
            metadata_score = round(
                (
                    (0.35 if entry["service_match"] else 0.0)
                    + (0.30 if entry["component_match"] else 0.0)
                    + (0.25 if entry["failure_match"] else 0.0)
                    + (0.10 if entry["severity_match"] else 0.0)
                ),
                3,
            )
            base_score = (
                similarity_score * self.similarity_weight
                + metadata_score * self.metadata_weight
            )
            experience_multiplier = self._experience_multiplier(
                adjusted_success_score=adjusted_success_score,
                resolution_score=resolution_score,
                confidence_score=confidence_score,
            )
            final_score = base_score * experience_multiplier

            evidence = [
                f"Similarity {similarity_score:.2f} across {entry['count']} retrieved incidents",
            ]
            if metadata_score > 0:
                evidence.append(f"Operational metadata match score {metadata_score:.2f}")
            if stats.times_used:
                evidence.append(
                    f"{stats.worked_count} of {stats.times_used} recorded outcomes succeeded"
                )
                evidence.append(
                    f"Bayesian-adjusted success score {adjusted_success_score:.2f}"
                )
            if stats.avg_resolution_time_seconds:
                evidence.append(
                    f"Average resolution time {int(stats.avg_resolution_time_seconds)} seconds"
                )
            if pattern:
                evidence.append(
                    f"Best known operational pattern for {pattern.failure_type}"
                )

            ranked.append(
                RankedRecommendation(
                    recommendation_id=recommendation_id,
                    recommendation=entry["recommendation"] or stats.recommendation,
                    similarity_score=round(similarity_score, 3),
                    success_score=success_score,
                    adjusted_success_score=adjusted_success_score,
                    resolution_score=resolution_score,
                    confidence_score=confidence_score,
                    metadata_score=metadata_score,
                    experience_multiplier=experience_multiplier,
                    final_score=round(final_score, 3),
                    times_seen_in_matches=entry["count"],
                    statistics=stats if stats.times_used else self._fallback_stats(recommendation_id, entry["recommendation"]),
                    pattern=pattern,
                    evidence=evidence,
                )
            )

        ranked.sort(
            key=lambda item: (
                -item.final_score,
                -item.metadata_score,
                -item.similarity_score,
                item.recommendation_id,
            )
        )
        return ranked

    def _normalize_resolution(self, stats: RecommendationStatistics) -> float:
        if stats.avg_resolution_time_seconds <= 0:
            return 0.5
        return round(max(0.0, 1 - min(stats.avg_resolution_time_seconds / 3600, 1.0)), 3)

    def _bayesian_success(self, stats: RecommendationStatistics) -> float:
        worked = float(stats.worked_count)
        total = float(stats.times_used)
        adjusted = (worked + self.prior_alpha) / (total + self.prior_alpha + self.prior_beta)
        return round(max(0.0, min(adjusted, 1.0)), 3)

    def _experience_multiplier(
        self,
        *,
        adjusted_success_score: float,
        resolution_score: float,
        confidence_score: float,
    ) -> float:
        centered_success = (adjusted_success_score - 0.5) * self.success_influence
        centered_resolution = (resolution_score - 0.5) * self.resolution_influence
        centered_confidence = (confidence_score - 0.5) * self.confidence_influence
        multiplier = 1.0 + centered_success + centered_resolution + centered_confidence
        return round(max(0.8, min(multiplier, 1.2)), 3)

    def _fallback_stats(self, recommendation_id: str, recommendation: str) -> RecommendationStatistics:
        return RecommendationStatistics(
            recommendation_id=recommendation_id,
            recommendation=recommendation or recommendation_label_from_id(recommendation_id),
        )


_ranker: ExperienceAwareRanker | None = None


def get_ranker() -> ExperienceAwareRanker:
    global _ranker
    if _ranker is None:
        _ranker = ExperienceAwareRanker(get_statistics_engine(), get_pattern_aggregator())
    return _ranker
