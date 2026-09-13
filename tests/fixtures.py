"""Synthetic YNAB test values shared by client and tool tests."""

from uuid import UUID

import httpx

from ynab_mcp.client import YnabClient
from ynab_mcp.config import Settings

PLAN_ID = UUID("12345678-1234-5678-1234-567812345678")
OTHER_PLAN_ID = UUID("87654321-4321-8765-4321-876543218765")
TOKEN = "sentinel-secret"


def scoped_settings() -> Settings:
    return Settings(pat=TOKEN, plan_id=PLAN_ID)


def setup_settings() -> Settings:
    return Settings(pat=TOKEN, plan_id=None)


def ynab_response(**resources: object) -> httpx.Response:
    """Wrap synthetic resources in the official API's `data` envelope."""
    return httpx.Response(200, json={"data": resources})


def account_fixture_client() -> YnabClient:
    """Return a client serving open, tracking, and closed account balances."""
    plans = [
        {
            "id": str(PLAN_ID),
            "name": "Fixture Plan",
            "last_modified_on": "private-metadata",
            "currency_format": {"iso_code": "USD", "decimal_digits": 2},
        }
    ]
    accounts = [
        {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "name": "Checking",
            "type": "checking",
            "on_budget": True,
            "closed": False,
            "cleared_balance": 900000,
            "uncleared_balance": 100000,
            "balance": 1000000,
            "deleted": False,
            "note": "private-account-note",
        },
        {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "name": "Credit Card",
            "type": "creditCard",
            "on_budget": True,
            "closed": False,
            "cleared_balance": -120000,
            "uncleared_balance": -30000,
            "balance": -150000,
            "deleted": False,
        },
        {
            "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "name": "Brokerage",
            "type": "investmentAccount",
            "on_budget": False,
            "closed": False,
            "cleared_balance": 150000,
            "uncleared_balance": 50000,
            "balance": 200000,
            "deleted": False,
        },
        {
            "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "name": "Closed Checking",
            "type": "checking",
            "on_budget": True,
            "closed": True,
            "cleared_balance": 50000,
            "uncleared_balance": 0,
            "balance": 50000,
            "deleted": False,
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/plans":
            return ynab_response(plans=plans)
        if request.url.path == f"/v1/plans/{PLAN_ID}/accounts":
            return ynab_response(accounts=accounts)
        return httpx.Response(404, json={"error": "unexpected fixture route"})

    return YnabClient(scoped_settings(), httpx.MockTransport(handler))
