from uuid import UUID

import httpx
import pytest
from mcp.client import Client

from ynab_mcp.client import YnabClient
from ynab_mcp.config import Settings
from ynab_mcp.server import build_server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def fake_client(settings: Settings, calls: list[httpx.Request]) -> YnabClient:
    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "plans": [
                        {
                            "id": "12345678-1234-5678-1234-567812345678",
                            "name": "Test Plan",
                            "last_modified_on": "private-metadata",
                        }
                    ]
                }
            },
        )

    return YnabClient(settings, transport=httpx.MockTransport(respond))


@pytest.mark.anyio
async def test_setup_mode_exposes_only_list_plans_on_demand() -> None:
    settings = Settings.from_env({"YNAB_PAT": "sentinel-secret"})
    calls: list[httpx.Request] = []
    server = build_server(settings, fake_client(settings, calls))
    assert calls == []

    async with Client(server) as mcp_client:
        tools = (await mcp_client.list_tools()).tools
        assert {tool.name for tool in tools} == {"list_plans"}
        assert tools[0].annotations is not None
        assert tools[0].annotations.read_only_hint is True

        result = await mcp_client.call_tool("list_plans", {})
        assert not result.is_error
        assert result.structured_content == {
            "plans": [
                {
                    "id": "12345678-1234-5678-1234-567812345678",
                    "name": "Test Plan",
                }
            ]
        }
        assert len(calls) == 1
        assert calls[0].method == "GET"
        assert calls[0].url.path == "/v1/plans"

        rejected = await mcp_client.call_tool("delete_transaction", {})
        assert rejected.is_error


@pytest.mark.anyio
async def test_scoped_mode_hides_discovery_and_does_not_fetch_on_startup() -> None:
    settings = Settings.from_env(
        {
            "YNAB_PAT": "sentinel-secret",
            "YNAB_PLAN_ID": str(UUID("12345678-1234-5678-1234-567812345678")),
        }
    )
    calls: list[httpx.Request] = []
    server = build_server(settings, fake_client(settings, calls))
    async with Client(server) as mcp_client:
        assert "list_plans" not in {
            tool.name for tool in (await mcp_client.list_tools()).tools
        }
        assert (await mcp_client.call_tool("list_plans", {})).is_error
    assert calls == []
