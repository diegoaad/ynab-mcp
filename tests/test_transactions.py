"""Bounded transaction details from synthetic YNAB responses."""

from typing import Any

import httpx
import pytest
from mcp.client import Client

from tests.fixtures import PLAN_ID, scoped_settings, ynab_response
from ynab_mcp.client import YnabClient
from ynab_mcp.server import build_server
from ynab_mcp.tools.transactions import transaction_list

ACCOUNT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CATEGORY = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PAYEE = "cccccccc-cccc-cccc-cccc-cccccccccccc"
OTHER = "dddddddd-dddd-dddd-dddd-dddddddddddd"


def row(number: int, **changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": f"00000000-0000-0000-0000-{number:012d}",
        "date": "2026-09-15",
        "amount": -12340,
        "account_id": ACCOUNT,
        "account_name": "Checking",
        "category_id": CATEGORY,
        "category_name": "Groceries",
        "payee_id": PAYEE,
        "payee_name": "Market",
        "memo": "private-memo",
        "cleared": "cleared",
        "approved": True,
        "deleted": False,
        "subtransactions": [],
        "private_key": "private-payload",
    }
    value.update(changes)
    return value


def transaction_fixture_client(
    rows: list[dict[str, Any]], calls: list[httpx.Request] | None = None
) -> YnabClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if request.url.path == "/v1/plans":
            return ynab_response(
                plans=[
                    {
                        "id": str(PLAN_ID),
                        "name": "Fixture Plan",
                        "currency_format": {"iso_code": "USD", "decimal_digits": 2},
                    }
                ]
            )
        if request.url.path.endswith("/transactions"):
            return ynab_response(transactions=rows)
        return httpx.Response(404)

    return YnabClient(scoped_settings(), httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_limit_is_output_only_and_marked() -> None:
    calls: list[httpx.Request] = []
    result = await transaction_list(
        transaction_fixture_client([row(1), row(2), row(3)], calls),
        "2026-09-01",
        "2026-09-30",
        limit=2,
    )
    assert len(result["transactions"]) == 2
    assert result["truncated"] is True
    assert result["complete"] is False
    assert result["currency"] == "USD"
    assert result["since_date"] == "2026-09-01"
    assert result["until_date"] == "2026-09-30"
    assert all("memo" not in item for item in result["transactions"])
    assert [request.url.path for request in calls].count("/v1/plans") == 1
    assert (
        len(
            [request for request in calls if request.url.path.endswith("/transactions")]
        )
        == 1
    )
    transaction_call = next(
        request for request in calls if request.url.path.endswith("/transactions")
    )
    assert transaction_call.url.params["since_date"] == "2026-09-01"
    assert transaction_call.url.params["until_date"] == "2026-09-30"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("start", "end", "limit", "account_id"),
    [
        ("2026-09-01", "2026-09-30", 0, None),
        ("2026-09-01", "2026-09-30", 501, None),
        ("2026-09-30", "2026-09-01", 1, None),
        ("2025-01-01", "2026-01-02", 1, None),
        ("2026-09-01", "2026-09-30", 1, "not-a-uuid"),
    ],
)
async def test_invalid_bounds_and_ids_rejected_before_fetch(
    start: str, end: str, limit: int, account_id: str | None
) -> None:
    calls: list[httpx.Request] = []
    with pytest.raises(ValueError):
        await transaction_list(
            transaction_fixture_client([row(1)], calls),
            start,
            end,
            limit=limit,
            account_id=account_id,
        )
    assert calls == []


@pytest.mark.anyio
async def test_combined_filters_match_split_category_then_cap() -> None:
    split = row(
        4,
        category_id=None,
        category_name=None,
        subtransactions=[
            {
                "id": "split-1",
                "amount": -12340,
                "category_id": CATEGORY,
                "category_name": "Groceries",
                "memo": "split-private",
            }
        ],
    )
    calls: list[httpx.Request] = []
    result = await transaction_list(
        transaction_fixture_client(
            [
                row(1, account_id=OTHER),
                row(2, payee_id=OTHER),
                row(3, category_id=OTHER),
                split,
                row(5, deleted=True),
            ],
            calls,
        ),
        "2026-09-01",
        "2026-09-30",
        account_id=ACCOUNT,
        category_id=CATEGORY,
        payee_id=PAYEE,
        limit=1,
    )
    assert [item["id"] for item in result["transactions"]] == [split["id"]]
    assert result["truncated"] is False
    assert result["complete"] is True
    assert any(
        request.url.path == f"/v1/plans/{PLAN_ID}/transactions" for request in calls
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "filter_name, child_field, child_value",
    [("payee_id", "payee_id", PAYEE), ("category_id", "category_id", CATEGORY)],
)
async def test_split_child_filter_uses_complete_plan_listing(
    filter_name: str, child_field: str, child_value: str
) -> None:
    split = row(
        8,
        payee_id=OTHER,
        category_id=OTHER,
        subtransactions=[
            {
                "id": "child",
                "amount": -12340,
                "category_id": OTHER,
                "payee_id": OTHER,
                child_field: child_value,
            }
        ],
    )
    calls: list[httpx.Request] = []
    result = await transaction_list(
        transaction_fixture_client([split], calls),
        "2026-09-01",
        "2026-09-30",
        **{filter_name: child_value},
    )
    assert [item["id"] for item in result["transactions"]] == [split["id"]]
    assert [
        request.url.path
        for request in calls
        if request.url.path.endswith("/transactions")
    ] == [f"/v1/plans/{PLAN_ID}/transactions"]


@pytest.mark.anyio
async def test_sorted_detail_and_opted_in_memos() -> None:
    result = await transaction_list(
        transaction_fixture_client(
            [
                row(3, date="2026-09-14"),
                row(
                    2,
                    amount=5000,
                    subtransactions=[
                        {
                            "id": "split-2",
                            "amount": 5000,
                            "category_id": CATEGORY,
                            "category_name": "Groceries",
                            "memo": "split-private",
                        }
                    ],
                ),
                row(1),
                row(4, deleted=True),
                row(5, date="2026-10-01"),
            ]
        ),
        "2026-09-01",
        "2026-09-30",
        include_memo=True,
    )
    items = result["transactions"]
    assert [item["id"] for item in items] == [row(1)["id"], row(2)["id"], row(3)["id"]]
    assert [item["amount"] for item in items] == ["-12.34", "5.00", "-12.34"]
    assert items[0]["memo"] == "private-memo"
    assert items[1]["subtransactions"][0]["memo"] == "split-private"
    assert "private_key" not in repr(result)
    assert result["truncated"] is False
    assert result["complete"] is True


@pytest.mark.anyio
async def test_server_registers_bounded_read_only_tool() -> None:
    server = build_server(scoped_settings(), transaction_fixture_client([row(1)]))
    async with Client(server) as mcp_client:
        tools = {tool.name: tool for tool in (await mcp_client.list_tools()).tools}
        assert tools["list_transactions"].annotations.read_only_hint is True
        props = tools["list_transactions"].input_schema["properties"]
        assert props["limit"]["maximum"] == 500
        assert props["limit"]["minimum"] == 1
        result = await mcp_client.call_tool(
            "list_transactions",
            {"since_date": "2026-09-01", "until_date": "2026-09-30"},
        )
        assert not result.is_error
        assert result.structured_content["transactions"][0]["amount"] == "-12.34"
