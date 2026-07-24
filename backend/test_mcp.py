import asyncio
import json
from telemetry.mcp_http import MCPHttpClient


async def test():
    client = MCPHttpClient(
        mcp_url="http://localhost:8000/mcp",
        api_key="Y9Lw8Ib695bAnhns6lXorlkNSNjACBQOzMgxbQjcDBc=",
        client_name="test",
    )
    ok = await client.initialize()
    print(f"Init: {ok}")
    if ok:
        tools = await client.list_tools()
        tool_names = [t.get("name", "?") for t in tools]
        print(f"Tools ({len(tools)}): {tool_names}")

        for name in [
            "signoz_list_dashboards",
            "signoz_create_dashboard",
            "signoz_list_views",
            "signoz_create_view",
            "signoz_update_alert",
        ]:
            found = "YES" if name in tool_names else "NO"
            print(f"  {name}: {found}")

        # Try list dashboards
        if "signoz_list_dashboards" in tool_names:
            result = await client.call_tool("signoz_list_dashboards", {})
            print(f"\nDashboards: {json.dumps(result, indent=2)[:500]}")

        # Try list views
        if "signoz_list_views" in tool_names:
            result = await client.call_tool("signoz_list_views", {})
            print(f"\nViews: {json.dumps(result, indent=2)[:500]}")

        # Try list alert rules
        if "signoz_list_alert_rules" in tool_names:
            result = await client.call_tool("signoz_list_alert_rules", {})
            print(f"\nAlert rules: {json.dumps(result, indent=2)[:500]}")


asyncio.run(test())
