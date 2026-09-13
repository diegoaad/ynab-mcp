import os
import tempfile
from pathlib import Path

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_stdio_setup_mode_keeps_secret_off_stderr() -> None:
    secret = "sentinel-secret-stdio"
    root = Path(__file__).resolve().parents[1]
    parameters = StdioServerParameters(
        command="uv",
        args=["run", "--frozen", "ynab-mcp"],
        cwd=root,
        env={
            "YNAB_PAT": secret,
            "UV_CACHE_DIR": os.environ.get(
                "UV_CACHE_DIR", "/private/tmp/ynab-mcp-uv-cache"
            ),
        },
    )
    with tempfile.TemporaryFile(mode="w+t") as stderr:
        async with (
            stdio_client(parameters, errlog=stderr) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            tools = (await session.list_tools()).tools
            assert {tool.name for tool in tools} == {"list_plans"}
        stderr.seek(0)
        assert secret not in stderr.read()
