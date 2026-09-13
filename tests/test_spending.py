"""Complete, inclusive spending summaries across YNAB months."""

from dataclasses import replace
from datetime import date

import httpx
import pytest
from mcp.client import Client

from tests.fixtures import (
    PLAN_ID,
    scoped_settings,
    spending_fixture_accounts,
    spending_fixture_categories,
    spending_fixture_transactions,
    ynab_response,
)
from ynab_mcp.analysis import extract_postings
from ynab_mcp.client import MAX_BODY_BYTES, YnabClient
from ynab_mcp.errors import YnabError
from ynab_mcp.server import build_server
from ynab_mcp.tools.spending import aggregate_postings, months_between, spending_summary


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def spending_client(
    *,
    transactions: list[dict[str, object]] | None = None,
    conflicting_internal: bool = False,
    oversized: bool = False,
) -> YnabClient:
    rows = transactions if transactions is not None else spending_fixture_transactions()

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/v1/plans/{PLAN_ID}/transactions":
            if oversized:
                return httpx.Response(200, content=b"x" * (MAX_BODY_BYTES + 1))
            return ynab_response(transactions=rows)
        if path == f"/v1/plans/{PLAN_ID}/accounts":
            return ynab_response(accounts=spending_fixture_accounts())
        if path == "/v1/plans":
            return ynab_response(
                plans=[
                    {
                        "id": str(PLAN_ID),
                        "name": "Fixture Plan",
                        "currency_format": {"iso_code": "USD", "decimal_digits": 2},
                    }
                ]
            )
        if f"/v1/plans/{PLAN_ID}/months/" in path:
            month = path.rsplit("/", 1)[-1]
            categories = spending_fixture_categories()
            if conflicting_internal and month == "2026-09-01":
                categories[0]["internal"] = True
            return ynab_response(
                month={"month": month, "deleted": False, "categories": categories}
            )
        return httpx.Response(404, json={"error": "unexpected route"})

    return YnabClient(scoped_settings(), httpx.MockTransport(respond))


def test_months_between_includes_each_intersecting_month() -> None:
    assert months_between(date(2026, 7, 31), date(2026, 9, 1)) == [
        date(2026, 7, 1),
        date(2026, 8, 1),
        date(2026, 9, 1),
    ]


@pytest.mark.anyio
async def test_category_summary_uses_all_rows_before_projection() -> None:
    result = await spending_summary(
        spending_client(), "2026-07-01", "2026-09-13", "category"
    )
    assert result["complete"] is True
    assert result["groups"]["Restaurants"] == "65.00"
    assert result["groups"]["Groceries"] == "20.00"
    assert result["groups"]["Uncategorized"] == "10.00"
    assert result["since_date"] == "2026-07-01"
    assert result["until_date"] == "2026-09-13"
    assert result["currency"] == "USD"


@pytest.mark.anyio
async def test_more_than_detail_cap_rows_are_all_summed() -> None:
    rows = [
        {**spending_fixture_transactions()[1], "id": f"refund-{index}", "amount": -1000}
        for index in range(501)
    ]
    result = await spending_summary(
        spending_client(transactions=rows), "2026-09-01", "2026-09-13", "category"
    )
    assert result["groups"]["Restaurants"] == "501.00"


def test_group_by_payee_account_and_month() -> None:
    postings = extract_postings(
        spending_fixture_transactions(),
        spending_fixture_accounts(),
        spending_fixture_categories(),
    )
    named = [
        replace(posting, payee_id="payee-1", payee_name="Cafe") for posting in postings
    ]
    for grouping, key in (
        ("payee", "Cafe"),
        ("account", "Checking"),
        ("month", "2026-09"),
    ):
        totals = aggregate_postings(
            named,
            grouping,
            date(2026, 9, 1),
            date(2026, 9, 13),
            today=date(2026, 9, 13),
        )
        assert totals[key]["milliunits"] == 95000
    assert totals["2026-09"]["coverage"] == "month_to_date"


def test_same_payee_id_with_renamed_display_name_has_one_total() -> None:
    postings = extract_postings(
        spending_fixture_transactions(),
        spending_fixture_accounts(),
        spending_fixture_categories(),
    )
    renamed = [
        replace(postings[0], payee_id="payee-1", payee_name="Cafe"),
        replace(postings[1], payee_id="payee-1", payee_name="Cafe Renamed"),
    ]
    for ordering in (renamed, list(reversed(renamed))):
        totals = aggregate_postings(
            ordering,
            "payee",
            date(2026, 9, 1),
            date(2026, 9, 13),
            today=date(2026, 9, 13),
        )
        assert totals == {"Cafe": {"milliunits": 90000, "coverage": "selected_range"}}


def test_idless_named_payees_remain_separate_from_each_other_and_unknown() -> None:
    postings = extract_postings(
        spending_fixture_transactions(),
        spending_fixture_accounts(),
        spending_fixture_categories(),
    )
    idless = [
        replace(postings[0], payee_id=None, payee_name="Cafe"),
        replace(postings[1], payee_id=None, payee_name="Market"),
        replace(postings[0], payee_id=None, payee_name=None, milliunits=-3000),
    ]
    totals = aggregate_postings(
        idless,
        "payee",
        date(2026, 9, 1),
        date(2026, 9, 13),
        today=date(2026, 9, 13),
    )
    assert totals == {
        "Cafe": {"milliunits": 70000, "coverage": "selected_range"},
        "Market": {"milliunits": 20000, "coverage": "selected_range"},
        "Unknown payee": {"milliunits": 3000, "coverage": "selected_range"},
    }


@pytest.mark.parametrize("blank_name", ["", "   "])
def test_blank_idless_payee_does_not_merge_with_literal_unknown_name(
    blank_name: str,
) -> None:
    postings = extract_postings(
        spending_fixture_transactions(),
        spending_fixture_accounts(),
        spending_fixture_categories(),
    )
    idless = [
        replace(postings[0], payee_id=None, payee_name=blank_name),
        replace(
            postings[1], payee_id=None, payee_name="Unknown payee", milliunits=-2000
        ),
    ]
    totals = aggregate_postings(
        idless,
        "payee",
        date(2026, 9, 1),
        date(2026, 9, 13),
        today=date(2026, 9, 13),
    )
    assert totals == {
        "Unknown payee [unnamed]": {"milliunits": 70000, "coverage": "selected_range"},
        "Unknown payee [name-only]": {"milliunits": 2000, "coverage": "selected_range"},
    }


def test_month_coverage_handles_28_30_and_current_month() -> None:
    buckets = aggregate_postings(
        [], "month", date(2026, 2, 1), date(2026, 9, 13), today=date(2026, 9, 13)
    )
    assert buckets["2026-02"]["coverage"] == "full_month"
    assert buckets["2026-04"]["coverage"] == "full_month"
    assert buckets["2026-09"]["coverage"] == "month_to_date"
    prior = aggregate_postings(
        [], "month", date(2026, 8, 1), date(2026, 8, 13), today=date(2026, 9, 13)
    )
    assert prior["2026-08"]["coverage"] == "partial_month"
    partial_start = aggregate_postings(
        [], "month", date(2026, 2, 2), date(2026, 2, 28), today=date(2026, 9, 13)
    )
    assert partial_start["2026-02"]["coverage"] == "partial_month"


def test_colliding_category_names_keep_stable_ids() -> None:
    postings = extract_postings(
        spending_fixture_transactions(),
        spending_fixture_accounts(),
        spending_fixture_categories(),
    )
    duplicate = replace(postings[0], category_id="other-restaurants", milliunits=-2000)
    totals = aggregate_postings(
        [postings[0], duplicate],
        "category",
        date(2026, 9, 1),
        date(2026, 9, 13),
        today=date(2026, 9, 13),
    )
    assert totals["Restaurants [restaurants]"]["milliunits"] == 70000
    assert totals["Restaurants [other-restaurants]"]["milliunits"] == 2000


@pytest.mark.anyio
async def test_conflicting_internal_classification_fails_closed() -> None:
    with pytest.raises(YnabError, match="incomplete_data"):
        await spending_summary(
            spending_client(conflicting_internal=True),
            "2026-08-01",
            "2026-09-13",
            "category",
        )


@pytest.mark.anyio
async def test_oversized_response_fails_without_partial_total() -> None:
    with pytest.raises(YnabError, match="incomplete_data"):
        await spending_summary(
            spending_client(oversized=True), "2026-09-01", "2026-09-13", "category"
        )


@pytest.mark.anyio
async def test_server_exposes_read_only_grouping_enum() -> None:
    server = build_server(scoped_settings(), spending_client())
    async with Client(server) as mcp_client:
        tools = {tool.name: tool for tool in (await mcp_client.list_tools()).tools}
        tool = tools["get_spending_summary"]
        assert tool.annotations.read_only_hint is True
        assert set(tool.input_schema["properties"]["group_by"]["enum"]) == {
            "category",
            "payee",
            "account",
            "month",
        }
        result = await mcp_client.call_tool(
            "get_spending_summary",
            {
                "start_date": "2026-09-01",
                "end_date": "2026-09-13",
                "group_by": "category",
            },
        )
        assert not result.is_error
        assert result.structured_content["groups"]["Restaurants"] == "65.00"
