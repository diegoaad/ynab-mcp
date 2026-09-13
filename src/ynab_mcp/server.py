"""MCP tool registration for local setup and one configured plan."""

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from ynab_mcp.client import YnabClient
from ynab_mcp.config import Settings
from ynab_mcp.errors import YnabError


def build_server(settings: Settings, client: YnabClient) -> MCPServer:
    mcp = MCPServer("YNAB personal plan", log_level="WARNING")

    if settings.plan_id is None:

        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def list_plans() -> dict[str, object]:
            """List plan IDs and names for local setup."""
            plans = await client.get_plans()
            if any(
                not isinstance(plan.get("id"), str)
                or not isinstance(plan.get("name"), str)
                for plan in plans
            ):
                raise YnabError("incomplete_data")
            return {
                "plans": [{"id": plan["id"], "name": plan["name"]} for plan in plans]
            }

    return mcp
