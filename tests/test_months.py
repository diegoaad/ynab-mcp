"""Month projections from synthetic, historical YNAB responses."""

from datetime import datetime
from typing import Any, cast

import httpx
import pytest
from mcp.client import Client

from tests.fixtures import PLAN_ID, scoped_settings, ynab_response
from ynab_mcp.client import YnabClient
from ynab_mcp.errors import YnabError
from ynab_mcp.server import build_server
from ynab_mcp.tools.months import budget_summary, category_list


def month_fixture_client(*, malformed: bool = False) -> YnabClient:
    plans = [
        {
            "id": str(PLAN_ID),
            "name": "Fixture Plan",
            "currency_format": {"iso_code": "USD", "decimal_digits": 2},
            "last_modified_on": "private-metadata",
        }
    ]
    categories = [
        {
            "id": "ordinary",
            "category_group_id": "living",
            "category_group_name": "Living",
            "name": "Groceries",
            "hidden": False,
            "internal": False,
            "deleted": False,
            "budgeted": 225000,
            "activity": -25000,
            "balance": 200000,
            "goal_type": "NEED",
            "goal_target": 300000,
            "goal_target_date": "2026-08-31",
            "goal_under_funded": 75000,
            "note": "private-category-note",
        },
        {
            "id": "hidden",
            "category_group_id": "living",
            "category_group_name": "Living",
            "name": "Rainy Day",
            "hidden": True,
            "internal": False,
            "deleted": False,
            "budgeted": 40000,
            "activity": 0,
            "balance": 40000,
        },
        {
            "id": "deleted",
            "category_group_id": "living",
            "category_group_name": "Living",
            "name": "Old",
            "hidden": False,
            "internal": False,
            "deleted": True,
            "budgeted": 90000,
            "activity": 0,
            "balance": 90000,
        },
        {
            "id": "internal",
            "category_group_id": "system",
            "category_group_name": "System",
            "name": "Special allocation",
            "hidden": False,
            "internal": True,
            "deleted": False,
            "budgeted": 30000,
            "activity": 0,
            "balance": 30000,
        },
    ]
    if malformed:
        categories[0]["balance"] = "200000"
    month = {
        "month": "2026-08-01",
        "income": 500000,
        "budgeted": 295000,
        "activity": -25000,
        "to_be_budgeted": 50000,
        "age_of_money": None,
        "deleted": False,
        "categories": categories,
        "note": "private-month-note",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/plans":
            return ynab_response(plans=plans)
        if request.url.path == f"/v1/plans/{PLAN_ID}/months/2026-08-01":
            return ynab_response(month=month)
        return httpx.Response(404, json={"error": "unexpected fixture route"})

    return YnabClient(scoped_settings(), httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_month_summary_keeps_ready_to_assign_separate() -> None:
    result = await budget_summary(month_fixture_client(), "2026-08-01")

    assert result["month"] == "2026-08-01"
    assert result["plan_name"] == "Fixture Plan"
    assert result["currency"] == "USD"
    assert result["assigned"] == "295.00"
    assert result["activity"] == "-25.00"
    assert result["ready_to_assign"] == "50.00"
    assert result["available_in_categories"] == "240.00"
    assert "non-deleted, non-internal" in cast(
        str, result["available_in_categories_scope"]
    )
    assert "credit-card-payment" in cast(str, result["available_in_categories_scope"])
    assert result["age_of_money"] is None
    assert result["complete"] is True
    assert isinstance(result["as_of_utc"], str)
    assert datetime.fromisoformat(result["as_of_utc"]).tzinfo is not None
    assert "private-" not in repr(result)


@pytest.mark.anyio
async def test_hidden_category_is_filtered_only_from_listing() -> None:
    result = await category_list(month_fixture_client(), "2026-08-01")

    assert result["month"] == "2026-08-01"
    assert result["currency"] == "USD"
    assert result["groups"] == [
        {"id": "living", "name": "Living"},
        {"id": "system", "name": "System"},
    ]
    rows = cast(list[dict[str, Any]], result["categories"])
    assert [row["id"] for row in rows] == ["ordinary", "internal"]
    assert rows[0] == {
        "id": "ordinary",
        "group_id": "living",
        "group_name": "Living",
        "name": "Groceries",
        "hidden": False,
        "internal": False,
        "assigned": "225.00",
        "activity": "-25.00",
        "available": "200.00",
        "goal_type": "NEED",
        "goal_target": "300.00",
        "goal_target_date": "2026-08-31",
        "goal_under_funded": "75.00",
    }
    assert result["complete"] is True
    assert "private-" not in repr(result)


@pytest.mark.anyio
async def test_include_hidden_adds_hidden_category() -> None:
    result = await category_list(
        month_fixture_client(), "2026-08-01", include_hidden=True
    )
    rows = cast(list[dict[str, Any]], result["categories"])
    assert [row["id"] for row in rows] == ["ordinary", "hidden", "internal"]


@pytest.mark.anyio
async def test_malformed_category_balance_rejects_incomplete_summary() -> None:
    with pytest.raises(YnabError) as caught:
        await budget_summary(month_fixture_client(malformed=True), "2026-08-01")
    assert caught.value.code == "incomplete_data"


@pytest.mark.anyio
async def test_scoped_month_tools_are_read_only() -> None:
    server = build_server(scoped_settings(), month_fixture_client())
    async with Client(server) as mcp_client:
        tools = (await mcp_client.list_tools()).tools
        assert {tool.name for tool in tools} == {
            "list_accounts",
            "get_budget_summary",
            "list_categories",
        }
        assert all(
            tool.annotations and tool.annotations.read_only_hint for tool in tools
        )
        summary = await mcp_client.call_tool(
            "get_budget_summary", {"month": "2026-08-01"}
        )
        assert not summary.is_error
        assert summary.structured_content["available_in_categories"] == "240.00"
