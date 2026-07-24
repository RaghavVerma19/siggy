from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

from telemetry.mcp_http import DEFAULT_MCP_URL, MCPHttpClient
from telemetry.provider import TelemetryProvider

load_dotenv()
logger = logging.getLogger(__name__)

SIGNOZ_MCP_URL = os.getenv("SIGNOZ_MCP_URL", DEFAULT_MCP_URL)
SIGNOZ_API_KEY = os.getenv("SIGNOZ_API_KEY", "")


class SigNozMCPProvider(TelemetryProvider):
    """SigNoz telemetry via MCP server using raw HTTP (no SDK)."""

    def __init__(self):
        self._client = MCPHttpClient(
            mcp_url=SIGNOZ_MCP_URL,
            api_key=SIGNOZ_API_KEY,
            client_name="siggy-telemetry",
        )

    async def connect(self):
        ok = await self._client.initialize()
        if ok:
            logger.info("Connected to SigNoz MCP at %s", SIGNOZ_MCP_URL)
        else:
            raise RuntimeError(f"Failed to connect to SigNoz MCP at {SIGNOZ_MCP_URL}")

    async def disconnect(self):
        self._client.reset()
        logger.info("Disconnected from SigNoz MCP")

    async def ensure_connected(self) -> bool:
        try:
            if not self._client._initialized:
                return await self._client.initialize()
            return await self.health_check()
        except Exception as e:
            logger.warning("MCP reconnect failed: %s", e)
            self._client.reset()
            return False

    async def _call_tool(self, tool_name: str, arguments: dict) -> dict:
        return await self._client.call_tool(tool_name, arguments)

    async def list_services(self, start_time: str, end_time: str) -> list[dict]:
        result = await self._call_tool("signoz_list_services", {
            "start_time": start_time,
            "end_time": end_time,
        })
        services = result.get("services", result.get("data", []))
        return services if isinstance(services, list) else []

    async def search_logs(
        self,
        service: str,
        query: str,
        limit: int = 50,
        start_time: str = "",
        end_time: str = "",
    ) -> list[dict]:
        args: dict = {"service": service, "query": query, "limit": limit}
        if start_time:
            args["start_time"] = start_time
        if end_time:
            args["end_time"] = end_time
        result = await self._call_tool("signoz_search_logs", args)
        return MCPHttpClient.extract_rows(result)

    async def search_traces(
        self,
        service: str,
        query: str = "",
        min_duration_ms: int = 0,
        limit: int = 20,
        start_time: str = "",
        end_time: str = "",
        error: bool = False,
        time_range: str = "",
    ) -> list[dict]:
        args: dict = {"service": service, "limit": limit}
        if query:
            args["query"] = query
        if min_duration_ms:
            args["min_duration_ms"] = min_duration_ms
        if start_time:
            args["start_time"] = start_time
        if end_time:
            args["end_time"] = end_time
        if error:
            args["error"] = True
        if time_range:
            args["timeRange"] = time_range
        result = await self._call_tool("signoz_search_traces", args)
        return MCPHttpClient.extract_rows(result)

    async def query_metrics(
        self,
        service: str,
        metric_name: str,
        aggregation: str = "avg",
        start_time: str = "",
        end_time: str = "",
    ) -> dict:
        args = {
            "service": service,
            "metric_name": metric_name,
            "aggregation": aggregation,
        }
        if start_time:
            args["start_time"] = start_time
        if end_time:
            args["end_time"] = end_time
        result = await self._call_tool("signoz_query_metrics", args)
        return result if isinstance(result, dict) else {}

    async def list_alerts(
        self, silenced: bool = False, inhibited: bool = False
    ) -> list[dict]:
        result = await self._call_tool("signoz_list_alerts", {
            "silenced": silenced,
            "inhibited": inhibited,
        })
        alerts = result.get("alerts", result.get("data", []))
        return alerts if isinstance(alerts, list) else []

    async def list_alert_rules(self) -> list[dict]:
        result = await self._call_tool("signoz_list_alert_rules", {})
        rules = result.get("rules", result.get("data", []))
        return rules if isinstance(rules, list) else []

    async def create_alert_rule(self, rule: dict) -> dict:
        return await self._call_tool("signoz_create_alert", rule)

    async def get_alert_history(self, alert_id: str) -> dict:
        return await self._call_tool("signoz_get_alert_history", {"id": alert_id})

    async def update_alert_rule(self, alert_id: str, rule: dict) -> dict:
        return await self._call_tool("signoz_update_alert", {"id": alert_id, **rule})

    async def list_dashboards(self) -> list[dict]:
        result = await self._call_tool("signoz_list_dashboards", {})
        dashboards = result.get("dashboards", result.get("data", []))
        return dashboards if isinstance(dashboards, list) else []

    async def get_dashboard(self, dashboard_id: str) -> dict:
        return await self._call_tool("signoz_get_dashboard", {"id": dashboard_id})

    async def create_dashboard(self, dashboard: dict) -> dict:
        return await self._call_tool("signoz_create_dashboard", dashboard)

    async def list_views(self) -> list[dict]:
        result = await self._call_tool("signoz_list_views", {})
        views = result.get("views", result.get("data", []))
        return views if isinstance(views, list) else []

    async def create_view(self, view: dict) -> dict:
        return await self._call_tool("signoz_create_view", view)

    async def health_check(self) -> bool:
        return await self._client.health_check()


_telemetry_provider = None


def get_telemetry_provider() -> SigNozMCPProvider:
    global _telemetry_provider
    if _telemetry_provider is None:
        _telemetry_provider = SigNozMCPProvider()
    return _telemetry_provider
