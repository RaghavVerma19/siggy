from __future__ import annotations

import hashlib
from datetime import datetime

from experience.aggregator import ExperiencePatternAggregator, get_pattern_aggregator
from experience.models import canonicalize_recommendation_id
from experience.statistics import ExperienceStatisticsEngine, get_statistics_engine
from graph.client import GraphClient, get_graph_client
from graph.schema import GraphEdge, GraphNode
from knowledge.schema import KnowledgeObject
from memory.vector_store import get_store


def _node_id(node_type: str, key: str) -> str:
    return f"{node_type}:{key.lower()}"


def _edge_id(from_node: str, relationship_type: str, to_node: str) -> str:
    raw = f"{from_node}:{relationship_type}:{to_node}"
    return hashlib.md5(raw.encode()).hexdigest()


class GraphBuilder:
    def __init__(
        self,
        client: GraphClient,
        statistics: ExperienceStatisticsEngine,
        aggregator: ExperiencePatternAggregator,
    ):
        self.client = client
        self.statistics = statistics
        self.aggregator = aggregator

    def sync_knowledge_object(self, ko: KnowledgeObject) -> dict:
        service_id = _node_id("Service", ko.service)
        component_id = _node_id("Component", ko.component)
        failure_id = _node_id("FailureType", ko.failure_type)
        canonical_recommendation_id = canonicalize_recommendation_id(
            recommendation=ko.fix,
            fix_type=ko.fix_type,
        )
        recommendation_id = _node_id("Recommendation", canonical_recommendation_id)

        self.client.upsert_node(
            GraphNode(
                node_id=service_id,
                node_type="Service",
                label=ko.service,
                properties={"environment": ko.environment, "severity": ko.severity},
            )
        )
        self.client.upsert_node(
            GraphNode(
                node_id=component_id,
                node_type="Component",
                label=ko.component,
                properties={"service": ko.service},
            )
        )
        self.client.upsert_node(
            GraphNode(
                node_id=failure_id,
                node_type="FailureType",
                label=ko.failure_type,
                properties={"severity": ko.severity, "symptoms": ko.symptoms},
            )
        )

        stats = self.statistics.get_recommendation_statistics(canonical_recommendation_id)
        self.client.upsert_node(
            GraphNode(
                node_id=recommendation_id,
                node_type="Recommendation",
                label=ko.fix or stats.recommendation,
                properties={
                    "recommendation_id": stats.recommendation_id or canonical_recommendation_id,
                    "success_rate": stats.success_rate,
                    "avg_resolution_time_seconds": stats.avg_resolution_time_seconds,
                    "times_used": stats.times_used,
                },
            )
        )

        self._upsert_edge(service_id, "DEPENDS_ON", component_id, {"source": "knowledge_object"})
        self._upsert_edge(component_id, "FAILS_WITH", failure_id, {"source": "knowledge_object"})
        self._upsert_edge(failure_id, "RESOLVED_BY", recommendation_id, {"source": "knowledge_object"})

        return {
            "service_id": service_id,
            "component_id": component_id,
            "failure_id": failure_id,
            "recommendation_node_id": recommendation_id,
        }

    def sync_operational_patterns(self) -> list[dict]:
        patterns = self.aggregator.build_patterns()
        synced = []
        for pattern in patterns:
            pattern_node_id = _node_id("OperationalPattern", pattern.pattern_id)
            failure_id = _node_id("FailureType", pattern.failure_type)
            recommendation_id = _node_id("Recommendation", pattern.best_recommendation_id)
            self.client.upsert_node(
                GraphNode(
                    node_id=failure_id,
                    node_type="FailureType",
                    label=pattern.failure_type,
                    properties={},
                )
            )
            self.client.upsert_node(
                GraphNode(
                    node_id=pattern_node_id,
                    node_type="OperationalPattern",
                    label=pattern.pattern_id,
                    properties=pattern.model_dump(),
                )
            )
            self.client.upsert_node(
                GraphNode(
                    node_id=recommendation_id,
                    node_type="Recommendation",
                    label=pattern.best_recommendation,
                    properties={
                        "recommendation_id": pattern.best_recommendation_id,
                        "success_rate": pattern.success_rate,
                        "avg_resolution_time_seconds": pattern.avg_resolution_time_seconds,
                        "evidence_count": pattern.evidence_count,
                    },
                )
            )
            self._upsert_edge(pattern_node_id, "DESCRIBES_FAILURE", failure_id, {"source": "pattern"})
            self._upsert_edge(pattern_node_id, "USES_RECOMMENDATION", recommendation_id, {"source": "pattern"})
            for service in pattern.services:
                service_id = _node_id("Service", service)
                self.client.upsert_node(
                    GraphNode(
                        node_id=service_id,
                        node_type="Service",
                        label=service,
                        properties={},
                    )
                )
                self._upsert_edge(service_id, "OBSERVED_PATTERN", pattern_node_id, {"source": "pattern"})
            for component in pattern.components:
                component_id = _node_id("Component", component)
                self.client.upsert_node(
                    GraphNode(
                        node_id=component_id,
                        node_type="Component",
                        label=component,
                        properties={},
                    )
                )
                self._upsert_edge(pattern_node_id, "INVOLVES_COMPONENT", component_id, {"source": "pattern"})
            synced.append(pattern.model_dump())
        return synced

    def sync_all(self) -> dict:
        store = get_store()
        synced_knowledge = []
        for payload in store.get_all():
            if payload.get("storage_format") != "knowledge":
                continue
            ko = KnowledgeObject(**{key: payload[key] for key in KnowledgeObject.model_fields if key in payload})
            synced_knowledge.append(self.sync_knowledge_object(ko))
        synced_patterns = self.sync_operational_patterns()
        return {
            "knowledge_objects_synced": len(synced_knowledge),
            "patterns_synced": len(synced_patterns),
        }

    def _upsert_edge(self, from_node: str, relationship_type: str, to_node: str, properties: dict) -> None:
        self.client.upsert_edge(
            GraphEdge(
                edge_id=_edge_id(from_node, relationship_type, to_node),
                from_node=from_node,
                to_node=to_node,
                relationship_type=relationship_type,
                properties=properties,
                updated_at=datetime.now(),
            )
        )


_builder: GraphBuilder | None = None


def get_graph_builder() -> GraphBuilder:
    global _builder
    if _builder is None:
        _builder = GraphBuilder(get_graph_client(), get_statistics_engine(), get_pattern_aggregator())
    return _builder
