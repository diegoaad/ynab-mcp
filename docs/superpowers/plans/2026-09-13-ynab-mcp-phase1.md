# YNAB MCP Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a local, PAT-authenticated, read-only MCP server that answers the five questions in the Phase 1 spec with complete and labeled YNAB data.

**Architecture:** A small `stdio` MCP adapter calls focused tool functions, which use one GET-only YNAB client. Date and money rules and spending aggregation are pure functions with synthetic fixtures. No server-owned financial persistence or HTTP listener exists.

**Tech Stack:** Python 3.12+, `uv`, `mcp==2.2.0`, `httpx==0.28.1`, `pytest==9.1.1`, `ruff==0.16.7`, `mypy==2.3.1`, `pip-audit==2.10.1`.

**Spec:** [Phase 1 design](../specs/2026-09-13-ynab-mcp-phase1-design.md)

## Global Constraints

- `YNAB_PAT` is the only credential input. A PAT is not provider-enforced read-only; this server must contain only GET YNAB methods and no write registrations.
- `YNAB_READ_ONLY` defaults to `true`; `false` fails startup. `YNAB_PLAN_ID` is a fixed UUID for normal mode. Missing ID exposes only `list_plans`.
- Runtime outbound origin is exactly `https://api.ynab.com/v1`, with redirects and environment proxies disabled. No arbitrary URL input, telemetry, listener, cache, or persisted financial data.
- All YNAB amounts remain integer milliunits until output. Output amounts are decimal strings with an ISO currency code and the plan's currency scale.
- Date ranges are inclusive, explicitly bounded to 366 days. Transaction detail output defaults to 100 and caps at 500; incomplete aggregates are errors.
- `stdout` carries MCP protocol only; sanitized logs go to `stderr`. Never log headers, bodies, names, memos, amounts, query values, or the PAT.
- The official YNAB [API reference](https://api.ynab.com/v1) and [MCP Python SDK v2 documentation](https://py.sdk.modelcontextprotocol.io/) are authoritative if examples here need adapting to a verified release detail.
- Run each task's focused test, then the existing suite, and commit the passing task. No live PAT or personal data in tests.

---

## File map and interfaces

| File | Responsibility |
| --- | --- |
| `pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example` | Reproducible package and secret-safe local setup. |
| `src/ynab_mcp/config.py` | Parse environment into immutable `Settings` without secret-bearing representations. |
| `src/ynab_mcp/dates.py` | Validate month and inclusive date windows. |
| `src/ynab_mcp/money.py` | Exact milliunit-to-currency formatting from `CurrencyFormat`. |
| `src/ynab_mcp/errors.py` | Stable sanitized `YnabError` classifications. |
| `src/ynab_mcp/client.py` | Only permitted YNAB GET routes, bounded HTTP responses, and narrow response validation. |
| `src/ynab_mcp/tools/overview.py` | Account, category, and month summary projections. |
| `src/ynab_mcp/tools/transactions.py` | Filtered transaction detail and uncategorized projections. |
| `src/ynab_mcp/analysis.py` | Pure posting extraction and complete spending aggregation. |
| `src/ynab_mcp/tools/spending.py` | Spending-summary orchestration and result metadata. |
| `src/ynab_mcp/server.py`, `main.py`, `tools/__init__.py` | Conditional MCP registration and `stdio` entry point. |
| `tests/` | Synthetic HTTP and MCP protocol tests; no real credentials. |
| `README.md` | Installation, host configuration, privacy boundary, and accepted limits. |

The public Python interfaces are `Settings.from_env(env)`, `parse_month(value)`, `parse_window(start, end)`, `format_milliunits(value, currency)`, `YnabClient(settings, transport=None)`, `build_server(settings, client)`, `extract_postings(transactions, accounts, categories)`, and `aggregate_postings(postings, group_by, start, end)`. Tool functions return ordinary dictionaries whose money fields are strings. The client does not expose a generic public `request` or caller-supplied path API.

Test helpers live in `tests/fixtures.py`: `scoped_settings()` uses PAT `sentinel-secret` and plan UUID `00000000-0000-4000-8000-000000000001`; `mocked_client()` returns a `YnabClient` backed by `httpx.MockTransport`; `account_fixture_client()`, `month_fixture_client()`, `transaction_fixture_client(count)`, `spending_fixture_client()`, and `uncategorized_fixture_client()` return the synthetic responses described in their tasks. Keep the fixture JSON small and explicit in that file, with no recorded personal responses. The pure `spending_fixture_transactions()`, `spending_fixture_accounts()`, and `spending_fixture_categories()` expose those same records to Task 8.

### Task 1: Package, configuration, and secret-safe setup

**Files:** Create `pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example`, `src/ynab_mcp/__init__.py`, `src/ynab_mcp/config.py`, `tests/test_config.py`.

**Interfaces:** Produces immutable `Settings(pat: str, plan_id: UUID | None, log_level: str)` and `Settings.from_env(env: Mapping[str, str]) -> Settings`.

`ConfigError` is a local `ValueError` subclass whose message contains only configuration field names and fixed text. Unit tests import it from `ynab_mcp.config`.

- [ ] **Step 1: Write failing configuration tests.**

```python
def test_setup_mode_and_secret_repr() -> None:
    settings = Settings.from_env({"YNAB_PAT": "sentinel-secret"})
    assert settings.plan_id is None
    assert "sentinel-secret" not in repr(settings)


def test_read_only_false_fails() -> None:
    with pytest.raises(ConfigError, match="read-only"):
        Settings.from_env({"YNAB_PAT": "sentinel-secret", "YNAB_READ_ONLY": "false"})


def test_plan_alias_is_rejected() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"YNAB_PAT": "sentinel-secret", "YNAB_PLAN_ID": "last-used"})
```

- [ ] **Step 2: Run `uv run pytest tests/test_config.py -q`; expect collection/import failure.**
- [ ] **Step 3: Create the package metadata and minimum implementation.**

```toml
[project]
name = "ynab-mcp"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["mcp==2.2.0", "httpx==0.28.1"]

[project.scripts]
ynab-mcp = "ynab_mcp.main:main"

[build-system]
requires = ["hatchling==1.32.0"]
build-backend = "hatchling.build"

[dependency-groups]
dev = ["pytest==9.1.1", "ruff==0.16.7", "mypy==2.3.1", "pip-audit==2.10.1"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["ynab_mcp"]
```

```python
@dataclass(frozen=True, repr=False)
class Settings:
    pat: str
    plan_id: UUID | None
    log_level: str = "WARNING"

    def __repr__(self) -> str:
        return f"Settings(pat=<redacted>, plan_id={self.plan_id}, log_level={self.log_level})"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        pat = env.get("YNAB_PAT", "").strip()
        if not pat:
            raise ConfigError("YNAB_PAT is required")
        if env.get("YNAB_READ_ONLY", "true").lower() != "true":
            raise ConfigError("Phase 1 is read-only")
        raw_id = env.get("YNAB_PLAN_ID", "").strip()
        try:
            plan_id = UUID(raw_id) if raw_id else None
        except ValueError:
            raise ConfigError("YNAB_PLAN_ID must be a UUID") from None
        return cls(pat=pat, plan_id=plan_id, log_level=env.get("LOG_LEVEL", "WARNING"))
```

Add `.env`, `.venv`, cache and build paths to `.gitignore`. `.env.example` contains placeholder values only. Pin the build backend as shown; do not add `pydantic-settings` solely for three variables.

- [ ] **Step 4: Run `uv lock`, `uv sync --frozen`, and `uv run pytest tests/test_config.py -q`; expect pass.**
- [ ] **Step 5: Commit `feat: add locked package and safe configuration`.**

### Task 2: Exact currency and date rules

**Files:** Create `src/ynab_mcp/money.py`, `dates.py`, `tests/test_money.py`, `tests/test_dates.py`.

**Interfaces:** Produces `CurrencyFormat(iso_code: str, decimal_digits: int)`, `format_milliunits(value: int, currency: CurrencyFormat) -> str`, `parse_month(value: str | None) -> date`, and `parse_window(start: str, end: str) -> tuple[date, date]`.

- [ ] **Step 1: Write failing tests for precision, calendar validity, and inclusive length.**

```python
@pytest.mark.parametrize(
    ("milliunits", "digits", "expected"),
    [
        (1000, 2, "1.00"),
        (123450, 2, "123.45"),
        (-42100, 2, "-42.10"),
        (1300, 1, "1.3"),
        (-395032, 3, "-395.032"),
    ],
)
def test_exact_money(milliunits: int, digits: int, expected: str) -> None:
    assert format_milliunits(milliunits, CurrencyFormat("USD", digits)) == expected


def test_invalid_precision_and_month() -> None:
    with pytest.raises(ValueError):
        format_milliunits(1001, CurrencyFormat("USD", 2))
    with pytest.raises(ValueError):
        parse_month("2026-09-13")


def test_window_is_inclusive_and_bounded() -> None:
    assert parse_window("2026-09-01", "2026-09-01")[0].day == 1
    with pytest.raises(ValueError):
        parse_window("2025-01-01", "2026-09-01")
```

- [ ] **Step 2: Run the two focused test modules; expect import failure.**
- [ ] **Step 3: Implement exact conversion and date parsing.**

```python
@dataclass(frozen=True)
class CurrencyFormat:
    iso_code: str
    decimal_digits: int


def format_milliunits(value: int, currency: CurrencyFormat) -> str:
    if currency.decimal_digits not in (0, 1, 2, 3):
        raise ValueError("unsupported currency precision")
    quantum = 10 ** (3 - currency.decimal_digits)
    if value % quantum:
        raise ValueError("milliunits exceed currency precision")
    amount = Decimal(value) / Decimal(1000)
    return f"{amount:.{currency.decimal_digits}f}"


def parse_month(value: str | None) -> date:
    month = (
        datetime.now(timezone.utc).date().replace(day=1)
        if value is None
        else date.fromisoformat(value)
    )
    if month.day != 1:
        raise ValueError("month must be the first day")
    return month


def parse_window(start: str, end: str) -> tuple[date, date]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if not first <= last or (last - first).days + 1 > 366:
        raise ValueError("date window must span 1 through 366 days")
    return first, last
```

- [ ] **Step 4: Run focused tests and the existing suite; expect pass.**
- [ ] **Step 5: Commit `feat: validate dates and format exact YNAB amounts`.**

### Task 3: GET-only bounded YNAB client

**Files:** Create `src/ynab_mcp/errors.py`, `client.py`, `tests/test_client.py`, `tests/fixtures.py`.

**Interfaces:** `YnabClient(settings: Settings, transport: httpx.AsyncBaseTransport | None = None)` produces `get_plans() -> list[dict]`, `get_plan_metadata() -> dict`, `get_accounts() -> list[dict]`, `get_month(month: date) -> dict`, and `get_transactions(start: date, end: date, *, account_id: UUID | None = None, category_id: UUID | None = None, payee_id: UUID | None = None) -> list[dict]`. These return the selected resource inside the YNAB `data` wrapper, not the wrapper itself. `get_plan_metadata` selects the configured UUID from `GET /plans`; `get_month` returns the `month` object. `YnabError(code: str, status: int | None = None)` is safe to show to MCP clients.

- [ ] **Step 1: Write failing `httpx.MockTransport` tests.**

```python
@pytest.mark.anyio
async def test_only_ynab_get_with_bearer() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": {"accounts": []}})

    client = YnabClient(scoped_settings(), httpx.MockTransport(handler))
    assert await client.get_accounts() == []
    assert seen[0].method == "GET"
    assert seen[0].url.host == "api.ynab.com"
    assert seen[0].headers["authorization"] == "Bearer sentinel-secret"


@pytest.mark.anyio
async def test_error_never_contains_pat() -> None:
    client = YnabClient(
        scoped_settings(),
        httpx.MockTransport(
            lambda request: httpx.Response(401, text="sentinel-secret")
        ),
    )
    with pytest.raises(YnabError) as caught:
        await client.get_accounts()
    assert "sentinel-secret" not in repr(caught.value)
```

Add parameterized cases for 400/401/403/404/409/429/500/503, timeout, malformed `data`, redirect 302, and an 8 MiB + 1-byte streamed body. Assert no second request on any failure and no raw body in exceptions.

- [ ] **Step 2: Run `uv run pytest tests/test_client.py -q`; expect import failure.**
- [ ] **Step 3: Implement closed route methods and streamed response validation.**

```python
BASE_URL = "https://api.ynab.com/v1"
MAX_BODY_BYTES = 8 * 1024 * 1024


class YnabError(Exception):
    def __init__(self, code: str, status: int | None = None) -> None:
        self.code, self.status = code, status
        super().__init__(code)


async def _read_bounded(response: httpx.Response) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise YnabError("incomplete_data")
    return bytes(body)
```

Inside `YnabClient`, private `_get_data(path, params=None)` creates an `httpx.AsyncClient(base_url=BASE_URL, timeout=httpx.Timeout(30.0, connect=5.0), trust_env=False, follow_redirects=False, transport=self._transport)` for the single call, sends a streamed GET with the bearer header, reads with `_read_bounded`, classifies status, parses JSON, and requires a mapping `data` wrapper. Public methods build paths from fixed route literals and `Settings.plan_id`. `get_transactions` chooses account, category, or payee route in that priority when supplied, then tool-level logic applies any remaining filters locally. It always sends both date query parameters and never sends `last_knowledge_of_server`. If the response redirects, reject it as an upstream error; do not follow the `Location` header.

- [ ] **Step 4: Run focused tests, existing suite, `uv run ruff check .`, and `uv run mypy src`; expect pass.**
- [ ] **Step 5: Commit `feat: add bounded GET-only YNAB client`.**

### Task 4: MCP startup, setup-only discovery, and protocol safety

**Files:** Create `src/ynab_mcp/server.py`, `main.py`, `tests/test_server.py`, `tests/test_stdio.py`.

**Interfaces:** Produces `build_server(settings: Settings, client: YnabClient) -> MCPServer` and `main() -> None`.

- [ ] **Step 1: Write failing in-process and subprocess MCP tests.**

```python
@pytest.mark.anyio
async def test_setup_mode_exposes_only_list_plans() -> None:
    server = build_server(
        Settings.from_env({"YNAB_PAT": "sentinel-secret"}), mocked_client()
    )
    async with Client(server) as mcp_client:
        names = {tool.name for tool in (await mcp_client.list_tools()).tools}
        assert names == {"list_plans"}
        result = await mcp_client.call_tool("delete_transaction", {})
        assert result.is_error


@pytest.mark.anyio
async def test_scoped_mode_hides_discovery() -> None:
    server = build_server(scoped_settings(), mocked_client())
    async with Client(server) as mcp_client:
        names = {tool.name for tool in (await mcp_client.list_tools()).tools}
        assert "list_plans" not in names
```

The subprocess smoke test launches `uv run --frozen ynab-mcp` through `StdioServerParameters` with a synthetic PAT and no plan ID, lists tools, and asserts stderr contains no PAT. It does not call a network tool.

- [ ] **Step 2: Run the focused tests; expect import failure.**
- [ ] **Step 3: Implement conditional registration and `stdio` entry.**

```python
def build_server(settings: Settings, client: YnabClient) -> MCPServer:
    mcp = MCPServer("YNAB personal plan")
    if settings.plan_id is None:

        @mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
        async def list_plans() -> dict[str, object]:
            """List plan IDs and names for local setup."""
            return {"plans": await client.get_plans()}

        return mcp
    return mcp


def main() -> None:
    settings = Settings.from_env(os.environ)
    client = YnabClient(settings)
    build_server(settings, client).run(transport="stdio")
```

Do not print startup banners to stdout. Set `logging.StreamHandler(sys.stderr)` and keep the default level at WARNING.

- [ ] **Step 4: Run focused tests and existing suite; expect pass.**
- [ ] **Step 5: Commit `feat: start local MCP in setup and scoped modes`.**

### Task 5: Account totals with clear scope labels

**Files:** Create `src/ynab_mcp/tools/accounts.py`, `tests/test_accounts.py`; modify `server.py`.

**Interfaces:** Produces `account_list(client: YnabClient, include_closed: bool = False) -> dict[str, object]`; registers `list_accounts` only in scoped mode.

Private helpers: `currency_from_plan(metadata: dict) -> CurrencyFormat` requires `currency_format.iso_code` and `decimal_digits`; `account_result(accounts: list[dict], on_budget: int, tracking: int, currency: CurrencyFormat) -> dict[str, object]` formats the three signed totals and every account balance.

- [ ] **Step 1: Write a failing synthetic fixture test with checking, credit-card, tracking, and closed accounts.**

```python
@pytest.mark.anyio
async def test_totals_are_signed_and_labeled() -> None:
    result = await account_list(account_fixture_client(), include_closed=False)
    assert result["currency"] == "USD"
    assert result["totals"]["on_budget"] == "850.00"
    assert result["totals"]["tracking"] == "200.00"
    assert result["totals"]["all_included"] == "1050.00"
    assert all(not account["closed"] for account in result["accounts"])
```

Use fixture balances of checking `1000000`, credit-card `-150000`, tracking `200000`, and closed `50000` milliunits. Assert each account has `on_budget`, type, cleared/uncleared/total balances, `as_of_utc`, and `complete=true`. The test's exact subtotal figures above derive from these values.

- [ ] **Step 2: Run `uv run pytest tests/test_accounts.py -q`; expect failure.**
- [ ] **Step 3: Implement projection and register the tool.**

```python
async def account_list(
    client: YnabClient, include_closed: bool = False
) -> dict[str, object]:
    metadata, accounts = await client.get_plan_metadata(), await client.get_accounts()
    included = [
        a for a in accounts if not a["deleted"] and (include_closed or not a["closed"])
    ]
    on_budget = sum(a["balance"] for a in included if a["on_budget"])
    tracking = sum(a["balance"] for a in included if not a["on_budget"])
    currency = currency_from_plan(metadata)
    return account_result(included, on_budget, tracking, currency)
```

`currency_from_plan` and `account_result` are private helpers in `tools/accounts.py`. They validate required fields and call `format_milliunits`; `account_result` labels `all_included` as a signed net balance, not spendable cash. Register an async `list_accounts(include_closed: bool = False)` wrapper with `read_only_hint=True`.

- [ ] **Step 4: Run focused tests, existing suite, lint, and type check; expect pass.**
- [ ] **Step 5: Commit `feat: report labeled YNAB account balances`.**

### Task 6: Month summary and category discovery

**Files:** Create `src/ynab_mcp/tools/months.py`, `tests/test_months.py`; modify `server.py`.

**Interfaces:** Produces `budget_summary(client, month: str | None = None) -> dict[str, object]` and `category_list(client, month: str | None = None, include_hidden: bool = False) -> dict[str, object]`.

Private helper: `month_summary_result(metadata: dict, data: dict, month: date, available: int) -> dict[str, object]` formats the month fields and records `complete=true`; `category_list` validates and projects the same month response's groups/categories.

- [ ] **Step 1: Write failing tests for historical month routing, hidden categories, and summary arithmetic.**

```python
@pytest.mark.anyio
async def test_month_summary_keeps_ready_to_assign_separate() -> None:
    result = await budget_summary(month_fixture_client(), "2026-08-01")
    assert result["month"] == "2026-08-01"
    assert result["ready_to_assign"] == "50.00"
    assert result["available_in_categories"] == "240.00"
    assert result["age_of_money"] is None


@pytest.mark.anyio
async def test_hidden_category_is_filtered_only_from_listing() -> None:
    result = await category_list(month_fixture_client(), "2026-08-01")
    assert all(not row["hidden"] for row in result["categories"])
```

The month fixture has ordinary balances `200000`, hidden `40000`, deleted `90000`, and internal `30000` milliunits. Assert summary includes the hidden amount but excludes deleted and internal amounts. Inspect the official schema before creating this fixture; if credit-card payment categories carry `internal=true`, apply the spec's explicit inclusion rule by identifying the credit-card payment category in a documented field, or revise that single rule in the spec before code. Do not infer it from an English display name.

- [ ] **Step 2: Run `uv run pytest tests/test_months.py -q`; expect failure.**
- [ ] **Step 3: Implement projections from `GET /plans/{id}/months/{month}`.**

```python
async def budget_summary(
    client: YnabClient, month: str | None = None
) -> dict[str, object]:
    selected = parse_month(month)
    metadata, data = await client.get_plan_metadata(), await client.get_month(selected)
    categories = data["categories"]
    available = sum(
        c["balance"] for c in categories if not c["deleted"] and not c["internal"]
    )
    return month_summary_result(metadata, data, selected, available)
```

`month_summary_result` and `category_list` format money with the plan currency, keep Ready to Assign separate, omit raw metadata, and use explicit `complete` and as-of/date coverage. Register `get_budget_summary` and `list_categories` with read-only annotations and concise descriptions.

- [ ] **Step 4: Run focused tests, existing suite, lint, and type check; expect pass.**
- [ ] **Step 5: Commit `feat: expose month summary and categories`.**

### Task 7: Bounded transaction detail

**Files:** Create `src/ynab_mcp/tools/transactions.py`, `tests/test_transactions.py`; modify `server.py`.

**Interfaces:** Produces `transaction_list(client, since_date: str, until_date: str, *, account_id: str | None = None, category_id: str | None = None, payee_id: str | None = None, limit: int = 100, include_memo: bool = False) -> dict[str, object]`.

Private helpers: `validate_optional_uuids(account_id, category_id, payee_id) -> dict[str, UUID | None]` rejects non-UUID strings; `filter_and_sort_transactions(rows: list[dict], ids: dict) -> list[dict]` applies every supplied ID, matching a split's category against its subtransactions; `transaction_result(rows: list[dict], *, truncated: bool, include_memo: bool, start: date, end: date) -> dict[str, object]` adds fixed-scale currency amounts, range, completeness, and optional memos.

- [ ] **Step 1: Write failing tests for bounds, local combined filters, and memo omission.**

```python
@pytest.mark.anyio
async def test_limit_is_output_only_and_marked() -> None:
    result = await transaction_list(
        transaction_fixture_client(3), "2026-09-01", "2026-09-30", limit=2
    )
    assert len(result["transactions"]) == 2
    assert result["truncated"] is True
    assert all("memo" not in row for row in result["transactions"])


@pytest.mark.anyio
async def test_limit_above_cap_is_rejected() -> None:
    with pytest.raises(ValueError):
        await transaction_list(
            transaction_fixture_client(1), "2026-09-01", "2026-09-30", limit=501
        )
```

Add cases for `limit=0`, reversed dates, 367-day windows, non-UUID filters, `include_memo=true`, deleted rows, and deterministic sorting by date descending then ID. Verify combined filters after the client's most-specific route selection and that `truncated` reflects the fully filtered set.

- [ ] **Step 2: Run `uv run pytest tests/test_transactions.py -q`; expect failure.**
- [ ] **Step 3: Implement validation, filtering, sorting, and projection.**

```python
async def transaction_list(
    client: YnabClient,
    since_date: str,
    until_date: str,
    *,
    account_id: str | None = None,
    category_id: str | None = None,
    payee_id: str | None = None,
    limit: int = 100,
    include_memo: bool = False,
) -> dict[str, object]:
    start, end = parse_window(since_date, until_date)
    if not 1 <= limit <= 500:
        raise ValueError("limit must be 1 through 500")
    ids = validate_optional_uuids(account_id, category_id, payee_id)
    rows = await client.get_transactions(start, end, **ids)
    filtered = filter_and_sort_transactions(rows, ids)
    return transaction_result(
        filtered[:limit],
        truncated=len(filtered) > limit,
        include_memo=include_memo,
        start=start,
        end=end,
    )
```

Private helpers in this file validate fields and convert amounts. Register `list_transactions` in `server.py` using bounded `Annotated[int, Field(ge=1, le=500)]` for MCP schema validation as well as internal validation.

- [ ] **Step 4: Run focused tests, existing suite, lint, and type check; expect pass.**
- [ ] **Step 5: Commit `feat: return bounded transaction details`.**

### Task 8: Pure spending-posting extraction

**Files:** Create `src/ynab_mcp/analysis.py`, `tests/test_analysis.py`.

**Interfaces:** Produces immutable `Posting(transaction_id: str, date: date, account_id: str, account_name: str, category_id: str | None, category_name: str, payee_id: str | None, payee_name: str | None, milliunits: int)` and `extract_postings(transactions: list[dict], accounts: list[dict], categories: list[dict]) -> list[Posting]`.

Private helper: `eligible_posting(tx: dict, part: dict, internal_ids: set[str], on_budget_ids: set[str]) -> Posting | None` applies the eligibility rules below and uses the parent for account/date and the part for amount/category/payee.

- [ ] **Step 1: Write failing fixture tests that pin accounting policy.**

```python
def test_split_refund_and_transfer_are_counted_once() -> None:
    rows = spending_fixture_transactions()
    postings = extract_postings(
        rows, spending_fixture_accounts(), spending_fixture_categories()
    )
    by_category = defaultdict(int)
    for posting in postings:
        by_category[posting.category_name] += posting.milliunits
    assert by_category["Restaurants"] == -65000
    assert by_category["Groceries"] == -20000
    assert by_category["Uncategorized"] == -10000
```

Fixture: split restaurant `-70000` and groceries `-20000` under a parent `-90000`; restaurant refund `+5000`; uncategorized purchase `-10000`; on-budget transfer pair `-30000`/`+30000`; tracking-side transaction `-40000`; Ready to Assign inflow `+100000`; deleted row. Add a categorized on-budget transfer to a tracking account and assert its category posting counts only once. Use IDs and `internal` flags, not English display names, to identify internal categories.

- [ ] **Step 2: Run `uv run pytest tests/test_analysis.py -q`; expect import failure.**
- [ ] **Step 3: Implement one posting per eligible non-split transaction or subtransaction.**

```python
def extract_postings(
    transactions: list[dict], accounts: list[dict], categories: list[dict]
) -> list[Posting]:
    on_budget = {a["id"] for a in accounts if a["on_budget"] and not a["deleted"]}
    internal = {c["id"] for c in categories if c["internal"]}
    result: list[Posting] = []
    for tx in transactions:
        if tx["deleted"] or tx["account_id"] not in on_budget:
            continue
        parts = tx["subtransactions"] if tx["subtransactions"] else [tx]
        for part in parts:
            posting = eligible_posting(tx, part, internal, on_budget)
            if posting is not None:
                result.append(posting)
    return result
```

`eligible_posting` is a private pure function in `analysis.py`. It excludes Ready to Assign/internal postings, ordinary uncategorized on-budget transfers, and positive uncategorized inflows; it retains categorized positive refunds and categorized on-budget-to-tracking transfers. Missing required fields raise `YnabError("incomplete_data")` rather than silently dropping rows.

- [ ] **Step 4: Run focused tests, existing suite, lint, and type check; expect pass.**
- [ ] **Step 5: Commit `feat: normalize spending postings without double counting`.**

### Task 9: Complete spending summaries and month coverage

**Files:** Create `src/ynab_mcp/tools/spending.py`, `tests/test_spending.py`; modify `analysis.py` and `server.py`.

**Interfaces:** Produces `aggregate_postings(postings: list[Posting], group_by: Literal["category", "payee", "account", "month"], start: date, end: date, *, today: date) -> dict[str, dict[str, int | str]]` and `spending_summary(client: YnabClient, start_date: str, end_date: str, group_by: Literal["category", "payee", "account", "month"]) -> dict[str, object]`.

Each aggregate group has `milliunits: int` and `coverage: str`; month coverage is `full_month`, `month_to_date` (current UTC month through today), or `partial_month` (any other incomplete month). Private helper `spending_result(totals: dict, metadata: dict, start: date, end: date, complete: bool) -> dict[str, object]` formats amounts and labels the inclusive range. `months_between(start: date, end: date) -> list[date]` returns the first day of each intersecting month in order.

- [ ] **Step 1: Write failing complete-data and partial-month tests.**

```python
@pytest.mark.anyio
async def test_category_summary_uses_all_rows_before_projection() -> None:
    result = await spending_summary(
        spending_fixture_client(), "2026-07-01", "2026-09-13", "category"
    )
    assert result["complete"] is True
    assert result["groups"]["Restaurants"] == "65.00"
    assert result["groups"]["Uncategorized"] == "10.00"


def test_current_month_bucket_is_labeled_partial() -> None:
    buckets = aggregate_postings(
        [], "month", date(2026, 8, 1), date(2026, 9, 13), today=date(2026, 9, 13)
    )
    assert buckets["2026-09"]["coverage"] == "month_to_date"
    prior = aggregate_postings(
        [], "month", date(2026, 8, 1), date(2026, 8, 13), today=date(2026, 9, 13)
    )
    assert prior["2026-08"]["coverage"] == "partial_month"
```

Include group-by payee/account/month fixtures, a refund that reduces net spending, a prior month ending on day 28 or 30, and an oversized-response client error that becomes `incomplete_data` rather than a numeric total.

- [ ] **Step 2: Run `uv run pytest tests/test_spending.py -q`; expect failure.**
- [ ] **Step 3: Implement complete-range aggregation.**

```python
async def spending_summary(
    client: YnabClient,
    start_date: str,
    end_date: str,
    group_by: Literal["category", "payee", "account", "month"],
) -> dict[str, object]:
    start, end = parse_window(start_date, end_date)
    transactions = await client.get_transactions(start, end)
    accounts = await client.get_accounts()
    metadata = await client.get_plan_metadata()
    month_data = [await client.get_month(month) for month in months_between(start, end)]
    categories = {
        category["id"]: category
        for data in month_data
        for category in data["categories"]
    }
    postings = extract_postings(transactions, accounts, list(categories.values()))
    totals = aggregate_postings(
        postings, group_by, start, end, today=datetime.now(timezone.utc).date()
    )
    return spending_result(totals, metadata, start, end, complete=True)
```

For a range crossing months, collect month-specific category metadata as shown; if the same ID has conflicting internal classification across months, return `incomplete_data` rather than taking the last dictionary entry. `aggregate_postings` groups integer milliunits first and never applies the 500-row detail cap. Register `get_spending_summary` with a `Literal` group-by schema.

- [ ] **Step 4: Run focused tests, existing suite, lint, and type check; expect pass.**
- [ ] **Step 5: Commit `feat: summarize complete spending ranges`.**

### Task 10: Uncategorized transactions and final MCP contracts

**Files:** Modify `src/ynab_mcp/tools/transactions.py`, `server.py`; create `tests/test_uncategorized.py`, `tests/test_mcp_contract.py`.

**Interfaces:** Produces `uncategorized_transactions(client, since_date: str, until_date: str, limit: int = 100) -> dict[str, object]` and registers `get_uncategorized_transactions`.

- [ ] **Step 1: Write failing synthetic and in-process MCP tests.**

```python
@pytest.mark.anyio
async def test_only_actionable_uncategorized_outflows() -> None:
    result = await uncategorized_transactions(
        uncategorized_fixture_client(), "2026-09-01", "2026-09-30"
    )
    assert [row["id"] for row in result["transactions"]] == [
        "purchase-1",
        "split-part-1",
    ]


@pytest.mark.anyio
async def test_scoped_mcp_tool_names_and_annotations() -> None:
    async with Client(build_server(scoped_settings(), mocked_client())) as mcp_client:
        tools = (await mcp_client.list_tools()).tools
        assert {t.name for t in tools} == {
            "get_budget_summary",
            "list_accounts",
            "list_categories",
            "list_transactions",
            "get_spending_summary",
            "get_uncategorized_transactions",
        }
        assert all(t.annotations and t.annotations.read_only_hint for t in tools)
```

Fixture includes a purchase, an on-budget transfer, an inflow, a tracking-account item, a closed-account item, and a split with one uncategorized outflow part. Assert output truncation and date validation too.

- [ ] **Step 2: Run focused tests; expect failure.**
- [ ] **Step 3: Implement eligibility, bounded output, and registration.**

```python
async def uncategorized_transactions(
    client: YnabClient, since_date: str, until_date: str, limit: int = 100
) -> dict[str, object]:
    start, end = parse_window(since_date, until_date)
    if not 1 <= limit <= 500:
        raise ValueError("limit must be 1 through 500")
    transactions = await client.get_transactions(start, end)
    accounts = await client.get_accounts()
    eligible = actionable_uncategorized(transactions, accounts)
    return transaction_result(
        eligible[:limit],
        truncated=len(eligible) > limit,
        include_memo=False,
        start=start,
        end=end,
    )
```

`actionable_uncategorized(transactions: list[dict], accounts: list[dict]) -> list[dict]` is a private function in `tools/transactions.py`; it handles split parts, negative amount, open on-budget account, and no ordinary transfer. Use the full date-bounded listing because the documented `type=uncategorized` filter does not specify whether it includes parents with uncategorized split parts. Keep public IDs in results but no API request paths, raw bodies, or headers.

- [ ] **Step 4: Run focused tests, existing suite, lint, and type check; expect pass.**
- [ ] **Step 5: Commit `feat: show actionable uncategorized transactions`.**

### Task 11: Privacy hardening, documentation, and release gate

**Files:** Create `README.md`, `tests/test_privacy.py`; modify `tests/test_stdio.py`, `pyproject.toml` only if checks expose issues.

**Interfaces:** No new MCP tools. Deliver reproducible host setup and a verified Phase 1 release.

- [ ] **Step 1: Write security regression checks at the MCP boundary.**

```python
def test_local_env_file_is_not_tracked() -> None:
    tracked = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    assert ".env" not in tracked
    assert "<secret>" in Path(".env.example").read_text()


@pytest.mark.anyio
async def test_pat_is_redacted_at_mcp_boundary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = scoped_settings()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, text="sentinel-secret")
    )
    async with Client(
        build_server(settings, YnabClient(settings, transport))
    ) as mcp_client:
        result = await mcp_client.call_tool("list_accounts", {})
    assert result.is_error
    assert "sentinel-secret" not in repr(result)
    assert "sentinel-secret" not in caplog.text
```

Extend the privacy test with an injected fake PAT in a YNAB error body and a payee/memo containing instruction-like text; assert no secret in logs/errors and that names/memos remain ordinary structured fields. Include an outbound-request recorder asserting every runtime request is GET to `api.ynab.com` and no request occurs at startup.

- [ ] **Step 2: Run privacy tests; fix any newly exposed redaction or routing failure before writing the README.**
- [ ] **Step 3: Write the README sections and resolve test failures.**

```json
{
  "mcpServers": {
    "ynab": {
      "command": "uv",
      "args": ["run", "--frozen", "--directory", "/absolute/path/to/ynab-mcp", "ynab-mcp"],
      "env": {
        "YNAB_PAT": "<set locally; never commit>",
        "YNAB_PLAN_ID": "<plan UUID>",
        "YNAB_READ_ONLY": "true"
      }
    }
  }
}
```

README also gives `uv sync --frozen`, `uv run --frozen pytest`, `uv run --frozen ruff check .`, `uv run --frozen ruff format --check .`, `uv run --frozen mypy src`, and `uv run --frozen pip-audit`. Explain PAT revocation, the server-only read restriction, host/model data exposure, no server persistence, UTC dates, output limits, account net-balance labels, and month-to-date comparison. Do not print a real token or suggest an unpinned `uvx ynab-mcp` install.

- [ ] **Step 4: Run the complete release gate and record results in the milestone report.**

```bash
uv sync --frozen
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pip-audit
git diff --check
git status --short
```

Run the subprocess `stdio` smoke test with a fake PAT. Review `git ls-files` for secrets, local databases, caches, and unexpected outputs. If the dependency audit needs network access, run it explicitly during this gate; the server itself never phones home for auditing.

- [ ] **Step 5: Commit `docs: finish Phase 1 setup and verification` only after the gate passes.**

## Acceptance trace

Milestone reports follow Tasks 4, 7, 10, and 11. Each report records what was implemented, files changed, tests added, exact verification commands and results, remaining risks, and the next step. A milestone is not reported complete merely because its task commits exist; run the current suite first.

| Spec requirement | Tasks that prove it |
| --- | --- |
| PAT from environment, fixed plan, setup-only mode, no mutations | 1, 3, 4, 10, 11 |
| Exact currency and UTC month/date validation | 2, 5, 6, 7, 9 |
| Fixed YNAB origin, bounded GET, sanitized errors, 429/503 | 3, 11 |
| Account balance question | 5 |
| Category discovery and budget summary | 6 |
| Bounded transaction detail | 7 |
| Split/refund/transfer semantics and spending questions | 8, 9 |
| Actionable uncategorized question | 10 |
| Protocol-level tools/list/call and `stdio` behavior | 4, 10, 11 |
| Privacy documentation, dependency audit, no persistence | 11 |

No Phase 2 write operation, money movement, scheduled transaction tool, payee-list tool, full-plan export, or persistent cache is included in this plan.
