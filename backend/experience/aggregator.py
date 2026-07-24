from __future__ import annotations

import hashlib
from collections import defaultdict

from experience.models import OperationalPattern
from experience.statistics import ExperienceStatisticsEngine, get_statistics_engine
from experience.store import ExperienceStore, get_experience_store


class ExperiencePatternAggregator:
    def __init__(self, store: ExperienceStore, statistics: ExperienceStatisticsEngine):
        self.store = store
        self.statistics = statistics

    def build_patterns(
        self,
        *,
        service: str | None = None,
        failure_type: str | None = None,
    ) -> list[OperationalPattern]:
        experiences = self.store.get_experiences(service=service, failure_type=failure_type, limit=5000)
        grouped: dict[str, list] = defaultdict(list)
        for record in experiences:
            key = record.failure_type or "unknown_failure"
            grouped[key].append(record)

        patterns = [self._build_pattern(group, records) for group, records in grouped.items()]
        patterns.sort(key=lambda item: (-item.success_rate, -item.total_occurrences, item.failure_type))
        return patterns

    def get_relevant_patterns(self, knowledge_object: object) -> list[OperationalPattern]:
        failure_type = getattr(knowledge_object, "failure_type", "")
        service = getattr(knowledge_object, "service", "")
        patterns = self.build_patterns(service=service or None, failure_type=failure_type or None)
        if patterns:
            return patterns
        return self.build_patterns(failure_type=failure_type or None)

    def _build_pattern(self, failure_type: str, records: list) -> OperationalPattern:
        recommendation_groups: dict[str, list] = defaultdict(list)
        for record in records:
            recommendation_groups[record.recommendation_id].append(record)

        best_id = ""
        best_score = (-1.0, -1, 0.0)
        best_stats = None
        for recommendation_id, grouped_records in recommendation_groups.items():
            stats = self.statistics.get_recommendation_statistics(recommendation_id)
            score = (stats.success_rate, stats.times_used, -stats.avg_resolution_time_seconds)
            if score > best_score:
                best_score = score
                best_id = recommendation_id
                best_stats = stats

        services = sorted({record.service for record in records if record.service})
        components = sorted({record.component for record in records if record.component})
        last_seen = max(record.timestamp for record in records)
        if best_stats is None:
            best_stats = self.statistics.get_recommendation_statistics(best_id)

        pattern_raw = f"{failure_type}:{','.join(services)}:{best_id}"
        pattern_id = hashlib.md5(pattern_raw.encode()).hexdigest()[:12]

        return OperationalPattern(
            pattern_id=pattern_id,
            failure_type=failure_type,
            services=services,
            components=components,
            total_occurrences=len(records),
            best_recommendation_id=best_id,
            best_recommendation=best_stats.recommendation,
            success_rate=best_stats.success_rate,
            avg_resolution_time_seconds=best_stats.avg_resolution_time_seconds,
            evidence_count=len(recommendation_groups.get(best_id, [])),
            last_seen=last_seen,
        )


_aggregator: ExperiencePatternAggregator | None = None


def get_pattern_aggregator() -> ExperiencePatternAggregator:
    global _aggregator
    if _aggregator is None:
        _aggregator = ExperiencePatternAggregator(get_experience_store(), get_statistics_engine())
    return _aggregator
