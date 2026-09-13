class YnabError(Exception):
    """Stable, sanitized error safe to return to an MCP caller."""

    def __init__(self, code: str, status: int | None = None) -> None:
        self.code = code
        self.status = status
        super().__init__(code)
