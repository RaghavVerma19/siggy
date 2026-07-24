from pydantic import BaseModel, Field, model_validator
from typing import List, Optional
from datetime import datetime


class Incident(BaseModel):
    id: str
    title: str
    summary: str
    root_cause: str
    fix: str
    affected_services: List[str]
    severity: str = "high"
    timestamp: datetime = Field(default_factory=datetime.now)


class NormalizedIncident(BaseModel):
    service: str
    component: str
    failure: str
    symptom: str
    root_cause: str
    fix: str


class IncidentQuery(BaseModel):
    title: str
    summary: str


class RecommendationResponse(BaseModel):
    current_incident: IncidentQuery
    similar_incidents: List[dict]
    normalized: NormalizedIncident
    recommended_fix: str
    confidence: float


class AgentAnalysisResponse(BaseModel):
    current_incident: dict
    normalized: NormalizedIncident
    similar_incidents: List[dict]
    analysis: dict


class TelemetrySummary(BaseModel):
    service: str
    latency: str = "unknown"
    error_rate: str = "unknown"
    top_errors: List[str] = []
    affected_dependencies: List[str] = []
    severity: str = "medium"
    summary: str = ""


class InvestigationResponse(BaseModel):
    query: str
    telemetry_summary: TelemetrySummary
    raw_data: dict = {}
    time_range: dict = {}


class ExperienceRecord(BaseModel):
    recommendation_id: str = ""
    recommendation: str
    accepted: bool = False
    worked: Optional[bool] = None
    resolution_time_seconds: int = 0
    confidence: float = 0.0
    incident_id: str = ""
    engineer_feedback: str = ""
    service: str = "unknown"
    component: str = "unknown"
    failure_type: str = ""
    symptoms: List[str] = []
    notes: str = ""
    resolution_time: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_fields(cls, values):
        if not isinstance(values, dict):
            return values

        if values.get("engineer_feedback") in (None, "") and values.get("notes"):
            values["engineer_feedback"] = values["notes"]

        if not values.get("resolution_time_seconds") and values.get("resolution_time"):
            raw = str(values["resolution_time"]).strip().lower()
            if raw.isdigit():
                values["resolution_time_seconds"] = int(raw)
            elif "minute" in raw:
                number = "".join(ch for ch in raw if ch.isdigit())
                values["resolution_time_seconds"] = int(number) * 60 if number else 0
            elif "hour" in raw:
                number = "".join(ch for ch in raw if ch.isdigit())
                values["resolution_time_seconds"] = int(number) * 3600 if number else 0
        return values

    def to_experience_create(self):
        from experience.models import ExperienceRecordCreate

        return ExperienceRecordCreate(
            incident_id=self.incident_id,
            recommendation_id=self.recommendation_id,
            recommendation=self.recommendation,
            accepted=self.accepted,
            worked=self.worked if self.worked is not None else False,
            resolution_time_seconds=self.resolution_time_seconds,
            engineer_feedback=self.engineer_feedback,
            confidence=self.confidence,
            service=self.service,
            component=self.component,
            failure_type=self.failure_type,
            symptoms=self.symptoms,
        )
