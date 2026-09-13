"""Actionable uncategorized outflows from synthetic YNAB responses."""

from typing import Any

import httpx
import pytest

from tests.fixtures import PLAN_ID, scoped_settings, ynab_response
from ynab_mcp.client import YnabClient
from ynab_mcp.errors import YnabError
from ynab_mcp.tools import transactions


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _row(identifier: str, **changes: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": identifier,
        "date": "2026-09-15",
        "account_id": "checking",
        "account_name": "Checking",
        "amount": -12000,
        "category_id": None,
        "category_name": None,
        "payee_id": "market",
        "payee_name": "Market",
        "transfer_account_id": None,
        "memo": "secret memo",
        "cleared": "cleared",
        "approved": True,
        "deleted": False,
        "subtransactions": [],
    }
    row.update(changes)
    return row


def uncategorized_fixture_client(
    rows: list[dict[str, Any]] | None = None,
    calls: list[httpx.Request] | None = None,
) -> YnabClient:
    accounts = [
        {
            "id": "checking",
            "name": "Checking",
            "on_budget": True,
            "closed": False,
            "deleted": False,
        },
        {
            "id": "savings",
            "name": "Savings",
            "on_budget": True,
            "closed": False,
            "deleted": False,
        },
        {
            "id": "tracking",
            "name": "Brokerage",
            "on_budget": False,
            "closed": False,
            "deleted": False,
        },
        {
            "id": "closed",
            "name": "Closed",
            "on_budget": True,
            "closed": True,
            "deleted": False,
        },
    ]
    transactions = (
        rows
        if rows is not None
        else [
            _row("purchase-1"),
            _row("ordinary-transfer", transfer_account_id="savings"),
            _row("inflow", amount=1000),
            _row("tracking-item", account_id="tracking"),
            _row("closed-item", account_id="closed"),
            _row("deleted-item", deleted=True),
            _row(
                "split-parent",
                amount=-20000,
                subtransactions=[
                    {
                        "id": "split-part-1",
                        "amount": -8000,
                        "category_id": None,
                        "category_name": None,
                        "payee_id": "market",
                        "payee_name": "Market",
                        "transfer_account_id": None,
                    },
                    {
                        "id": "split-part-2",
                        "amount": -12000,
                        "category_id": "groceries",
                        "category_name": "Groceries",
                        "payee_id": "market",
                        "payee_name": "Market",
                        "transfer_account_id": None,
                    },
                ],
            ),
        ]
    )

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
        if request.url.path == f"/v1/plans/{PLAN_ID}/accounts":
            return ynab_response(accounts=accounts)
        if request.url.path == f"/v1/plans/{PLAN_ID}/transactions":
            return ynab_response(transactions=transactions)
        return httpx.Response(404)

    return YnabClient(scoped_settings(), httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_only_actionable_uncategorized_outflows() -> None:
    calls: list[httpx.Request] = []
    result = await transactions.uncategorized_transactions(
        uncategorized_fixture_client(calls=calls), "2026-09-01", "2026-09-30"
    )
    items = result["transactions"]
    assert [item["id"] for item in items] == ["purchase-1", "split-part-1"]
    assert [item["amount"] for item in items] == ["-12.00", "-8.00"]
    assert items[1]["date"] == "2026-09-15"
    assert items[1]["account_id"] == "checking"
    assert items[1]["subtransactions"] == []
    assert result["currency"] == "USD"
    assert result["complete"] is True
    assert "memo" not in repr(result)
    assert all(request.method == "GET" for request in calls)
    transaction_call = next(
        request for request in calls if request.url.path.endswith("/transactions")
    )
    assert dict(transaction_call.url.params) == {
        "since_date": "2026-09-01",
        "until_date": "2026-09-30",
    }


@pytest.mark.anyio
async def test_cap_applies_after_eligibility_and_marks_truncation() -> None:
    result = await transactions.uncategorized_transactions(
        uncategorized_fixture_client(), "2026-09-01", "2026-09-30", limit=1
    )
    assert [item["id"] for item in result["transactions"]] == ["purchase-1"]
    assert result["truncated"] is True
    assert result["complete"] is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("start", "end", "limit"),
    [
        ("2026-09-01", "2026-09-30", 0),
        ("2026-09-01", "2026-09-30", 501),
        ("2026-09-30", "2026-09-01", 1),
        ("2025-01-01", "2026-01-02", 1),
    ],
)
async def test_invalid_bounds_rejected_before_fetch(
    start: str, end: str, limit: int
) -> None:
    calls: list[httpx.Request] = []
    with pytest.raises(ValueError):
        await transactions.uncategorized_transactions(
            uncategorized_fixture_client(calls=calls), start, end, limit=limit
        )
    assert calls == []


@pytest.mark.anyio
async def test_unknown_transfer_destination_fails_closed() -> None:
    with pytest.raises(YnabError, match="incomplete_data"):
        await transactions.uncategorized_transactions(
            uncategorized_fixture_client(
                [_row("unknown-transfer", transfer_account_id="missing")]
            ),
            "2026-09-01",
            "2026-09-30",
        )
