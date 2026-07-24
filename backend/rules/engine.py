"""Rule Engine: pattern-match on telemetry summary for instant recommendations. No LLM needed."""

from typing import Optional


def _parse_percent(s: str) -> float:
    try:
        return float(s.strip().rstrip("%"))
    except (ValueError, AttributeError):
        return 0.0


def _parse_latency_ms(s: str) -> float:
    s = s.strip().lower()
    try:
        if s.endswith("ms"):
            return float(s[:-2])
        elif s.endswith("s"):
            return float(s[:-1]) * 1000
        else:
            return float(s)
    except (ValueError, AttributeError):
        return 0.0


def check_oom(summary: dict) -> Optional[dict]:
    top_errors = " ".join(summary.get("top_errors", [])).lower()
    if "oom" in top_errors or "out of memory" in top_errors or "killed" in top_errors:
        return {
            "rule": "oom_detected",
            "confidence": 0.95,
            "recommended_fix": (
                "Increase memory limits for affected pods. Check for memory leaks "
                "with heap dumps. Set resource requests and limits in Kubernetes."
            ),
            "investigation_steps": [
                "Check pod events: kubectl describe pod <pod>",
                "Take heap dump: kubectl exec <pod> -- jmap -dump:live,format=b,file=/tmp/heap.hprof <pid>",
                "Check memory usage trend in SigNoz metrics dashboard",
                "Review recent code changes for memory leaks",
            ],
        }
    return None


def check_connection_pool(summary: dict) -> Optional[dict]:
    top_errors = " ".join(summary.get("top_errors", [])).lower()
    deps = [d.lower() for d in summary.get("affected_dependencies", [])]

    pool_keywords = [
        "connection pool", "pool exhausted", "too many connections",
        "connection limit", "pool size", "max_connections",
    ]
    if any(kw in top_errors for kw in pool_keywords):
        component = "database"
        for dep in deps:
            if "redis" in dep:
                component = "Redis"
                break
            elif "postgres" in dep or "mysql" in dep or "database" in dep:
                component = "PostgreSQL"
                break
            elif "kafka" in dep:
                component = "Kafka"
                break

        return {
            "rule": "connection_pool_exhaustion",
            "confidence": 0.90,
            "recommended_fix": (
                f"Increase {component} connection pool size. Add connection pool monitoring. "
                "Implement connection timeout and retry with exponential backoff."
            ),
            "investigation_steps": [
                f"Check current {component} connection pool stats",
                "Review connection pool config (max connections, timeout)",
                "Check for connection leaks in application code",
                f"Monitor {component} active connections in SigNoz dashboard",
            ],
        }
    return None


def check_disk_space(summary: dict) -> Optional[dict]:
    top_errors = " ".join(summary.get("top_errors", [])).lower()
    if "disk" in top_errors or "no space" in top_errors or "storage" in top_errors:
        return {
            "rule": "disk_space_exhaustion",
            "confidence": 0.92,
            "recommended_fix": (
                "Free disk space immediately. Reduce log retention policy. "
                "Add disk usage alerts at 80% threshold. Consider tiered storage."
            ),
            "investigation_steps": [
                "Check disk usage: df -h on affected nodes",
                "Identify largest files: du -sh /* | sort -rh | head",
                "Check log retention settings",
                "Review recent data growth patterns",
            ],
        }
    return None


def check_high_latency(summary: dict) -> Optional[dict]:
    latency = summary.get("latency", "0")
    deps = summary.get("affected_dependencies", [])

    latency_ms = _parse_latency_ms(latency)
    if latency_ms > 5000 and deps:
        return {
            "rule": "high_latency_dependency",
            "confidence": 0.80,
            "recommended_fix": (
                f"Investigate {deps[0]} as the likely bottleneck. "
                f"Check connection pool, query performance, and network latency to {deps[0]}."
            ),
            "investigation_steps": [
                f"Check {deps[0]} connection latency and pool stats",
                "Review slow query logs if database-related",
                f"Check {deps[0]} resource usage (CPU, memory, network)",
                "Review recent deployment changes",
            ],
        }
    return None


RULES = [
    check_oom,
    check_connection_pool,
    check_disk_space,
    check_high_latency,
]


def evaluate_rules(summary: dict) -> Optional[dict]:
    """Try all rules. Returns first match or None (caller should fall back to LLM)."""
    for rule_fn in RULES:
        result = rule_fn(summary)
        if result is not None:
            return result
    return None
