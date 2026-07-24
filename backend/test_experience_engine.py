import os
import tempfile

from experience.aggregator import ExperiencePatternAggregator
from experience.models import ExperienceRecordCreate
from experience.ranking import ExperienceAwareRanker
from experience.statistics import ExperienceStatisticsEngine
from experience.store import ExperienceStore
from knowledge.schema import KnowledgeObject


def run_smoke_test() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "experience.db")
        store = ExperienceStore(db_path=db_path)
        statistics = ExperienceStatisticsEngine(store)
        aggregator = ExperiencePatternAggregator(store, statistics)
        ranker = ExperienceAwareRanker(statistics, aggregator)

        store.record_experience(
            ExperienceRecordCreate(
                incident_id="inc-1",
                recommendation_id="INCREASE_POOL_SIZE",
                recommendation="Increase Redis pool size",
                accepted=True,
                worked=True,
                resolution_time_seconds=540,
                confidence=0.93,
                service="checkout",
                component="redis",
                failure_type="connection_pool_exhaustion",
                symptoms=["high_latency", "request_timeout"],
            )
        )
        store.record_experience(
            ExperienceRecordCreate(
                incident_id="inc-2",
                recommendation_id="INCREASE_POOL_SIZE",
                recommendation="Increase Redis pool size",
                accepted=True,
                worked=True,
                resolution_time_seconds=600,
                confidence=0.89,
                service="payment",
                component="redis",
                failure_type="connection_pool_exhaustion",
                symptoms=["high_latency"],
            )
        )
        store.record_experience(
            ExperienceRecordCreate(
                incident_id="inc-3",
                recommendation_id="RESTART_SERVICE",
                recommendation="Restart Redis service",
                accepted=True,
                worked=False,
                resolution_time_seconds=1200,
                confidence=0.52,
                service="checkout",
                component="redis",
                failure_type="connection_pool_exhaustion",
                symptoms=["high_latency"],
            )
        )

        knowledge_object = KnowledgeObject(
            incident_id="live-1",
            title="Checkout latency spike",
            summary="Redis connection pool exhausted under load",
            service="checkout",
            component="redis",
            failure_type="connection_pool_exhaustion",
            symptoms=["high_latency", "request_timeout"],
            severity="high",
            environment="production",
            root_cause="Redis pool exhausted",
            fix="Increase Redis pool size",
            fix_type="increase_pool_size",
            confidence=0.91,
        )

        similar_incidents = [
            {
                "incident_id": "inc-101",
                "service": "checkout",
                "component": "redis",
                "failure_type": "connection_pool_exhaustion",
                "severity": "high",
                "fix": "Increase Redis pool size",
                "fix_type": "increase_pool_size",
                "confidence": 0.94,
                "similarity": 0.96,
            },
            {
                "incident_id": "inc-102",
                "service": "payment",
                "component": "redis",
                "failure_type": "connection_pool_exhaustion",
                "severity": "high",
                "fix": "Restart Redis service",
                "fix_type": "restart_service",
                "confidence": 0.61,
                "similarity": 0.82,
            },
        ]

        ranked = ranker.rank(
            knowledge_object=knowledge_object,
            similar_incidents=similar_incidents,
            fallback_recommendation=knowledge_object.fix,
            fallback_fix_type=knowledge_object.fix_type,
            fallback_confidence=knowledge_object.confidence,
        )

        stats = statistics.get_recommendation_statistics("INCREASE_POOL_SIZE")
        patterns = aggregator.build_patterns(failure_type="connection_pool_exhaustion")

        assert ranked[0].recommendation_id == "INCREASE_POOL_SIZE"
        assert stats.worked_count == 2
        assert round(stats.success_rate, 2) == 100.00
        assert patterns[0].best_recommendation_id == "INCREASE_POOL_SIZE"

        store.close()
        print("experience engine smoke test passed")


if __name__ == "__main__":
    run_smoke_test()
