from datetime import datetime

import pytest
from mcp.client import Client

from tests.fixtures import account_fixture_client, scoped_settings, setup_settings
from ynab_mcp.server import build_server
from ynab_mcp.tools.accounts import account_list


@pytest.mark.anyio
async def test_totals_are_signed_and_labeled() -> None:
    result = await account_list(account_fixture_client(), include_closed=False)

    assert result["currency"] == "USD"
    assert result["totals"] == {
        "on_budget": "850.00",
        "tracking": "200.00",
        "all_included": "1050.00",
    }
    assert result["totals_basis"] == "signed net account balances; not spendable cash"
    assert all(not account["closed"] for account in result["accounts"])
    assert result["complete"] is True
    as_of_utc = result["as_of_utc"]
    assert isinstance(as_of_utc, str)
    assert datetime.fromisoformat(as_of_utc).tzinfo is not None

    accounts = result["accounts"]
    assert isinstance(accounts, list)
    assert len(accounts) == 3
    checking, credit_card, tracking = accounts
    assert checking == {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "name": "Checking",
        "type": "checking",
        "on_budget": True,
        "closed": False,
        "cleared_balance": "900.00",
        "uncleared_balance": "100.00",
        "balance": "1000.00",
    }
    assert credit_card["on_budget"] is True
    assert credit_card["type"] == "creditCard"
    assert credit_card["cleared_balance"] == "-120.00"
    assert credit_card["uncleared_balance"] == "-30.00"
    assert credit_card["balance"] == "-150.00"
    assert tracking["on_budget"] is False
    assert tracking["type"] == "investmentAccount"
    assert tracking["cleared_balance"] == "150.00"
    assert tracking["uncleared_balance"] == "50.00"
    assert tracking["balance"] == "200.00"


@pytest.mark.anyio
async def test_include_closed_adds_closed_account_to_signed_totals() -> None:
    result = await account_list(account_fixture_client(), include_closed=True)

    assert result["totals"] == {
        "on_budget": "900.00",
        "tracking": "200.00",
        "all_included": "1100.00",
    }
    assert len(result["accounts"]) == 4
    assert result["accounts"][-1]["closed"] is True


@pytest.mark.anyio
async def test_list_accounts_is_scoped_and_read_only() -> None:
    server = build_server(scoped_settings(), account_fixture_client())

    async with Client(server) as mcp_client:
        tools = (await mcp_client.list_tools()).tools
        assert {tool.name for tool in tools} == {
            "list_accounts",
            "get_budget_summary",
            "list_categories",
            "list_transactions",
            "get_spending_summary",
            "get_uncategorized_transactions",
        }
        assert all(
            tool.annotations and tool.annotations.read_only_hint for tool in tools
        )

        result = await mcp_client.call_tool("list_accounts", {})
        assert not result.is_error
        assert result.structured_content is not None
        assert result.structured_content["totals"]["all_included"] == "1050.00"
        assert "private-metadata" not in repr(result)
        assert "private-account-note" not in repr(result)


@pytest.mark.anyio
async def test_setup_mode_does_not_register_list_accounts() -> None:
    server = build_server(setup_settings(), account_fixture_client())

    async with Client(server) as mcp_client:
        assert {tool.name for tool in (await mcp_client.list_tools()).tools} == {
            "list_plans"
        }
