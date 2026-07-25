"""Auto-create default alert rules in SigNoz so the Siggy sidecar has data to enrich."""

from __future__ import annotations

import httpx

DEFAULT_RULES = [
    {
        "alert": "Siggy - High Error Rate",
        "alertType": "METRIC_BASED_ALERT",
        "ruleType": "promql_rule",
        "version": "v5",
        "schemaVersion": "v2alpha1",
        "severity": "critical",
        "disabled": False,
        "labels": {"severity": "critical", "managed_by": "siggy"},
        "annotations": {
            "summary": "High error rate on {{$labels.service_name}}",
            "description": "Error rate is {{$value}}% which exceeds the 5% threshold",
        },
        "condition": {
            "compositeQuery": {
                "queryType": "promql",
                "panelType": "graph",
                "queries": [
                    {
                        "type": "promql",
                        "spec": {
                            "name": "A",
                            "query": (
                                'sum(rate(signoz_calls_total{status_code="STATUS_CODE_ERROR"}[5m])) '
                                "/ sum(rate(signoz_calls_total[5m])) * 100"
                            ),
                            "legend": "error_rate",
                        },
                    }
                ],
                "unit": "percentunit",
            },
            "selectedQueryName": "A",
            "thresholds": {
                "kind": "basic",
                "spec": [
                    {
                        "name": "critical",
                        "target": 5,
                        "op": "above",
                        "matchType": "all_the_times",
                        "channels": ["siggy-webhook"],
                    }
                ],
            },
        },
        "evaluation": {"kind": "rolling", "spec": {"evalWindow": "5m", "frequency": "1m"}},
        "notificationSettings": {
            "groupBy": [],
            "renotify": {"enabled": False, "interval": "1h", "alertStates": ["firing"]},
        },
    },
    {
        "alert": "Siggy - High Latency",
        "alertType": "METRIC_BASED_ALERT",
        "ruleType": "promql_rule",
        "version": "v5",
        "schemaVersion": "v2alpha1",
        "severity": "warning",
        "disabled": False,
        "labels": {"severity": "warning", "managed_by": "siggy"},
        "annotations": {
            "summary": "High P95 latency on {{$labels.service_name}}",
            "description": "P95 latency is {{$value}}ms which exceeds the 2000ms threshold",
        },
        "condition": {
            "compositeQuery": {
                "queryType": "promql",
                "panelType": "graph",
                "queries": [
                    {
                        "type": "promql",
                        "spec": {
                            "name": "A",
                            "query": (
                                "histogram_quantile(0.95, "
                                'sum(rate(signoz_duration_milliseconds_bucket[5m])) by (le))'
                            ),
                            "legend": "p95_latency",
                        },
                    }
                ],
                "unit": "ms",
            },
            "selectedQueryName": "A",
            "thresholds": {
                "kind": "basic",
                "spec": [
                    {
                        "name": "warning",
                        "target": 2000,
                        "op": "above",
                        "matchType": "all_the_times",
                        "channels": ["siggy-webhook"],
                    }
                ],
            },
        },
        "evaluation": {"kind": "rolling", "spec": {"evalWindow": "5m", "frequency": "1m"}},
        "notificationSettings": {
            "groupBy": [],
            "renotify": {"enabled": False, "interval": "1h", "alertStates": ["firing"]},
        },
    },
    {
        "alert": "Siggy - High Failure Count",
        "alertType": "METRIC_BASED_ALERT",
        "ruleType": "promql_rule",
        "version": "v5",
        "schemaVersion": "v2alpha1",
        "severity": "critical",
        "disabled": False,
        "labels": {"severity": "critical", "managed_by": "siggy"},
        "annotations": {
            "summary": "High failure count on {{$labels.service_name}}",
            "description": "Failure rate is {{$value}} req/s which exceeds threshold",
        },
        "condition": {
            "compositeQuery": {
                "queryType": "promql",
                "panelType": "graph",
                "queries": [
                    {
                        "type": "promql",
                        "spec": {
                            "name": "A",
                            "query": (
                                'sum(rate(signoz_calls_total{status_code="STATUS_CODE_ERROR"}[5m]))'
                            ),
                            "legend": "failure_rate",
                        },
                    }
                ],
                "unit": "reqps",
            },
            "selectedQueryName": "A",
            "thresholds": {
                "kind": "basic",
                "spec": [
                    {
                        "name": "critical",
                        "target": 0.167,
                        "op": "above",
                        "matchType": "all_the_times",
                        "channels": ["siggy-webhook"],
                    }
                ],
            },
        },
        "evaluation": {"kind": "rolling", "spec": {"evalWindow": "5m", "frequency": "1m"}},
        "notificationSettings": {
            "groupBy": [],
            "renotify": {"enabled": False, "interval": "1h", "alertStates": ["firing"]},
        },
    },
]


def _ensure_webhook_channel(signoz_url: str, api_key: str) -> str | None:
    """Create a no-op webhook notification channel if none exists. Returns channel name."""
    headers = {"SIGNOZ-API-KEY": api_key, "Content-Type": "application/json"}

    try:
        r = httpx.get(f"{signoz_url}/api/v1/channels", headers=headers, timeout=10)
        channels = r.json().get("data", [])
    except Exception:
        return None

    for ch in channels:
        if ch.get("name") == "siggy-webhook":
            return "siggy-webhook"

    payload = {
        "type": "webhook",
        "name": "siggy-webhook",
        "onboarding_complete": True,
        "webhook_configs": [{"url": "http://localhost:9999/health"}],
    }

    try:
        r = httpx.post(f"{signoz_url}/api/v1/channels", headers=headers, json=payload, timeout=10)
        if r.status_code in (200, 201):
            return "siggy-webhook"
    except Exception:
        pass

    return None


def _get_existing_rule_names(signoz_url: str, api_key: str) -> set[str]:
    """Fetch existing alert rule names."""
    headers = {"SIGNOZ-API-KEY": api_key}
    try:
        r = httpx.get(f"{signoz_url}/api/v2/rules", headers=headers, timeout=10)
        resp = r.json()
        data = resp.get("data", resp)
        if isinstance(data, list):
            rules = data
        elif isinstance(data, dict):
            rules = data.get("rules", [])
        else:
            rules = []
        return {rule["alert"] for rule in rules}
    except Exception:
        return set()


def setup_default_alerts(signoz_url: str, api_key: str) -> dict:
    """Create default alert rules in SigNoz if they don't already exist.

    Returns summary dict with keys: rules_created, rules_skipped, channel_created.
    """
    result = {"rules_created": 0, "rules_skipped": 0, "channel_created": False}

    if not api_key:
        return result

    channel_name = _ensure_webhook_channel(signoz_url, api_key)
    result["channel_created"] = channel_name is not None

    existing = _get_existing_rule_names(signoz_url, api_key)
    headers = {"SIGNOZ-API-KEY": api_key, "Content-Type": "application/json"}

    for rule in DEFAULT_RULES:
        if rule["alert"] in existing:
            result["rules_skipped"] += 1
            continue

        try:
            r = httpx.post(f"{signoz_url}/api/v2/rules", headers=headers, json=rule, timeout=10)
            if r.status_code in (200, 201):
                result["rules_created"] += 1
            else:
                result["rules_skipped"] += 1
        except Exception:
            result["rules_skipped"] += 1

    return result
