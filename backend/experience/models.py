from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


FIX_TYPE_TO_RECOMMENDATION_ID = {
    "restart_service": "RESTART_SERVICE",
    "increase_pool_size": "INCREASE_POOL_SIZE",
    "rollback_deployment": "ROLLBACK_DEPLOYMENT",
    "scale_horizontally": "SCALE_HORIZONTALLY",
    "clear_cache": "CLEAR_CACHE",
    "increase_memory_limit": "INCREASE_MEMORY_LIMIT",
    "fix_memory_leak": "FIX_MEMORY_LEAK",
    "add_circuit_breaker": "ADD_CIRCUIT_BREAKER",
    "reduce_query_load": "REDUCE_QUERY_LOAD",
    "move_to_read_replica": "MOVE_TO_READ_REPLICA",
    "add_exponential_backoff": "ADD_EXPONENTIAL_BACKOFF",
    "free_disk_space": "FREE_DISK_SPACE",
    "renew_certificate": "RENEW_CERTIFICATE",
    "reduce_log_retention": "REDUCE_LOG_RETENTION",
    "add_autoscaler": "ADD_AUTOSCALER",
}


def canonicalize_recommendation_id(
    recommendation_id: str = "",
    recommendation: str = "",
    fix_type: str = "",
) -> str:
    if recommendation_id:
        return _slug_to_upper(recommendation_id)
    if fix_type:
        return FIX_TYPE_TO_RECOMMENDATION_ID.get(fix_type, _slug_to_upper(fix_type))
    if recommendation:
        return _slug_to_upper(recommendation)
    return "INVESTIGATE_FURTHER"


def recommendation_label_from_id(recommendation_id: str) -> str:
    return recommendation_id.replace("_", " ").title()


def _slug_to_upper(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned.upper() if cleaned else "INVESTIGATE_FURTHER"


class ExperienceRecordCreate(BaseModel):
    incident_id: str = ""
    recommendation_id: str = ""
    recommendation: str
    accepted: bool = False
    worked: bool = False
    resolution_time_seconds: int = 0
    engineer_feedback: str = ""
    confidence: float = 0.0
    service: str = "unknown"
    component: str = "unknown"
    failure_type: str = ""
    symptoms: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)


class ExperienceRecord(BaseModel):
    experience_id: str
    incident_id: str = ""
    recommendation_id: str
    recommendation: str
    accepted: bool = False
    worked: bool = False
    resolution_time_seconds: int = 0
    engineer_feedback: str = ""
    confidence: float = 0.0
    service: str = "unknown"
    component: str = "unknown"
    failure_type: str = ""
    symptoms: list[str] = Field(default_factory=list)
    timestamp: datetime


class RecommendationStatistics(BaseModel):
    recommendation_id: str
    recommendation: str
    times_used: int = 0
    accepted_count: int = 0
    worked_count: int = 0
    success_rate: float = 0.0
    acceptance_rate: float = 0.0
    avg_resolution_time_seconds: float = 0.0
    avg_confidence: float = 0.0
    last_used_at: Optional[datetime] = None


class OperationalPattern(BaseModel):
    pattern_id: str
    failure_type: str
    services: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    total_occurrences: int = 0
    best_recommendation_id: str
    best_recommendation: str
    success_rate: float = 0.0
    avg_resolution_time_seconds: float = 0.0
    evidence_count: int = 0
    last_seen: Optional[datetime] = None


class RankedRecommendation(BaseModel):
    recommendation_id: str
    recommendation: str
    similarity_score: float = 0.0
    success_score: float = 0.0
    adjusted_success_score: float = 0.0
    resolution_score: float = 0.0
    confidence_score: float = 0.0
    metadata_score: float = 0.0
    experience_multiplier: float = 1.0
    final_score: float = 0.0
    times_seen_in_matches: int = 0
    statistics: RecommendationStatistics
    pattern: Optional[OperationalPattern] = None
    evidence: list[str] = Field(default_factory=list)
