"""MCP tool registration for local setup and one configured plan."""

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from ynab_mcp.client import YnabClient
from ynab_mcp.config import Settings
from ynab_mcp.errors import YnabError
from ynab_mcp.tools.accounts import account_list
from ynab_mcp.tools.months import budget_summary, category_list


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
    else:

        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def list_accounts(include_closed: bool = False) -> dict[str, object]:
            """List signed account balances by scope; net totals are not spendable cash."""
            return await account_list(client, include_closed)

        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def get_budget_summary(month: str | None = None) -> dict[str, object]:
            """Summarize one month; category available excludes internal balances."""
            return await budget_summary(client, month)

        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def list_categories(
            month: str | None = None, include_hidden: bool = False
        ) -> dict[str, object]:
            """List month category IDs, groups, balances, and available goals."""
            return await category_list(client, month, include_hidden)

    return mcp
