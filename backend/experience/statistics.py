from __future__ import annotations

from collections import defaultdict

from experience.models import RecommendationStatistics, recommendation_label_from_id
from experience.store import ExperienceStore, get_experience_store


class ExperienceStatisticsEngine:
    def __init__(self, store: ExperienceStore):
        self.store = store

    def get_recommendation_statistics(self, recommendation_id: str) -> RecommendationStatistics:
        experiences = self.store.get_by_recommendation(recommendation_id, limit=1000)
        return self._build_statistics(recommendation_id, experiences)

    def list_recommendation_statistics(self) -> list[RecommendationStatistics]:
        grouped: dict[str, list] = defaultdict(list)
        for record in self.store.get_experiences(limit=5000):
            grouped[record.recommendation_id].append(record)

        stats = [
            self._build_statistics(recommendation_id, experiences)
            for recommendation_id, experiences in grouped.items()
        ]
        stats.sort(key=lambda item: (-item.success_rate, -item.times_used, item.recommendation_id))
        return stats

    def _build_statistics(self, recommendation_id: str, experiences: list) -> RecommendationStatistics:
        if not experiences:
            return RecommendationStatistics(
                recommendation_id=recommendation_id,
                recommendation=recommendation_label_from_id(recommendation_id),
            )

        times_used = len(experiences)
        accepted_count = sum(1 for record in experiences if record.accepted)
        worked_count = sum(1 for record in experiences if record.worked)
        resolutions = [record.resolution_time_seconds for record in experiences if record.resolution_time_seconds > 0]
        confidences = [record.confidence for record in experiences if record.confidence > 0]
        latest = max(record.timestamp for record in experiences)

        return RecommendationStatistics(
            recommendation_id=recommendation_id,
            recommendation=experiences[0].recommendation,
            times_used=times_used,
            accepted_count=accepted_count,
            worked_count=worked_count,
            success_rate=round((worked_count / times_used) * 100, 2) if times_used else 0.0,
            acceptance_rate=round((accepted_count / times_used) * 100, 2) if times_used else 0.0,
            avg_resolution_time_seconds=round(sum(resolutions) / len(resolutions), 2) if resolutions else 0.0,
            avg_confidence=round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
            last_used_at=latest,
        )


_statistics_engine: ExperienceStatisticsEngine | None = None


def get_statistics_engine() -> ExperienceStatisticsEngine:
    global _statistics_engine
    if _statistics_engine is None:
        _statistics_engine = ExperienceStatisticsEngine(get_experience_store())
    return _statistics_engine
