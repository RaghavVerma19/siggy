import os
import tempfile

from experience.aggregator import ExperiencePatternAggregator
from experience.models import ExperienceRecordCreate
from experience.statistics import ExperienceStatisticsEngine
from experience.store import ExperienceStore
from graph.builder import GraphBuilder
from graph.client import GraphClient
from graph.context_builder import GraphContextBuilder
from graph.queries import GraphQueryService
from knowledge.schema import KnowledgeObject


def run_graph_smoke_test() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        experience_db = os.path.join(temp_dir, "experience.db")
        graph_db = os.path.join(temp_dir, "graph.db")

        store = ExperienceStore(db_path=experience_db)
        statistics = ExperienceStatisticsEngine(store)
        aggregator = ExperiencePatternAggregator(store, statistics)
        client = GraphClient(db_path=graph_db)
        builder = GraphBuilder(client, statistics, aggregator)
        queries = GraphQueryService(client)
        context_builder = GraphContextBuilder(client, statistics, aggregator)
        try:
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
                    symptoms=["high_latency"],
                )
            )
            store.record_experience(
                ExperienceRecordCreate(
                    incident_id="inc-2",
                    recommendation_id="INCREASE_POOL_SIZE",
                    recommendation="Increase Redis pool size",
                    accepted=True,
                    worked=True,
                    resolution_time_seconds=620,
                    confidence=0.89,
                    service="payment",
                    component="redis",
                    failure_type="connection_pool_exhaustion",
                    symptoms=["request_timeout"],
                )
            )

            knowledge_object = KnowledgeObject(
                incident_id="live-1",
                title="Checkout latency increased",
                summary="Redis connection pool exhausted",
                service="checkout",
                component="redis",
                failure_type="connection_pool_exhaustion",
                symptoms=["high_latency", "request_timeout"],
                severity="high",
                environment="production",
                root_cause="Redis connection pool exhausted",
                fix="Increase Redis pool size",
                fix_type="increase_pool_size",
                confidence=0.94,
            )

            builder.sync_knowledge_object(knowledge_object)
            builder.sync_operational_patterns()

            neighbors = queries.get_neighbors("checkout")
            pattern = queries.get_pattern("connection_pool_exhaustion")
            recommendation = queries.get_recommendation("INCREASE_POOL_SIZE")
            context = context_builder.build(
                knowledge_object,
                ranked_recommendations=[
                    {
                        "recommendation_id": "INCREASE_POOL_SIZE",
                        "recommendation": "Increase Redis pool size",
                        "final_score": 0.92,
                    }
                ],
            )

            assert neighbors.center.label == "checkout"
            assert any(item["node"]["node_type"] == "Component" for item in neighbors.neighbors if item["node"])
            assert pattern.patterns
            assert recommendation.recommendation["properties"]["recommendation_id"] == "INCREASE_POOL_SIZE"
            assert context.evidence

            print("graph engine smoke test passed")
        finally:
            store.close()
            client.close()


if __name__ == "__main__":
    run_graph_smoke_test()
