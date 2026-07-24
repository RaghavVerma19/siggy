from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from knowledge.taxonomy import (
    COMPONENT_ALIASES,
    ENVIRONMENT_ALIASES,
    ENVIRONMENTS,
    FAILURE_TYPE_ALIASES,
    FAILURE_TYPES,
    FIX_TYPE_ALIASES,
    FIX_TYPES,
    SEVERITY_ALIASES,
    SEVERITY_LEVELS,
    SERVICE_ALIASES,
    SYMPTOM_ALIASES,
    SYMPTOM_TYPES,
)

SERVICE_SUFFIXES = ("service", "api", "worker", "consumer", "processor")


@dataclass
class NormalizationReport:
    field_matches: dict[str, bool] = field(default_factory=dict)
    field_expected: dict[str, str] = field(default_factory=dict)
    field_predicted: dict[str, str] = field(default_factory=dict)
    method: str = "regex-first"
    alias_matched: list[str] = field(default_factory=list)
    regex_matched: list[str] = field(default_factory=list)


_REGEX_RULES: list[tuple[str, re.Pattern[str], str, str]] = [
    (
        "failure_type",
        re.compile(r"redis\s+(?:had\s+)?no\s+free\s+connection|connection\s+pool\s+(?:was\s+)?exhausted|all\s+client\s+slot.*busy|pool.*exhaust|no\s+free\s+connection.*pool", re.IGNORECASE),
        "connection_pool_exhaustion",
        "redis_pool",
    ),
    (
        "failure_type",
        re.compile(r"redis\s+(?:node\s+)?election|redis\s+failover|failover\s+storm|failover\s+event|node\s+failover|cache\s+failover|redis\s+recover", re.IGNORECASE),
        "redis_failover_storm",
        "redis_failover",
    ),
    (
        "failure_type",
        re.compile(r"kafka\s+disk|broker.*disk|disk.*kafka|kafka.*storage.*(?:full|exceed|pressure|95%)|topic\s+retention.*disk|retention.*broker|kafka.*reject", re.IGNORECASE),
        "kafka_disk_pressure",
        "kafka_disk",
    ),
    (
        "failure_type",
        re.compile(r"(?:full\s+table\s+scan|missing\s+index|unindexed|query\s+overload|scanned.*table\s+without|hammered.*unindexed|slow\s+quer(?:y|ies))", re.IGNORECASE),
        "query_overload",
        "query_overload",
    ),
    (
        "failure_type",
        re.compile(r"certificate\s+expir|tls\s+expir|ssl\s+expir|stale\s+(?:tls|ssl|certificate)|missed\s+certificate\s+rotation|certificate.*expir", re.IGNORECASE),
        "certificate_expired",
        "certificate",
    ),
    (
        "failure_type",
        re.compile(r"oom\s+kill|out\s+of\s+memory|killed\s+by\s+oom|oom\b", re.IGNORECASE),
        "oom_killed",
        "oom",
    ),
    (
        "failure_type",
        re.compile(r"infinite\s+retry|retry\s+loop|endless\s+loop|retried.*(?:forever|all\s+at\s+once|immediately|without\s+backoff|instead\s+of\s+waiting)", re.IGNORECASE),
        "infinite_loop",
        "retry_loop",
    ),
    (
        "failure_type",
        re.compile(r"cpu\s+(?:to\s+)?100|cpu\s+pinned|100%\s+cpu|cpu\s+saturat|cpu\s+spike|cpu\s+burn|high\s+cpu", re.IGNORECASE),
        "cpu_saturation",
        "cpu_saturation",
    ),
    (
        "failure_type",
        re.compile(r"memory\s+leak|heap\s+growth|heap\s+exhaust", re.IGNORECASE),
        "memory_leak",
        "memory_leak",
    ),
    (
        "failure_type",
        re.compile(r"connection\s+pool\s+exhaustion|db.*connection.*exhaust|database.*connection.*exhaust", re.IGNORECASE),
        "database_connection_exhaustion",
        "db_pool",
    ),
    (
        "failure_type",
        re.compile(r"crash\s*loop|pod.*restart|crashloopbackoff", re.IGNORECASE),
        "pod_crash_loop",
        "pod_restart",
    ),
    (
        "failure_type",
        re.compile(r"replication\s+lag|replica\s+delay|sync\s+delay", re.IGNORECASE),
        "replication_lag",
        "replication",
    ),
    (
        "fix_type",
        re.compile(r"(?:increase|expand|scale|grow|bigger)\s+(?:connection\s+)?pool\s+size|pool\s+size\s+increase|add\s+more\s+connection", re.IGNORECASE),
        "increase_pool_size",
        "pool_size",
    ),
    (
        "fix_type",
        re.compile(r"backoff|exponential\s+backoff|retry.*backoff|with\s+backoff|backoff\s+strategy", re.IGNORECASE),
        "add_exponential_backoff",
        "backoff",
    ),
    (
        "fix_type",
        re.compile(r"rollback|revert\s+(?:deploy|release)", re.IGNORECASE),
        "rollback_deployment",
        "rollback",
    ),
    (
        "fix_type",
        re.compile(r"(?:add|create|build|tune)\s+(?:a\s+)?(?:missing\s+)?index|index\s+the\s+table", re.IGNORECASE),
        "add_index",
        "add_index",
    ),
    (
        "fix_type",
        re.compile(r"renew\s+certificate|rotate\s+(?:certificate|tls)|certificate\s+renewal|tls\s+renewal", re.IGNORECASE),
        "renew_certificate",
        "cert_renew",
    ),
    (
        "fix_type",
        re.compile(r"reduce\s+(?:log\s+)?retention|shorten\s+retention|lower\s+retention|retention\s+policy", re.IGNORECASE),
        "reduce_log_retention",
        "retention",
    ),
    (
        "fix_type",
        re.compile(r"reduce\s+quer(?:y|ies)\s+load|throttle\s+quer(?:y|ies)|limit\s+quer(?:y|ies)", re.IGNORECASE),
        "reduce_query_load",
        "reduce_query",
    ),
    (
        "fix_type",
        re.compile(r"optimize\s+quer(?:y|ies)\s+plan|rewrite\s+quer(?:y|ies)|query\s+optimization|tune\s+quer(?:y|ies)\s+plan", re.IGNORECASE),
        "optimize_query_plan",
        "query_opt",
    ),
    (
        "severity",
        re.compile(r"critical|sev[\s-]?0|p0|full\s+outage|complete\s+outage", re.IGNORECASE),
        "critical",
        "sev_critical",
    ),
    (
        "severity",
        re.compile(r"sev[\s-]?1\b|p1\b|severe|major", re.IGNORECASE),
        "high",
        "sev_high",
    ),
    (
        "severity",
        re.compile(r"sev[\s-]?2\b|p2\b|moderate|warning|degraded", re.IGNORECASE),
        "medium",
        "sev_medium",
    ),
    (
        "severity",
        re.compile(r"sev[\s-]?3\b|p3\b|minor|info|low", re.IGNORECASE),
        "low",
        "sev_low",
    ),
    (
        "fix_type",
        re.compile(r"restart\s+(?:the\s+)?(?:affected\s+)?service|service\s+restart", re.IGNORECASE),
        "restart_service",
        "restart",
    ),
    (
        "fix_type",
        re.compile(r"scale\s+(?:horizontally|out|up\s+instances)|add\s+instances|more\s+replicas|horizontal\s+scale", re.IGNORECASE),
        "scale_horizontally",
        "scale_h",
    ),
    (
        "fix_type",
        re.compile(r"clear\s+cache|flush\s+cache|evict\s+cache", re.IGNORECASE),
        "clear_cache",
        "clear_cache",
    ),
    (
        "fix_type",
        re.compile(r"free\s+disk\s+space|clean(?:up)?\s+disk|remove\s+old\s+data", re.IGNORECASE),
        "free_disk_space",
        "free_disk",
    ),
    (
        "fix_type",
        re.compile(r"move\s+to\s+read\s+replica|add\s+read\s+replica|use\s+replica", re.IGNORECASE),
        "move_to_read_replica",
        "read_replica",
    ),
    (
        "fix_type",
        re.compile(r"fix\s+memory\s+leak|patch\s+leak|memory\s+leak\s+fix", re.IGNORECASE),
        "fix_memory_leak",
        "fix_leak",
    ),
    (
        "fix_type",
        re.compile(r"increase\s+memory\s+limit|more\s+memory|bump\s+memory", re.IGNORECASE),
        "increase_memory_limit",
        "mem_limit",
    ),
    (
        "fix_type",
        re.compile(r"add\s+circuit\s+breaker|enable\s+circuit\s+breaker", re.IGNORECASE),
        "add_circuit_breaker",
        "circuit_breaker",
    ),
    (
        "fix_type",
        re.compile(r"add\s+autoscaler|enable\s+autoscaler|\bhpa\b", re.IGNORECASE),
        "add_autoscaler",
        "autoscaler",
    ),
    (
        "fix_type",
        re.compile(r"scale\s+vertically|vertical\s+scale|bigger\s+instance|upgrade\s+instance", re.IGNORECASE),
        "scale_vertically",
        "scale_v",
    ),
]

_COMPONENT_CONTEXT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bredis\b", re.IGNORECASE), "redis"),
    (re.compile(r"\bkafka\b", re.IGNORECASE), "kafka"),
    (re.compile(r"\bpostgre(?:sql|s)?\b|\bpg\b", re.IGNORECASE), "postgresql"),
    (re.compile(r"\bmysql\b", re.IGNORECASE), "mysql"),
    (re.compile(r"\bmongo(?:db)?\b", re.IGNORECASE), "mongodb"),
    (re.compile(r"\belastic(?:search)?\b|\bes\b", re.IGNORECASE), "elasticsearch"),
    (re.compile(r"\bnginx\b", re.IGNORECASE), "nginx"),
    (re.compile(r"\brabbitmq\b|\brmq\b", re.IGNORECASE), "rabbitmq"),
    (re.compile(r"\bcpu\b|\bprocessor\b", re.IGNORECASE), "cpu"),
    (re.compile(r"\bmemory\b|\bmem\b|\bram\b", re.IGNORECASE), "memory"),
    (re.compile(r"\bdisk\b|\bstorage\b|\bvolume\b", re.IGNORECASE), "disk"),
    (re.compile(r"\bnetwork\b|\bnet\b", re.IGNORECASE), "network"),
    (re.compile(r"\bdns\b", re.IGNORECASE), "dns"),
    (re.compile(r"\btls\b|\bssl\b|\bcertificate\b", re.IGNORECASE), "nginx"),
]

_SERVICE_CONTEXT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcheckout\b", re.IGNORECASE), "checkout"),
    (re.compile(r"\bpayment\b", re.IGNORECASE), "payment"),
    (re.compile(r"\bsession\b", re.IGNORECASE), "session"),
    (re.compile(r"\bauth\b", re.IGNORECASE), "auth"),
    (re.compile(r"\bgateway\b", re.IGNORECASE), "gateway"),
    (re.compile(r"\border[- ]?processor\b", re.IGNORECASE), "order-processor"),
    (re.compile(r"\border[- ]?service\b|\borders\b", re.IGNORECASE), "order-service"),
    (re.compile(r"\bnotification[- ]?service\b", re.IGNORECASE), "notification-service"),
    (re.compile(r"\banalytics[- ]?processor\b", re.IGNORECASE), "analytics-processor"),
    (re.compile(r"\bevent[- ]?processor\b", re.IGNORECASE), "event-processor"),
    (re.compile(r"\bpayment[- ]?worker\b", re.IGNORECASE), "payment-worker"),
    (re.compile(r"\binventory\b", re.IGNORECASE), "inventory"),
    (re.compile(r"\bbilling\b", re.IGNORECASE), "billing"),
    (re.compile(r"\bapi\b", re.IGNORECASE), "api"),
]


def _alias_lookup(text: str, alias_map: dict[str, str], default: str) -> str:
    normalized = text.lower().strip()
    if normalized in alias_map:
        return alias_map[normalized]
    for alias, canonical in alias_map.items():
        if alias in normalized or normalized in alias:
            return canonical
    return default


def _context_component(text: str) -> str:
    for pattern, component in _COMPONENT_CONTEXT_RULES:
        if pattern.search(text):
            return component
    return "unknown"


def _context_service(text: str) -> str:
    lower = text.lower()
    tokens = re.findall(r"[a-z0-9-]+", lower)
    for token in tokens:
        for alias, canonical in SERVICE_ALIASES.items():
            if token == alias or token in alias:
                return canonical
    for pattern, service in _SERVICE_CONTEXT_RULES:
        if pattern.search(text):
            return service
    return "unknown"


def _regex_first_failure_type(text: str) -> tuple[str, str]:
    for rule_name, pattern, canonical, source in _REGEX_RULES:
        if rule_name == "failure_type" and pattern.search(text):
            return canonical, source
    return "", ""


def _regex_first_fix_type(text: str) -> tuple[str, str]:
    for rule_name, pattern, canonical, source in _REGEX_RULES:
        if rule_name == "fix_type" and pattern.search(text):
            return canonical, source
    return "", ""


def _regex_first_severity(text: str) -> tuple[str, str]:
    for rule_name, pattern, canonical, source in _REGEX_RULES:
        if rule_name == "severity" and pattern.search(text):
            return canonical, source
    return "", ""


def _alias_symptoms(text: str) -> list[str]:
    lower = text.lower()
    matched = []
    for alias, canonical in SYMPTOM_ALIASES.items():
        if alias in lower and canonical not in matched:
            matched.append(canonical)
    return matched[:3] if matched else []


def _alias_fix_type(text: str) -> str:
    return _alias_lookup(text, FIX_TYPE_ALIASES, "")


def _alias_severity(text: str) -> str:
    return _alias_lookup(text, SEVERITY_ALIASES, "")


def _alias_failure_type(text: str) -> str:
    return _alias_lookup(text, FAILURE_TYPE_ALIASES, "")


def normalize_deterministic(title: str, summary: str, incident_id: str = "") -> tuple[dict, NormalizationReport]:
    text = f"{title}\n{summary}"
    report = NormalizationReport()

    service = _context_service(text)
    component = _context_component(text)

    regex_failure, regex_src = _regex_first_failure_type(text)
    alias_failure = _alias_failure_type(text)
    failure_type = regex_failure or alias_failure
    if regex_failure:
        report.regex_matched.append(f"failure_type:{regex_src}")
    elif alias_failure:
        report.alias_matched.append("failure_type")

    regex_fix, regex_src = _regex_first_fix_type(text)
    alias_fix = _alias_fix_type(text)
    fix_type = regex_fix or alias_fix
    if regex_fix:
        report.regex_matched.append(f"fix_type:{regex_src}")
    elif alias_fix:
        report.alias_matched.append("fix_type")

    regex_severity, regex_src = _regex_first_severity(text)
    alias_severity = _alias_severity(text)
    severity = regex_severity or alias_severity
    if regex_severity:
        report.regex_matched.append(f"severity:{regex_src}")
    elif alias_severity:
        report.alias_matched.append("severity")

    symptom_matches = _alias_symptoms(text)
    if not symptom_matches:
        symptom_matches = _infer_symptoms_heuristic(text)

    if failure_type and failure_type not in FAILURE_TYPES:
        failure_type = _closest_from_list(failure_type, FAILURE_TYPES)
    if not failure_type:
        failure_type = "timeout"

    if fix_type and fix_type not in FIX_TYPES:
        fix_type = _closest_from_list(fix_type, FIX_TYPES)
    if not fix_type:
        fix_type = _infer_fix_from_context(component, failure_type)

    if severity and severity not in SEVERITY_LEVELS:
        severity = _closest_from_list(severity, SEVERITY_LEVELS)
    if not severity:
        severity = _infer_severity_heuristic(text)

    if not symptom_matches:
        symptom_matches = _infer_symptoms_heuristic(text)
    symptom_matches = [s for s in symptom_matches if s in SYMPTOM_TYPES][:3]
    if not symptom_matches:
        symptom_matches = ["high_latency"]

    environment = "production"

    root_cause = _build_root_cause(component, failure_type)
    fix = _build_fix_text(component, failure_type, fix_type)
    confidence = _compute_confidence(len(report.regex_matched), len(report.alias_matched), failure_type != "timeout", fix_type != "restart_service")

    result = {
        "incident_id": incident_id,
        "title": title,
        "summary": summary,
        "service": service,
        "component": component,
        "failure_type": failure_type,
        "fix_type": fix_type,
        "symptoms": symptom_matches,
        "severity": severity,
        "environment": environment,
        "root_cause": root_cause,
        "fix": fix,
        "confidence": confidence,
    }

    report.field_predicted = {
        "service": result["service"],
        "component": result["component"],
        "failure_type": result["failure_type"],
        "fix_type": result["fix_type"],
        "severity": result["severity"],
    }
    report.method = "regex-first" if report.regex_matched else ("alias-lookup" if report.alias_matched else "heuristic")

    return result, report


def _infer_symptoms_heuristic(text: str) -> list[str]:
    lower = text.lower()
    symptoms: list[str] = []
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
    if "retry" in lower and ("loop" in lower or "storm" in lower or "amplification" in lower):
        symptoms.append("retry_storm")
    if "disk" in lower and ("pressure" in lower or "full" in lower or "95%" in lower):
        symptoms.append("disk_pressure")
    if "certificate" in lower and ("error" in lower or "expired" in lower or "tls" in lower):
        symptoms.append("certificate_errors")
    deduped: list[str] = []
    for symptom in symptoms:
        if symptom in SYMPTOM_TYPES and symptom not in deduped:
            deduped.append(symptom)
    return deduped[:3] or ["high_latency"]


def _infer_severity_heuristic(text: str) -> str:
    lower = text.lower()
    if any(t in lower for t in ["critical", "sev1", "sev-1", "outage", "down"]):
        return "critical"
    if any(t in lower for t in ["504", "503", "timeout", "degraded", "high latency"]):
        return "high"
    return "medium"


def _infer_fix_from_context(component: str, failure_type: str) -> str:
    if component == "redis" and failure_type == "connection_pool_exhaustion":
        return "increase_pool_size"
    if component == "redis" and failure_type == "redis_failover_storm":
        return "add_exponential_backoff"
    if failure_type == "kafka_disk_pressure":
        return "reduce_log_retention"
    if failure_type == "certificate_expired":
        return "renew_certificate"
    if failure_type in ("infinite_loop", "cpu_saturation"):
        return "add_exponential_backoff"
    if failure_type == "query_overload":
        return "reduce_query_load"
    if failure_type == "oom_killed":
        return "increase_memory_limit"
    if failure_type == "timeout":
        return "add_exponential_backoff"
    return "restart_service"


def _build_root_cause(component: str, failure_type: str) -> str:
    readable = failure_type.replace("_", " ")
    if component != "unknown":
        return f"{component} experienced {readable}."
    return f"System experienced {readable}."


def _build_fix_text(component: str, failure_type: str, fix_type: str) -> str:
    if component == "redis" and failure_type == "connection_pool_exhaustion":
        return "Increase Redis connection pool size and recycle stuck connections."
    if failure_type == "redis_failover_storm":
        return "Add exponential backoff to Redis retry logic during failover."
    if failure_type == "kafka_disk_pressure":
        return "Reduce Kafka log retention period and free broker disk space."
    if failure_type == "certificate_expired":
        return "Renew the expired TLS certificate and verify rotation schedule."
    if failure_type in ("infinite_loop", "cpu_saturation") and fix_type == "add_exponential_backoff":
        return "Add exponential backoff to retry logic to prevent CPU saturation."
    if failure_type == "query_overload":
        return "Reduce query load and add or tune database indexes."
    if failure_type == "oom_killed":
        return "Increase memory limit and identify the memory growth path."
    if failure_type == "timeout":
        return "Add exponential backoff and verify dependency health."
    readable_fix = fix_type.replace("_", " ")
    return f"Apply {readable_fix} to resolve {failure_type.replace('_', ' ')}."


def _closest_from_list(value: str, valid: list[str]) -> str:
    v = (value or "").lower().replace(" ", "_")
    if not v:
        return valid[0] if valid else ""
    for c in valid:
        if v == c or v in c or c in v:
            return c
    words = v.split("_")
    for c in valid:
        if any(w and w in c for w in words):
            return c
    return valid[0] if valid else ""


def _compute_confidence(regex_hits: int, alias_hits: int, failure_specific: bool, fix_specific: bool) -> float:
    base = 0.55
    if regex_hits >= 2:
        base = 0.88
    elif regex_hits == 1:
        base = 0.80
    elif alias_hits >= 2:
        base = 0.72
    elif alias_hits == 1:
        base = 0.65
    if failure_specific and fix_specific:
        base = min(base + 0.08, 0.95)
    elif failure_specific:
        base = min(base + 0.04, 0.92)
    return round(base, 3)
