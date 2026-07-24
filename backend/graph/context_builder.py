from __future__ import annotations

from experience.aggregator import ExperiencePatternAggregator, get_pattern_aggregator
from experience.statistics import ExperienceStatisticsEngine, get_statistics_engine
from graph.client import GraphClient, get_graph_client
from graph.schema import GraphContext
from knowledge.schema import KnowledgeObject


def _service_node_id(service: str) -> str:
    return f"Service:{service.lower()}"


def _component_node_id(component: str) -> str:
    return f"Component:{component.lower()}"


def _failure_node_id(failure_type: str) -> str:
    return f"FailureType:{failure_type.lower()}"


class GraphContextBuilder:
    def __init__(
        self,
        client: GraphClient,
        statistics: ExperienceStatisticsEngine,
        aggregator: ExperiencePatternAggregator,
    ):
        self.client = client
        self.statistics = statistics
        self.aggregator = aggregator

    def build(self, ko: KnowledgeObject, ranked_recommendations: list[dict] | None = None) -> GraphContext:
        service = self.client.get_node(_service_node_id(ko.service))
        component = self.client.get_node(_component_node_id(ko.component))
        failure = self.client.get_node(_failure_node_id(ko.failure_type))
        service_neighbors = self.client.get_neighbors(_service_node_id(ko.service), depth=2) if service else []
        patterns = self.aggregator.get_relevant_patterns(ko)

        related_services = []
        for item in service_neighbors:
            node = item.get("node") or {}
            if node.get("node_type") == "Service" and node.get("label", "").lower() != ko.service.lower():
                related_services.append(node)

        recommendations = []
        if ranked_recommendations:
            for item in ranked_recommendations[:5]:
                stats = self.statistics.get_recommendation_statistics(item["recommendation_id"])
                recommendations.append(
                    {
                        "recommendation_id": item["recommendation_id"],
                        "recommendation": item["recommendation"],
                        "success_rate": stats.success_rate,
                        "avg_resolution_time_seconds": stats.avg_resolution_time_seconds,
                        "final_score": item["final_score"],
                    }
                )

        evidence = []
        if service and component:
            evidence.append(f"{ko.service} depends on {ko.component}")
        if patterns:
            top_pattern = patterns[0]
            evidence.append(
                f"{top_pattern.total_occurrences} historical occurrences for {top_pattern.failure_type}"
            )
            evidence.append(
                f"Best recommendation {top_pattern.best_recommendation} succeeds {top_pattern.success_rate:.0f}% of the time"
            )
        if related_services:
            labels = ", ".join(node["label"] for node in related_services[:3])
            evidence.append(f"Related services in the same neighborhood: {labels}")

        return GraphContext(
            service=service.model_dump() if service else None,
            component=component.model_dump() if component else None,
            failure=failure.model_dump() if failure else None,
            related_services=related_services,
            recommendations=recommendations,
            patterns=[pattern.model_dump() for pattern in patterns[:5]],
            evidence=evidence,
        )


_context_builder: GraphContextBuilder | None = None


def get_graph_context_builder() -> GraphContextBuilder:
    global _context_builder
    if _context_builder is None:
        _context_builder = GraphContextBuilder(
            get_graph_client(),
            get_statistics_engine(),
            get_pattern_aggregator(),
        )
    return _context_builder
