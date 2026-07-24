from __future__ import annotations

from experience.aggregator import ExperiencePatternAggregator, get_pattern_aggregator


class PatternService:
    def __init__(self, aggregator: ExperiencePatternAggregator):
        self.aggregator = aggregator

    def list_patterns(
        self,
        *,
        service: str | None = None,
        failure_type: str | None = None,
    ) -> list[dict]:
        return [
            pattern.model_dump()
            for pattern in self.aggregator.build_patterns(service=service, failure_type=failure_type)
        ]


_pattern_service: PatternService | None = None


def get_pattern_service() -> PatternService:
    global _pattern_service
    if _pattern_service is None:
        _pattern_service = PatternService(get_pattern_aggregator())
    return _pattern_service
