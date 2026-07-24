from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime

from knowledge.taxonomy import (
    FAILURE_TYPES,
    FIX_TYPES,
    SYMPTOM_TYPES,
    SEVERITY_LEVELS,
    ENVIRONMENTS,
)


class KnowledgeObject(BaseModel):
    incident_id: str = ""
    title: str = ""
    summary: str = ""
    service: str = "unknown"
    component: str = "unknown"
    failure_type: str = ""
    symptoms: List[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    environment: Literal["dev", "staging", "production"] = "production"
    root_cause: str = ""
    fix: str = ""
    fix_type: str = ""
    confidence: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.now)

    def to_embedding_text(self) -> str:
        parts = [
            self.service,
            self.component,
            self.failure_type,
            " ".join(self.symptoms),
            self.root_cause,
        ]
        return " ".join(p for p in parts if p)

    def to_search_payload(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "summary": self.summary,
            "service": self.service,
            "component": self.component,
            "failure_type": self.failure_type,
            "symptoms": self.symptoms,
            "severity": self.severity,
            "environment": self.environment,
            "root_cause": self.root_cause,
            "fix": self.fix,
            "fix_type": self.fix_type,
            "confidence": self.confidence,
        }


class ExplainableRecommendation(BaseModel):
    recommendation_id: str = ""
    recommendation: str
    confidence: float
    evidence: List[str] = Field(default_factory=list)
    reasoning: dict
    recommendation_stats: Optional[dict] = None
    operational_pattern: Optional[dict] = None
    graph_context: Optional[dict] = None
    ranked_recommendations: List[dict] = Field(default_factory=list)
    knowledge_object: Optional[KnowledgeObject] = None
    similar_incidents: List[dict] = Field(default_factory=list)


class SearchFilters(BaseModel):
    service: Optional[str] = None
    component: Optional[str] = None
    failure_type: Optional[str] = None
    severity: Optional[str] = None
    environment: Optional[str] = None
    fix_type: Optional[str] = None
