from __future__ import annotations

from graph.client import GraphClient, get_graph_client
from graph.schema import GraphNeighborView, GraphPatternView, GraphRecommendationView


def _service_node_id(service: str) -> str:
    return f"Service:{service.lower()}"


def _failure_node_id(failure_type: str) -> str:
    return f"FailureType:{failure_type.lower()}"


def _recommendation_node_id(recommendation_id: str) -> str:
    return f"Recommendation:{recommendation_id.lower()}"


class GraphQueryService:
    def __init__(self, client: GraphClient):
        self.client = client

    def get_neighbors(self, service: str) -> GraphNeighborView:
        center = self.client.get_node(_service_node_id(service))
        if center is None:
            raise ValueError(f"Unknown service '{service}'")
        return GraphNeighborView(
            center=center,
            neighbors=self.client.get_neighbors(center.node_id, depth=2),
        )

    def get_pattern(self, failure_type: str) -> GraphPatternView:
        failure_node = self.client.get_node(_failure_node_id(failure_type))
        pattern_neighbors = self.client.get_neighbors(_failure_node_id(failure_type), depth=2)
        recommendations = []
        patterns = []
        for item in pattern_neighbors:
            node = item.get("node") or {}
            if node.get("node_type") == "Recommendation":
                recommendations.append(node)
            if node.get("node_type") == "OperationalPattern":
                patterns.append(node)
        return GraphPatternView(
            failure_type=failure_node.label if failure_node else failure_type,
            patterns=patterns,
            recommendations=recommendations,
        )

    def get_recommendation(self, recommendation_id: str) -> GraphRecommendationView:
        recommendation = self.client.get_node(_recommendation_node_id(recommendation_id))
        if recommendation is None:
            raise ValueError(f"Unknown recommendation '{recommendation_id}'")
        neighbors = self.client.get_neighbors(recommendation.node_id, depth=2)
        linked_failures = []
        linked_patterns = []
        for item in neighbors:
            node = item.get("node") or {}
            if node.get("node_type") == "FailureType":
                linked_failures.append(node)
            if node.get("node_type") == "OperationalPattern":
                linked_patterns.append(node)
        return GraphRecommendationView(
            recommendation=recommendation.model_dump(),
            linked_failures=linked_failures,
            linked_patterns=linked_patterns,
        )

    def run_natural_language_query(self, question: str) -> dict:
        text = question.lower()
        if "depend on" in text:
            component = text.split("depend on", 1)[1].strip().replace("?", "")
            component_node = self.client.find_nodes(node_type="Component", label=component, limit=1)
            if not component_node:
                return {"question": question, "answer": [], "reason": "No matching component found"}
            component_id = component_node[0].node_id
            edges = self.client.get_edges_for_node(component_id, relationship_type="DEPENDS_ON")
            services = []
            for edge in edges:
                if edge.from_node.startswith("Service:"):
                    service = self.client.get_node(edge.from_node)
                    if service:
                        services.append(service.model_dump())
            return {"question": question, "answer": services}

        if "highest success" in text or "best recommendation" in text:
            recommendations = self.client.find_nodes(node_type="Recommendation", limit=100)
            recommendations.sort(
                key=lambda node: (
                    -float(node.properties.get("success_rate", 0.0)),
                    -float(node.properties.get("times_used", 0)),
                    node.label,
                )
            )
            return {"question": question, "answer": [node.model_dump() for node in recommendations[:5]]}

        if "pattern" in text or "failure" in text:
            failures = self.client.find_nodes(node_type="FailureType", limit=100)
            return {"question": question, "answer": [node.model_dump() for node in failures[:10]]}

        return {
            "question": question,
            "answer": [],
            "reason": "Query parser currently supports dependency, recommendation, and failure-pattern prompts.",
        }


_query_service: GraphQueryService | None = None


def get_graph_queries() -> GraphQueryService:
    global _query_service
    if _query_service is None:
        _query_service = GraphQueryService(get_graph_client())
    return _query_service
