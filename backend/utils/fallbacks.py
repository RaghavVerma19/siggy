from __future__ import annotations

import json
import re

from knowledge.taxonomy import (
    ENVIRONMENTS,
    FAILURE_TYPES,
    FIX_TYPES,
    SEVERITY_LEVELS,
    SYMPTOM_TYPES,
)
from models.incident import NormalizedIncident


COMPONENT_KEYWORDS = [
    "redis",
    "kafka",
    "postgresql",
    "postgres",
    "mysql",
    "mongodb",
    "elasticsearch",
    "nginx",
    "rabbitmq",
    "cpu",
    "memory",
    "disk",
    "network",
    "dns",
]

SERVICE_SUFFIXES = ("service", "api", "worker", "consumer", "processor")


def closest_match(value: str, valid_values: list[str], default: str) -> str:
    value_lower = (value or "").lower().replace(" ", "_")
    if not value_lower:
        return default
    for candidate in valid_values:
        if value_lower == candidate or value_lower in candidate or candidate in value_lower:
            return candidate
    words = value_lower.split("_")
    for candidate in valid_values:
        if any(word and word in candidate for word in words):
            return candidate
    return default


def infer_service(text: str, fallback: str = "unknown") -> str:
    from knowledge.normalization_v2 import _context_service
    return _context_service(text)


def infer_component(text: str) -> str:
    from knowledge.normalization_v2 import _context_component
    return _context_component(text)


def infer_failure_type(text: str, component: str = "unknown") -> str:
    from knowledge.normalization_v2 import _regex_first_failure_type, _alias_failure_type
    regex_ft, _ = _regex_first_failure_type(text)
    if regex_ft:
        return regex_ft
    alias_ft = _alias_failure_type(text)
    if alias_ft:
        return alias_ft
    lower = text.lower()
    if "pool" in lower and ("exhaust" in lower or "no free connection" in lower):
        return "connection_pool_exhaustion"
    if "oom" in lower or "out of memory" in lower:
        return "oom_killed"
    if "network partition" in lower:
        return "network_partition"
    if "disk full" in lower or "no space left" in lower:
        return "disk_full"
    if "cpu" in lower and ("spike" in lower or "saturation" in lower or "100%" in lower):
        return "cpu_saturation"
    if "deadlock" in lower:
        return "deadlock"
    if "memory leak" in lower:
        return "memory_leak"
    if "timeout" in lower or "timing out" in lower:
        return "timeout"
    if "broker" in lower and ("unavailable" in lower or "down" in lower):
        return "broker_unavailable"
    if "infinite loop" in lower:
        return "infinite_loop"
    if "query" in lower and ("slow" in lower or "overload" in lower):
        return "query_overload"
    if "certificate" in lower and ("expired" in lower or "tls" in lower):
        return "certificate_expired"
    if "dns" in lower and ("resolution" in lower or "lookup" in lower):
        return "dns_resolution_failure"
    if "rate limit" in lower or "429" in lower:
        return "rate_limit_exceeded"
    if "dependency" in lower and ("unavailable" in lower or "down" in lower):
        return "dependency_unavailable"
    if component == "redis" and ("connection" in lower or "pool" in lower):
        return "connection_pool_exhaustion"
    return "timeout"


def infer_fix_type(text: str, component: str, failure_type: str) -> str:
    from knowledge.normalization_v2 import _regex_first_fix_type, _alias_fix_type
    regex_ft, _ = _regex_first_fix_type(text)
    if regex_ft:
        return regex_ft
    alias_ft = _alias_fix_type(text)
    if alias_ft:
        return alias_ft
    lower = text.lower()
    if "restart" in lower:
        return "restart_service"
    if "pool" in lower and ("increase" in lower or "expand" in lower):
        return "increase_pool_size"
    if "rollback" in lower:
        return "rollback_deployment"
    if "scale" in lower:
        return "scale_horizontally"
    if "cache" in lower and "clear" in lower:
        return "clear_cache"
    if "memory" in lower and ("increase" in lower or "limit" in lower):
        return "increase_memory_limit"
    if "leak" in lower:
        return "fix_memory_leak"
    if "circuit breaker" in lower:
        return "add_circuit_breaker"
    if "query" in lower and ("reduce" in lower or "optimiz" in lower):
        return "reduce_query_load"
    if "replica" in lower:
        return "move_to_read_replica"
    if "backoff" in lower or "retry" in lower:
        return "add_exponential_backoff"
    if "disk" in lower and ("free" in lower or "cleanup" in lower):
        return "free_disk_space"
    if "certificate" in lower or "tls" in lower:
        return "renew_certificate"
    if "retention" in lower:
        return "reduce_log_retention"
    if "autoscaler" in lower:
        return "add_autoscaler"
    if component == "redis" and failure_type == "connection_pool_exhaustion":
        return "increase_pool_size"
    if failure_type == "timeout":
        return "restart_service"
    return "restart_service"


def infer_symptoms(text: str) -> list[str]:
    from knowledge.normalization_v2 import _alias_symptoms
    matched = _alias_symptoms(text)
    if matched:
        return matched
    lower = text.lower()
    symptoms = []
    if "latency" in lower or "slow" in lower:
        symptoms.append("high_latency")
    if "timeout" in lower:
        symptoms.append("request_timeout")
    if "cpu" in lower:
        symptoms.append("cpu_spike")
    if "memory" in lower or "oom" in lower:
        symptoms.append("memory_spike")
    if "error rate" in lower or "5xx" in lower or "504" in lower or "500" in lower:
        symptoms.append("error_rate_increase")
    if "unavailable" in lower or "down" in lower:
        symptoms.append("service_unavailable")
    if "refused" in lower:
        symptoms.append("connection_refused")
    if "queue" in lower or "backlog" in lower:
        symptoms.append("queue_backup")
    if "inconsisten" in lower:
        symptoms.append("data_inconsistency")
    if "restart" in lower or "crashloop" in lower:
        symptoms.append("pod_restarts")
    if "query" in lower and "slow" in lower:
        symptoms.append("slow_queries")
    if "5xx" in lower:
        symptoms.append("5xx_errors")
    deduped = []
    for symptom in symptoms:
        if symptom in SYMPTOM_TYPES and symptom not in deduped:
            deduped.append(symptom)
    return deduped[:3] or ["high_latency"]


def infer_severity(text: str) -> str:
    from knowledge.normalization_v2 import _regex_first_severity, _alias_severity
    regex_sev, _ = _regex_first_severity(text)
    if regex_sev:
        return regex_sev
    alias_sev = _alias_severity(text)
    if alias_sev:
        return alias_sev
    lower = text.lower()
    if any(token in lower for token in ["critical", "sev1", "sev-1", "outage", "down"]):
        return "critical"
    if any(token in lower for token in ["504", "503", "timeout", "degraded", "high latency"]):
        return "high"
    return "medium"


def infer_fix_text(component: str, failure_type: str) -> str:
    if component == "redis" and failure_type == "connection_pool_exhaustion":
        return "Increase Redis connection pool size and recycle stuck connections."
    if failure_type == "timeout":
        return "Restart the affected service and verify dependency health."
    if failure_type == "query_overload":
        return "Reduce query load and add or tune indexes."
    if failure_type == "oom_killed":
        return "Increase memory limit and identify the memory growth path."
    return "Investigate the affected dependency and restart the impacted service if needed."


def normalize_incident_fallback(title: str, summary: str) -> NormalizedIncident:
    from knowledge.normalization_v2 import normalize_deterministic
    normalized, _report = normalize_deterministic(title, summary)
    symptoms = normalized.get("symptoms", ["high_latency"])
    return NormalizedIncident(
        service=normalized.get("service", "unknown"),
        component=normalized.get("component", "unknown"),
        failure=normalized.get("failure_type", "timeout"),
        symptom=symptoms[0] if symptoms else "high_latency",
        root_cause=normalized.get("root_cause", ""),
        fix=normalized.get("fix", ""),
    )


def normalize_knowledge_fallback(title: str, summary: str, incident_id: str = "") -> dict:
    from knowledge.normalization_v2 import normalize_deterministic
    normalized, _report = normalize_deterministic(title, summary, incident_id)
    return normalized


def summarize_telemetry_fallback(raw_data: dict) -> dict:
    service = raw_data.get("service", "unknown")
    logs = raw_data.get("logs", [])
    if not isinstance(logs, list):
        if isinstance(logs, dict):
            inner = logs.get("logs", logs.get("data", []))
            logs = inner if isinstance(inner, list) else []
        else:
            logs = []
    traces = raw_data.get("traces", [])
    if not isinstance(traces, list):
        if isinstance(traces, dict):
            inner = traces.get("traces", traces.get("data", []))
            traces = inner if isinstance(inner, list) else []
        else:
            traces = []
    latency_metric = raw_data.get("latency_metric", {})
    error_metric = raw_data.get("error_metric", {})
    combined_text = " ".join(
        [
            raw_data.get("query", ""),
            json.dumps(logs[:10]),
            json.dumps(traces[:5]),
            json.dumps(latency_metric),
            json.dumps(error_metric),
        ]
    )
    component = infer_component(combined_text)
    dependencies = []
    if component != "unknown":
        dependencies.append(component)
    top_errors = []
    for entry in logs[:3]:
        if not isinstance(entry, dict):
            continue
        body = entry.get("body") or entry.get("message") or str(entry)
        top_errors.append(str(body)[:120])
    latency = _extract_metric_value(latency_metric, combined_text, default="unknown")
    error_rate = _extract_error_rate(error_metric, combined_text)
    severity = _severity_from_metrics(latency, error_rate)
    summary = f"{service} is degraded with {failure_phrase(infer_failure_type(combined_text, component))} affecting {component}."
    return {
        "service": service,
        "latency": latency,
        "error_rate": error_rate,
        "top_errors": top_errors,
        "affected_dependencies": dependencies,
        "severity": severity,
        "summary": summary,
    }


def analyze_incident_fallback(title: str, summary: str, normalized: NormalizedIncident, similar_incidents: list[dict]) -> dict:
    evidence = []
    if normalized.service != "unknown":
        evidence.append(f"Service match focus: {normalized.service}")
    if normalized.component != "unknown":
        evidence.append(f"Component involved: {normalized.component}")
    evidence.append(f"Failure type inferred as {normalized.failure}")
    if similar_incidents:
        top = similar_incidents[0]
        evidence.append(f"Top similar incident score {top.get('similarity', 0):.2f}")
        if top.get("fix"):
            recommended_fix = top["fix"]
        else:
            recommended_fix = normalized.fix
    else:
        recommended_fix = normalized.fix
    confidence = 0.82 if similar_incidents else 0.58
    return {
        "reasoning_chain": {
            "compare": "Compared the current incident against structured memory and local heuristics.",
            "identify": f"Most likely pattern is {normalized.failure} in {normalized.component}.",
            "evidence": evidence,
            "reason": "The fallback analyzer used component, symptom, and similarity evidence because the external LLM was unavailable.",
        },
        "confidence": confidence,
        "recommended_fix": recommended_fix,
        "investigation_steps": [
            f"Check {normalized.component} health and saturation signals.",
            "Review recent errors and slow requests for the affected service.",
            "Apply the recommendation if the failure signature matches production evidence.",
        ],
        "common_pattern": f"{normalized.component} instability causing {normalized.symptom}",
    }


def failure_phrase(failure_type: str) -> str:
    return failure_type.replace("_", " ")


def _root_cause_text(component: str, failure_type: str) -> str:
    if component != "unknown":
        return f"{component} experienced {failure_phrase(failure_type)}."
    return f"System experienced {failure_phrase(failure_type)}."


def _extract_metric_value(metric: dict, text: str, default: str = "unknown") -> str:
    metric_text = json.dumps(metric)
    match = re.search(r"(\d+(?:\.\d+)?)\s*(ms|s|%)", metric_text or text, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1)}{match.group(2).lower()}"
    return default


def _extract_error_rate(metric: dict, text: str) -> str:
    metric_text = json.dumps(metric)
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", metric_text or text, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1)}%"
    if "5xx" in text.lower() or "error" in text.lower():
        return "5%"
    return "0.5%"


def _severity_from_metrics(latency: str, error_rate: str) -> str:
    latency_seconds = _to_seconds(latency)
    error_percent = _to_percent(error_rate)
    if error_percent > 10 or latency_seconds > 5:
        return "critical"
    if error_percent > 1 or latency_seconds > 2:
        return "high"
    return "medium"


def _to_seconds(value: str) -> float:
    if not value or value == "unknown":
        return 0.0
    match = re.search(r"(\d+(?:\.\d+)?)(ms|s)", value)
    if not match:
        return 0.0
    number = float(match.group(1))
    unit = match.group(2)
    return number / 1000 if unit == "ms" else number


def _to_percent(value: str) -> float:
    if not value:
        return 0.0
    match = re.search(r"(\d+(?:\.\d+)?)", value)
    return float(match.group(1)) if match else 0.0
