"""SigNoz dashboard and view definitions for Siggy memory layer.

Uses direct SigNoz REST API (SIGNOZ-API-KEY header) instead of MCP,
because the MCP server in HTTP mode doesn't forward auth to SigNoz.

SigNoz v5 API format (captured from UI):
- Dashboard create: POST /api/v1/dashboards {title, description}
- Dashboard update: PUT  /api/v1/dashboards/{id} {widgets, layout}
- View create:      POST /api/v1/explorer/views {name, sourcePage, compositeQuery, extraData}
"""

from __future__ import annotations

import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

DASHBOARD_TITLE = "Siggy - Memory Layer"


def _headers(api_key: str) -> dict[str, str]:
    return {
        "SIGNOZ-API-KEY": api_key,
        "Content-Type": "application/json",
    }


# --- Widget query builders (SigNoz v5 dashboard widget format) ---

def _make_widget_query(group_by: str | None = None) -> dict:
    """Build a dashboard widget query filtering siggy.recommendation spans."""
    q: dict = {
        "queryType": "builder",
        "builder": {
            "queryData": [
                {
                    "dataSource": "traces",
                    "queryName": "A",
                    "aggregateOperator": "count",
                    "aggregateAttribute": {
                        "key": "operation.name",
                        "dataType": "string",
                    },
                    "filters": {
                        "items": [
                            {
                                "key": {"key": "name", "dataType": "string"},
                                "op": "=",
                                "value": "siggy.recommendation",
                            }
                        ]
                    },
                }
            ]
        },
    }
    if group_by:
        q["builder"]["queryData"][0]["groupBy"] = [
            {"key": group_by, "dataType": "string"}
        ]
    return q


# --- Dashboard widgets + layout ---

DASHBOARD_WIDGETS = [
    {
        "id": "panel-recent-recs",
        "title": "Recent Recommendations",
        "description": "Latest memory-enriched recommendations from Siggy",
        "query": _make_widget_query(),
        "timePreferency": "GLOBAL",
    },
    {
        "id": "panel-by-service",
        "title": "Recommendations by Service",
        "description": "How many recommendations per service",
        "query": _make_widget_query("siggy.service"),
        "timePreferency": "GLOBAL",
    },
    {
        "id": "panel-confidence",
        "title": "Confidence Distribution",
        "description": "Distribution of recommendation confidence scores",
        "query": _make_widget_query("siggy.confidence"),
        "timePreferency": "GLOBAL",
    },
    {
        "id": "panel-failures",
        "title": "Top Failure Types",
        "description": "Most common failure types detected by Siggy",
        "query": _make_widget_query("siggy.failure_type"),
        "timePreferency": "GLOBAL",
    },
]

DASHBOARD_LAYOUT = [
    {"h": 4, "i": "panel-recent-recs", "w": 12, "x": 0, "y": 0},
    {"h": 4, "i": "panel-by-service", "w": 6, "x": 0, "y": 4},
    {"h": 4, "i": "panel-confidence", "w": 6, "x": 6, "y": 4},
    {"h": 4, "i": "panel-failures", "w": 12, "x": 0, "y": 8},
]


# --- Saved view definitions (SigNoz v5 explorer view format) ---

def _make_view_query(
    name: str,
    signal: str = "traces",
    filter_expr: str = "",
) -> dict:
    """Build the compositeQuery for a saved explorer view.

    Uses expression-based filter (not items array) to match SigNoz v5 format.
    """
    spec: dict = {
        "name": name,
        "signal": signal,
        "stepInterval": None,
        "disabled": False,
        "filter": {"expression": filter_expr},
        "having": {"expression": ""},
    }

    return {
        "queryType": "builder",
        "panelType": "list",
        "queries": [
            {
                "type": "builder_query",
                "spec": spec,
            }
        ],
    }


def _make_view_extra_data(select_columns: list[dict] | None = None) -> str:
    """Build the extraData JSON string for a saved view."""
    if select_columns is None:
        select_columns = [
            {"name": "timestamp", "signal": "traces", "fieldContext": "span", "fieldDataType": "string"},
            {"name": "service.name", "signal": "traces", "fieldContext": "resource", "fieldDataType": "string"},
            {"name": "name", "signal": "traces", "fieldContext": "span", "fieldDataType": "string"},
            {"name": "duration_nano", "signal": "traces", "fieldContext": "span", "fieldDataType": ""},
            {"name": "http_method", "signal": "traces", "fieldContext": "span", "fieldDataType": ""},
            {"name": "response_status_code", "signal": "traces", "fieldContext": "span", "fieldDataType": ""},
        ]
    return json.dumps({
        "color": "#8444ff",
        "selectColumns": select_columns,
        "version": 1,
    })


SIGGY_VIEWS = [
    {
        "name": "Siggy Recommendations",
        "sourcePage": "traces",
        "compositeQuery": _make_view_query("A"),
        "extraData": _make_view_extra_data(),
    },
    {
        "name": "Siggy Low Confidence",
        "sourcePage": "traces",
        "compositeQuery": _make_view_query(
            "A",
            filter_expr="name = 'siggy.recommendation' AND siggy.confidence < 0.5",
        ),
        "extraData": _make_view_extra_data(),
    },
]


# --- REST API helpers ---

def _list_dashboards(signoz_url: str, api_key: str) -> list[dict]:
    try:
        r = httpx.get(
            f"{signoz_url}/api/v1/dashboards",
            headers=_headers(api_key),
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("data", [])
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.debug("Failed to list dashboards: %s", e)
    return []


def _create_dashboard(signoz_url: str, api_key: str, title: str, description: str) -> str:
    """Create a minimal dashboard, return its ID."""
    r = httpx.post(
        f"{signoz_url}/api/v1/dashboards",
        headers=_headers(api_key),
        json={"title": title, "description": description},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["data"]["id"]


def _update_dashboard(signoz_url: str, api_key: str, dash_id: str, title: str, description: str, widgets: list, layout: list) -> dict:
    """Add widgets and layout to an existing dashboard (preserving title)."""
    r = httpx.put(
        f"{signoz_url}/api/v1/dashboards/{dash_id}",
        headers=_headers(api_key),
        json={"title": title, "description": description, "widgets": widgets, "layout": layout},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _list_views(signoz_url: str, api_key: str, source_page: str = "traces") -> list[dict]:
    try:
        r = httpx.get(
            f"{signoz_url}/api/v1/explorer/views",
            headers=_headers(api_key),
            params={"sourcePage": source_page},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("data")
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.debug("Failed to list views: %s", e)
    return []


def _create_view(signoz_url: str, api_key: str, payload: dict) -> str:
    """Create a saved explorer view, return its ID."""
    r = httpx.post(
        f"{signoz_url}/api/v1/explorer/views",
        headers=_headers(api_key),
        json=payload,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["data"]


# --- Public setup function ---

def setup_siggy_in_signoz(api_key: str = "", signoz_url: str = "") -> dict:
    """Create the Siggy dashboard and saved views in SigNoz.

    Uses direct REST API with SIGNOZ-API-KEY auth (not MCP).

    Args:
        api_key: SigNoz API key. Falls back to SIGNOZ_API_KEY env var.
        signoz_url: SigNoz base URL. Falls back to SIGNOZ_URL env var.

    Flow:
        1. Check if dashboard exists -> create minimal -> PUT with widgets
        2. Check if views exist -> create each with correct v5 payload

    Returns:
        dict with status of each operation
    """
    results: dict = {"dashboard": None, "views": [], "errors": []}

    api_key = api_key or os.getenv("SIGNOZ_API_KEY", "")
    signoz_url = signoz_url or os.getenv("SIGNOZ_URL", "http://localhost:8080")

    if not api_key:
        results["errors"].append("SIGNOZ_API_KEY not set — dashboard integration skipped")
        return results

    # --- Create/update dashboard ---
    try:
        existing = _list_dashboards(signoz_url, api_key)
        siggy_dash = None
        for d in existing:
            if isinstance(d, dict):
                dd = d.get("data", {})
                if isinstance(dd, dict) and DASHBOARD_TITLE in dd.get("title", ""):
                    siggy_dash = d
                    break

        if siggy_dash:
            dash_id = siggy_dash["id"]
            results["dashboard"] = "already_exists"
            logger.info("Siggy dashboard already exists (id=%s)", dash_id)
        else:
            dash_id = _create_dashboard(
                signoz_url,
                api_key,
                DASHBOARD_TITLE,
                "AI-powered recommendations from Siggy's operational memory.",
            )
            _update_dashboard(
                signoz_url,
                api_key,
                dash_id,
                DASHBOARD_TITLE,
                "AI-powered recommendations from Siggy's operational memory.",
                DASHBOARD_WIDGETS,
                DASHBOARD_LAYOUT,
            )
            results["dashboard"] = {"id": dash_id, "status": "created"}
            logger.info("Created Siggy dashboard (id=%s)", dash_id)
    except Exception as e:
        results["errors"].append(f"dashboard: {e}")
        logger.warning("Failed to create Siggy dashboard: %s", e)

    # --- Create saved views ---
    try:
        existing_views = _list_views(signoz_url, api_key, "traces")
        existing_view_names = [
            v.get("name", "") for v in existing_views if isinstance(v, dict)
        ]
    except Exception:
        existing_view_names = []

    for view_def in SIGGY_VIEWS:
        view_name = view_def["name"]
        if view_name in existing_view_names:
            results["views"].append({"name": view_name, "status": "already_exists"})
            continue
        try:
            _create_view(signoz_url, api_key, view_def)
            results["views"].append({"name": view_name, "status": "created"})
            logger.info("Created saved view: %s", view_name)
        except Exception as e:
            results["views"].append({"name": view_name, "status": "error", "error": str(e)})
            results["errors"].append(f"view '{view_name}': {e}")
            logger.warning("Failed to create view '%s': %s", view_name, e)

    return results


def validate_api_key(api_key: str, signoz_url: str = "") -> tuple[bool, str]:
    """Test a SigNoz API key against the API.

    Returns (valid, message) where message explains the result.
    """
    signoz_url = signoz_url or os.getenv("SIGNOZ_URL", "http://localhost:8080")

    if not api_key:
        return False, "No API key provided"

    try:
        r = httpx.get(
            f"{signoz_url}/api/v2/rules",
            headers={"SIGNOZ-API-KEY": api_key},
            timeout=5,
        )
        if r.status_code < 400:
            return True, "API key valid"
        elif r.status_code in (401, 403):
            return False, f"Invalid key (SigNoz returned {r.status_code})"
        else:
            return False, f"Unexpected response from SigNoz ({r.status_code})"
    except Exception as e:
        return False, f"Could not reach SigNoz: {e}"
