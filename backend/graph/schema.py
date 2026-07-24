from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


NODE_TYPES = [
    "Service",
    "Component",
    "FailureType",
    "Recommendation",
    "OperationalPattern",
]


RELATIONSHIP_TYPES = [
    "DEPENDS_ON",
    "FAILS_WITH",
    "RESOLVED_BY",
    "OBSERVED_PATTERN",
    "DESCRIBES_FAILURE",
    "USES_RECOMMENDATION",
    "INVOLVES_COMPONENT",
]


class GraphNode(BaseModel):
    node_id: str
    node_type: str
    label: str
    properties: dict = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=datetime.now)


class GraphEdge(BaseModel):
    edge_id: str
    from_node: str
    to_node: str
    relationship_type: str
    properties: dict = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=datetime.now)


class GraphNeighborView(BaseModel):
    center: GraphNode
    neighbors: list[dict] = Field(default_factory=list)


class GraphPatternView(BaseModel):
    failure_type: str
    patterns: list[dict] = Field(default_factory=list)
    recommendations: list[dict] = Field(default_factory=list)


class GraphRecommendationView(BaseModel):
    recommendation: dict
    linked_failures: list[dict] = Field(default_factory=list)
    linked_patterns: list[dict] = Field(default_factory=list)


class GraphContext(BaseModel):
    service: Optional[dict] = None
    component: Optional[dict] = None
    failure: Optional[dict] = None
    related_services: list[dict] = Field(default_factory=list)
    recommendations: list[dict] = Field(default_factory=list)
    patterns: list[dict] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
