"""MCP tool registration for local setup and one configured plan."""

from collections.abc import Awaitable
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from ynab_mcp.client import YnabClient
from ynab_mcp.config import Settings
from ynab_mcp.errors import YnabError
from ynab_mcp.tools.accounts import account_list
from ynab_mcp.tools.months import budget_summary, category_list
from ynab_mcp.tools.spending import spending_summary
from ynab_mcp.tools.transactions import transaction_list, uncategorized_transactions


async def _safe_result[T](result: Awaitable[T]) -> T:
    """Expose only the sanitized classification of an expected YNAB failure."""
    try:
        return await result
    except YnabError as error:
        raise ToolError(error.code) from None
    except ValueError:
        raise ToolError("bad_request") from None


def build_server(settings: Settings, client: YnabClient) -> MCPServer:
    mcp = MCPServer("YNAB personal plan", log_level="WARNING")

    if settings.plan_id is None:

        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def list_plans() -> dict[str, object]:
            """List plan IDs and names for local setup."""
            plans = await _safe_result(client.get_plans())
            if any(
                not isinstance(plan.get("id"), str)
                or not isinstance(plan.get("name"), str)
                for plan in plans
            ):
                raise ToolError("incomplete_data")
            return {
                "plans": [{"id": plan["id"], "name": plan["name"]} for plan in plans]
            }
    else:

        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def list_accounts(include_closed: bool = False) -> dict[str, object]:
            """List signed account balances by scope; net totals are not spendable cash."""
            return await _safe_result(account_list(client, include_closed))

        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def list_transactions(
            since_date: str,
            until_date: str,
            account_id: str | None = None,
            category_id: str | None = None,
            payee_id: str | None = None,
            limit: Annotated[int, Field(ge=1, le=500)] = 100,
            include_memo: bool = False,
        ) -> dict[str, object]:
            """List bounded transaction details for inclusive dates; memos are opt-in."""
            return await _safe_result(
                transaction_list(
                    client,
                    since_date,
                    until_date,
                    account_id=account_id,
                    category_id=category_id,
                    payee_id=payee_id,
                    limit=limit,
                    include_memo=include_memo,
                )
            )

        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def get_uncategorized_transactions(
            since_date: str,
            until_date: str,
            limit: Annotated[int, Field(ge=1, le=500)] = 100,
        ) -> dict[str, object]:
            """List actionable uncategorized outflows for inclusive dates."""
            return await _safe_result(
                uncategorized_transactions(client, since_date, until_date, limit=limit)
            )

        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def get_budget_summary(month: str | None = None) -> dict[str, object]:
            """Summarize one month; category available excludes internal balances."""
            return await _safe_result(budget_summary(client, month))

        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def list_categories(
            month: str | None = None, include_hidden: bool = False
        ) -> dict[str, object]:
            """List month category IDs, groups, balances, and available goals."""
            return await _safe_result(category_list(client, month, include_hidden))

        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def get_spending_summary(
            start_date: str,
            end_date: str,
            group_by: Literal["category", "payee", "account", "month"],
        ) -> dict[str, object]:
            """Summarize complete net spending for inclusive dates by category, payee, account, or month."""
            return await _safe_result(
                spending_summary(client, start_date, end_date, group_by)
            )

    return mcp
