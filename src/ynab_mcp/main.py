"""Start the local MCP server over stdio."""

import logging
import os
import sys

from ynab_mcp.client import YnabClient
from ynab_mcp.config import Settings
from ynab_mcp.server import build_server


def main() -> None:
    settings = Settings.from_env(os.environ)
    handler = logging.StreamHandler(sys.stderr)
    logging.basicConfig(level=logging.WARNING, handlers=[handler])
    client = YnabClient(settings)
    build_server(settings, client).run(transport="stdio")
