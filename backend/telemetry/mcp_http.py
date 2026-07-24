"""Raw HTTP JSON-RPC client for SigNoz MCP.

Avoids the MCP Python SDK cancel-scope bug when used inside FastAPI's asyncio loop.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MCP_URL = "http://localhost:8000/mcp"


class MCPHttpClient:
    """Stateless-friendly MCP client using JSON-RPC over HTTP POST."""

    def __init__(
        self,
        mcp_url: str | None = None,
        api_key: str | None = None,
        client_name: str = "siggy",
    ):
        self.mcp_url = mcp_url or os.getenv("SIGNOZ_MCP_URL", DEFAULT_MCP_URL)
        self.api_key = api_key if api_key is not None else os.getenv("SIGNOZ_API_KEY", "")
        self.client_name = client_name
        self._session_id = ""
        self._request_id = 0
        self._initialized = False

    def _base_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["SIGNOZ-API-KEY"] = self.api_key
        return headers

    def _session_headers(self) -> dict[str, str]:
        headers = self._base_headers()
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def initialize(self) -> bool:
        """Run MCP handshake: initialize → notifications/initialized."""
        init_payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": self.client_name, "version": "1.0"},
            },
        }

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                self.mcp_url, headers=self._base_headers(), json=init_payload
            )
            if r.status_code != 200:
                logger.debug("MCP init returned %s", r.status_code)
                return False

            self._session_id = r.headers.get("mcp-session-id", "")

            await client.post(
                self.mcp_url,
                headers=self._session_headers(),
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

        self._initialized = True
        return True

    async def _post(self, payload: dict) -> dict:
        if not self._initialized:
            ok = await self.initialize()
            if not ok:
                raise RuntimeError(f"MCP initialize failed for {self.mcp_url}")

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                self.mcp_url, headers=self._session_headers(), json=payload
            )
            if r.status_code != 200:
                raise RuntimeError(f"MCP request failed with status {r.status_code}")
            return r.json()

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Call an MCP tool and return parsed JSON from the response."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        resp = await self._post(payload)

        if "error" in resp:
            err = resp["error"]
            raise RuntimeError(f"MCP tool '{name}' failed: {err.get('message', err)}")

        parsed = self.parse_tool_result(resp)
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}

    async def list_tools(self) -> list[dict]:
        """List available MCP tools."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        }
        resp = await self._post(payload)
        result = resp.get("result", {})
        return result.get("tools", [])

    async def health_check(self) -> bool:
        try:
            if not self._initialized:
                if not await self.initialize():
                    return False
            tools = await self.list_tools()
            return len(tools) > 0
        except Exception as e:
            logger.debug("MCP health check failed: %s", e)
            return False

    def reset(self) -> None:
        """Clear session state (e.g. on disconnect)."""
        self._session_id = ""
        self._request_id = 0
        self._initialized = False

    @staticmethod
    def parse_tool_result(resp: dict) -> dict | list | str:
        """Parse JSON-RPC tools/call response content into Python data."""
        result = resp.get("result")
        if not isinstance(result, dict):
            return {}

        content = result.get("content")
        if not isinstance(content, list):
            return result

        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text", "")
            if not text or not isinstance(text, str):
                continue
            if not text.startswith(("{", "[")):
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue

        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                return {"raw": item.get("text", "")}
        return {}

    @staticmethod
    def extract_rows(data: dict | list) -> list[dict]:
        """Extract row dicts from nested SigNoz MCP result structures."""
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]

        if not isinstance(data, dict):
            return []

        # Direct rows
        rows = data.get("rows")
        if isinstance(rows, list):
            return [r.get("data", r) for r in rows if isinstance(r, dict)]

        # data.results[].rows
        inner = data.get("data", data)
        if isinstance(inner, dict):
            results = inner.get("results", [])
            if isinstance(results, list):
                extracted: list[dict] = []
                for group in results:
                    if not isinstance(group, dict):
                        continue
                    group_rows = group.get("rows") or []
                    if isinstance(group_rows, list):
                        for row in group_rows:
                            if isinstance(row, dict):
                                extracted.append(row.get("data", row))
                if extracted:
                    return extracted

            # Double-nested: data.data.results (trace search format)
            nested = inner.get("data")
            if isinstance(nested, dict):
                return MCPHttpClient.extract_rows(nested)

        results = data.get("results", [])
        if isinstance(results, list):
            extracted = []
            for group in results:
                if isinstance(group, dict):
                    group_rows = group.get("rows") or []
                    if isinstance(group_rows, list):
                        for row in group_rows:
                            if isinstance(row, dict):
                                extracted.append(row.get("data", row))
            return extracted

        return []

    @staticmethod
    def extract_traces_from_response(resp: dict) -> list[dict]:
        """Extract trace dicts from a raw signoz_search_traces JSON-RPC response."""
        traces: list[dict] = []
        result = resp.get("result")
        if not isinstance(result, dict):
            return traces

        content = result.get("content")
        if not isinstance(content, list):
            return traces

        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text", "")
            if not text or not isinstance(text, str) or not text.startswith(("{", "[")):
                continue
            try:
                inner = json.loads(text)
            except json.JSONDecodeError:
                continue

            data_outer = inner.get("data")
            if isinstance(data_outer, dict):
                data_inner = data_outer.get("data", data_outer)
                rows = MCPHttpClient.extract_rows(data_inner)
                traces.extend(r for r in rows if isinstance(r, dict))

        return traces
