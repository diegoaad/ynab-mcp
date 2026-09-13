"""Synthetic YNAB test values shared by client and tool tests."""

from uuid import UUID

import httpx

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
