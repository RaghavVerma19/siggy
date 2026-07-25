"""SigNoz dashboard and view definitions for Siggy memory layer.

Uses direct SigNoz REST API (SIGNOZ-API-KEY header) instead of MCP,
because the MCP server in HTTP mode doesn't forward auth to SigNoz.

SigNoz v1 dashboard widget format (from Terraform provider + UI traffic):
- Dashboard create: POST /api/v1/dashboards {title, description}
- Dashboard update: PUT  /api/v1/dashboards/{id} {title, description, widgets, layout}
- View create:      POST /api/v1/explorer/views {name, sourcePage, compositeQuery, extraData}

Critical: each widget MUST include panelTypes ("graph", "list", "value", etc.)
to avoid SigNoz returning "unknown request type ''".
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


# ---------------------------------------------------------------------------
# Widget builders — complete SigNoz v1 dashboard widget payloads
# ---------------------------------------------------------------------------

def _base_widget(panel_id: str, title: str, description: str, panel_type: str = "graph") -> dict:
    """Return the base widget dict with all required SigNoz metadata fields."""
    return {
        "id": panel_id,
        "title": title,
        "description": description,
        "panelTypes": panel_type,
        "selectedLogFields": [],
        "selectedTracesFields": [],
        "thresholds": [],
        "columnUnits": {},
        "yAxisUnit": "none",
        "softMax": None,
        "softMin": None,
        "fillSpans": False,
        "isStacked": False,
        "stackedBarChart": False,
        "nullZeroValues": "zero",
        "opacity": "1",
        "bucketCount": 30,
        "bucketWidth": 0,
        "mergeAllActiveQueries": False,
    }


def _make_trace_query(
    query_name: str = "A",
    aggregate_operator: str = "count",
    aggregate_key: str = "operation.name",
    aggregate_data_type: str = "string",
    filters: list[dict] | None = None,
    group_by: list[dict] | None = None,
    order_by: list[dict] | None = None,
    limit: int = 100,
) -> dict:
    """Build a single queryData entry for traces."""
    q: dict = {
        "queryName": query_name,
        "dataSource": "traces",
        "aggregateOperator": aggregate_operator,
        "aggregateAttribute": {
            "key": aggregate_key,
            "dataType": aggregate_data_type,
        },
        "filters": {"items": filters or []},
        "groupBy": group_by or [],
        "limit": limit,
        "stepInterval": 60,
        "expression": query_name,
        "disabled": False,
    }
    if order_by:
        q["orderBy"] = order_by
    return q


def _make_log_query(
    query_name: str = "A",
    filters: list[dict] | None = None,
    group_by: list[dict] | None = None,
    order_by: list[dict] | None = None,
    limit: int = 50,
) -> dict:
    """Build a single queryData entry for logs."""
    q: dict = {
        "queryName": query_name,
        "dataSource": "logs",
        "aggregateOperator": "count",
        "aggregateAttribute": {
            "key": "ts",
            "dataType": "string",
        },
        "filters": {"items": filters or []},
        "groupBy": group_by or [],
        "limit": limit,
        "stepInterval": 60,
        "expression": query_name,
        "disabled": False,
    }
    if order_by:
        q["orderBy"] = order_by
    return q


def _build_graph_widget(
    panel_id: str,
    title: str,
    description: str,
    data_source: str = "traces",
    query_data: list[dict] | None = None,
    formulas: list[dict] | None = None,
    height: int = 4,
    width: int = 6,
    x: int = 0,
    y: int = 0,
) -> tuple[dict, dict]:
    """Build a complete graph widget + layout entry."""
    widget = _base_widget(panel_id, title, description, panel_type="graph")
    widget["query"] = {
        "queryType": "builder",
        "builder": {
            "queryData": query_data or [],
            "queryFormulas": formulas or [],
        },
        "promql": [],
        "clickhouse_sql": [],
    }
    widget["timePreferance"] = "GLOBAL_TIME"
    layout = {"h": height, "i": panel_id, "w": width, "x": x, "y": y}
    return widget, layout


def _build_list_widget(
    panel_id: str,
    title: str,
    description: str,
    data_source: str,
    query_data: list[dict],
    height: int = 4,
    width: int = 12,
    x: int = 0,
    y: int = 0,
) -> tuple[dict, dict]:
    """Build a complete list (raw rows) widget + layout entry."""
    widget = _base_widget(panel_id, title, description, panel_type="list")
    widget["query"] = {
        "queryType": "builder",
        "builder": {
            "queryData": query_data,
            "queryFormulas": [],
        },
        "promql": [],
        "clickhouse_sql": [],
    }
    widget["timePreferance"] = "GLOBAL_TIME"
    layout = {"h": height, "i": panel_id, "w": width, "x": x, "y": y}
    return widget, layout


# ---------------------------------------------------------------------------
# Dashboard panels + layout
# ---------------------------------------------------------------------------

def _build_all_widgets() -> tuple[list[dict], list[dict]]:
    """Build all dashboard widgets and their layout."""
    widgets: list[dict] = []
    layout: list[dict] = []
    row = 0

    # Row 1: Live service health (request rate + error rate)
    w, l = _build_graph_widget(
        "panel-request-rate",
        "Request Rate by Service",
        "Number of requests per service over time",
        data_source="traces",
        query_data=[
            _make_trace_query(
                aggregate_operator="count",
                aggregate_key="operation.name",
                aggregate_data_type="string",
                group_by=[{"key": "service.name", "dataType": "string"}],
                order_by=[{"key": "count()", "dataType": "number", "order": "DESC"}],
            )
        ],
        width=6, x=0, y=row,
    )
    widgets.append(w)
    layout.append(l)

    w, l = _build_graph_widget(
        "panel-error-rate",
        "Error Rate by Service",
        "Number of error spans per service over time",
        data_source="traces",
        query_data=[
            _make_trace_query(
                aggregate_operator="count",
                aggregate_key="operation.name",
                aggregate_data_type="string",
                filters=[
                    {"key": {"key": "status_code", "dataType": "string"}, "op": "=", "value": "STATUS_CODE_ERROR"},
                ],
                group_by=[{"key": "service.name", "dataType": "string"}],
                order_by=[{"key": "count()", "dataType": "number", "order": "DESC"}],
            )
        ],
        width=6, x=6, y=row,
    )
    widgets.append(w)
    layout.append(l)
    row += 4

    # Row 2: Latency + Top operations
    w, l = _build_graph_widget(
        "panel-p95-latency",
        "P95 Latency by Service",
        "95th percentile request duration per service",
        data_source="traces",
        query_data=[
            _make_trace_query(
                aggregate_operator="p95",
                aggregate_key="duration_nano",
                aggregate_data_type="float64",
                group_by=[{"key": "service.name", "dataType": "string"}],
                order_by=[{"key": "p95(duration_nano)", "dataType": "number", "order": "DESC"}],
            )
        ],
        width=6, x=0, y=row,
    )
    widgets.append(w)
    layout.append(l)

    w, l = _build_graph_widget(
        "panel-top-operations",
        "Top Operations",
        "Most frequently called operations",
        data_source="traces",
        query_data=[
            _make_trace_query(
                aggregate_operator="count",
                aggregate_key="operation.name",
                aggregate_data_type="string",
                group_by=[{"key": "operation.name", "dataType": "string"}],
                order_by=[{"key": "count()", "dataType": "number", "order": "DESC"}],
                limit=20,
            )
        ],
        width=6, x=6, y=row,
    )
    widgets.append(w)
    layout.append(l)
    row += 4

    # Row 3: Siggy recommendations (over time + by service)
    w, l = _build_graph_widget(
        "panel-recs-over-time",
        "Recommendations Over Time",
        "Memory-enriched recommendations generated by Siggy",
        data_source="traces",
        query_data=[
            _make_trace_query(
                aggregate_operator="count",
                aggregate_key="operation.name",
                aggregate_data_type="string",
                filters=[
                    {"key": {"key": "name", "dataType": "string"}, "op": "=", "value": "siggy.recommendation"},
                ],
                order_by=[],
            )
        ],
        width=6, x=0, y=row,
    )
    widgets.append(w)
    layout.append(l)

    w, l = _build_graph_widget(
        "panel-recs-by-service",
        "Recommendations by Service",
        "Which services have the most Siggy recommendations",
        data_source="traces",
        query_data=[
            _make_trace_query(
                aggregate_operator="count",
                aggregate_key="operation.name",
                aggregate_data_type="string",
                filters=[
                    {"key": {"key": "name", "dataType": "string"}, "op": "=", "value": "siggy.recommendation"},
                ],
                group_by=[{"key": "siggy.service", "dataType": "string"}],
                order_by=[{"key": "count()", "dataType": "number", "order": "DESC"}],
            )
        ],
        width=6, x=6, y=row,
    )
    widgets.append(w)
    layout.append(l)
    row += 4

    # Row 4: Failure types + confidence
    w, l = _build_graph_widget(
        "panel-failures",
        "Top Failure Types",
        "Most common failure types detected by Siggy",
        data_source="traces",
        query_data=[
            _make_trace_query(
                aggregate_operator="count",
                aggregate_key="operation.name",
                aggregate_data_type="string",
                filters=[
                    {"key": {"key": "name", "dataType": "string"}, "op": "=", "value": "siggy.recommendation"},
                ],
                group_by=[{"key": "siggy.failure_type", "dataType": "string"}],
                order_by=[{"key": "count()", "dataType": "number", "order": "DESC"}],
            )
        ],
        width=6, x=0, y=row,
    )
    widgets.append(w)
    layout.append(l)

    w, l = _build_graph_widget(
        "panel-confidence",
        "Confidence Distribution",
        "Distribution of Siggy recommendation confidence scores",
        data_source="traces",
        query_data=[
            _make_trace_query(
                aggregate_operator="count",
                aggregate_key="operation.name",
                aggregate_data_type="string",
                filters=[
                    {"key": {"key": "name", "dataType": "string"}, "op": "=", "value": "siggy.recommendation"},
                ],
                group_by=[{"key": "siggy.confidence", "dataType": "string"}],
                order_by=[{"key": "count()", "dataType": "number", "order": "DESC"}],
            )
        ],
        width=6, x=6, y=row,
    )
    widgets.append(w)
    layout.append(l)
    row += 4

    # Row 5: Raw data — error logs + recent siggy recommendations
    w, l = _build_list_widget(
        "panel-error-logs",
        "Recent Error Logs",
        "Latest error-level logs from all services",
        data_source="logs",
        query_data=[
            _make_log_query(
                filters=[
                    {"key": {"key": "severity_text", "dataType": "string"}, "op": "=", "value": "ERROR"},
                ],
                order_by=[{"key": "timestamp", "dataType": "string", "order": "DESC"}],
                limit=20,
            )
        ],
        height=6, width=6, x=0, y=row,
    )
    widgets.append(w)
    layout.append(l)

    w, l = _build_list_widget(
        "panel-recs-list",
        "Recent Siggy Recommendations",
        "Latest memory-enriched recommendation spans",
        data_source="traces",
        query_data=[
            _make_trace_query(
                aggregate_operator="count",
                aggregate_key="operation.name",
                aggregate_data_type="string",
                filters=[
                    {"key": {"key": "name", "dataType": "string"}, "op": "=", "value": "siggy.recommendation"},
                ],
                order_by=[{"key": "timestamp", "dataType": "string", "order": "DESC"}],
                limit=20,
            )
        ],
        height=6, width=6, x=6, y=row,
    )
    widgets.append(w)
    layout.append(l)

    return widgets, layout


DASHBOARD_WIDGETS, DASHBOARD_LAYOUT = _build_all_widgets()


# --- Saved view definitions (SigNoz v5 explorer view format) ---

def _make_view_query(
    name: str,
    signal: str = "traces",
    filter_expr: str = "",
) -> dict:
    """Build the compositeQuery for a saved explorer view."""
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
    """Add widgets and layout to an existing dashboard."""
    r = httpx.put(
        f"{signoz_url}/api/v1/dashboards/{dash_id}",
        headers=_headers(api_key),
        json={"title": title, "description": description, "widgets": widgets, "layout": layout},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _delete_dashboard(signoz_url: str, api_key: str, dash_id: str) -> bool:
    """Delete a dashboard by ID."""
    try:
        r = httpx.delete(
            f"{signoz_url}/api/v1/dashboards/{dash_id}",
            headers=_headers(api_key),
            timeout=10,
        )
        return r.status_code < 300
    except Exception as e:
        logger.debug("Failed to delete dashboard %s: %s", dash_id, e)
        return False


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

def setup_siggy_in_signoz(api_key: str = "", signoz_url: str = "", force: bool = False) -> dict:
    """Create the Siggy dashboard and saved views in SigNoz.

    Always updates the dashboard with fresh widget definitions on startup,
    even if it already exists. This ensures broken panels get fixed.

    Args:
        api_key: SigNoz API key. Falls back to SIGNOZ_API_KEY env var.
        signoz_url: SigNoz base URL. Falls back to SIGNOZ_URL env var.
        force: If True, delete existing dashboard and recreate from scratch.

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
            dash_id = siggy_dash.get("id", "")
            if not dash_id:
                dash_id = siggy_dash.get("data", {}).get("id", "")

            if force and dash_id:
                _delete_dashboard(signoz_url, api_key, dash_id)
                siggy_dash = None
                dash_id = None
                logger.info("Deleted existing Siggy dashboard for recreation")
            else:
                # Always update existing dashboard with fresh widgets
                _update_dashboard(
                    signoz_url,
                    api_key,
                    dash_id,
                    DASHBOARD_TITLE,
                    "Unified Siggy memory layer + live SigNoz observability.",
                    DASHBOARD_WIDGETS,
                    DASHBOARD_LAYOUT,
                )
                results["dashboard"] = {"id": dash_id, "status": "updated"}
                logger.info("Updated Siggy dashboard widgets (id=%s)", dash_id)

        if not siggy_dash or force:
            dash_id = _create_dashboard(
                signoz_url,
                api_key,
                DASHBOARD_TITLE,
                "Unified Siggy memory layer + live SigNoz observability.",
            )
            _update_dashboard(
                signoz_url,
                api_key,
                dash_id,
                DASHBOARD_TITLE,
                "Unified Siggy memory layer + live SigNoz observability.",
                DASHBOARD_WIDGETS,
                DASHBOARD_LAYOUT,
            )
            results["dashboard"] = {"id": dash_id, "status": "created"}
            logger.info("Created Siggy dashboard (id=%s)", dash_id)
    except Exception as e:
        results["errors"].append(f"dashboard: {e}")
        logger.warning("Failed to create/update Siggy dashboard: %s", e)

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
