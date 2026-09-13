"""The scoped MCP surface is exactly the six approved read-only tools."""

import pytest
from mcp.client import Client

from tests.fixtures import account_fixture_client, scoped_settings
from ynab_mcp.server import build_server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_scoped_mcp_tool_names_and_annotations() -> None:
    async with Client(
        build_server(scoped_settings(), account_fixture_client())
    ) as mcp_client:
        tools = (await mcp_client.list_tools()).tools
        assert {tool.name for tool in tools} == {
            "get_budget_summary",
            "list_accounts",
            "list_categories",
            "list_transactions",
            "get_spending_summary",
            "get_uncategorized_transactions",
        }
        assert all(
            tool.annotations and tool.annotations.read_only_hint for tool in tools
        )
        properties = next(
            tool for tool in tools if tool.name == "get_uncategorized_transactions"
        ).input_schema["properties"]
        assert properties["limit"]["default"] == 100
        assert properties["limit"]["minimum"] == 1
        assert properties["limit"]["maximum"] == 500
