# YNAB MCP server (Phase 1)

A local, read-only MCP server for one personal YNAB plan. It runs over `stdio`, fetches current data on demand from `https://api.ynab.com/v1`, and does not save financial data, cache responses, or send telemetry. Python 3.12+ and `uv` are required.

## Set up

1. Create a YNAB Personal Access Token (PAT) in your YNAB account and keep it in your local MCP host configuration. The server does not load `.env` automatically. `.env.example` contains placeholders only; `.env` is ignored by Git.
2. In this audited checkout, run `uv sync --frozen`.
3. Set `YNAB_PAT` but leave `YNAB_PLAN_ID` unset, then start the server and call `list_plans` to find your plan UUID. Setup mode exposes only that tool.
4. Add the UUID to the host configuration and restart. For example, replace the path and placeholders locally:

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

The configured server exposes `list_accounts`, `get_budget_summary`, `list_categories`, `list_transactions`, `get_spending_summary`, and `get_uncategorized_transactions`. All are read-only tools. `YNAB_READ_ONLY` defaults to `true`; setting it to any other value fails startup. Logging is fixed at `WARNING`; setting `LOG_LEVEL` fails startup. If you no longer need access or suspect exposure, revoke the PAT in YNAB and remove it from your host configuration.

## What the results mean

- Account balances and their on-budget, tracking, and combined totals are **signed net balances**, including liabilities. They are not spendable cash. Closed accounts are excluded by default; deleted accounts are always excluded.
- `available_in_categories` sums non-deleted, non-internal month-category balances, including hidden categories. Ready to Assign is separate. YNAB's documented category schema has no stable credit-card-payment discriminator, so internal credit-card-payment balances may be omitted. This number is neither cash available nor the sum of account balances.
- Spending is net expense-category outflows plus eligible uncategorized outflows on on-budget accounts; refunds reduce spending. Ordinary transfers between on-budget accounts, tracking-account postings, deleted rows, and Ready to Assign inflows are excluded. `get_uncategorized_transactions` shows actionable open-account outflows rather than every row lacking a category.
- Dates are inclusive and the current month uses UTC. A current-month bucket is month-to-date; compare it with the same days in the previous month for equal coverage. For example, compare September 1–13 with August 1–13, rather than all of August. Clamp the prior end date to its last calendar day when needed.
- Date ranges are limited to 366 days. Transaction tools return at most 500 rows, with `truncated` and `complete` flags; `list_transactions` omits memos unless `include_memo=true`. Aggregate tools require complete source data and return an error instead of a partial total when the bounded response cannot be processed. Money values are fixed-scale decimal strings in the plan currency.

## Privacy boundary

The PAT itself is **not provider-enforced read-only** and can access any plan allowed by that token. The fixed plan UUID and GET-only routes constrain this server; they do not reduce the PAT's underlying permissions. The server has no YNAB write route, does not follow redirects, and does not take a caller-supplied URL. Its own no-persistence rule does not apply to your MCP host: financial results cross into the host and may enter its history or be sent to a remote model. Use a host whose data-handling policy you accept. Payee names, category names, and memos are untrusted data fields, not instructions to the assistant.

## Verify this checkout

```bash
uv sync --frozen
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pip-audit
```

The dependency audit is an explicit development/release check and may use the network. The running MCP server does not audit dependencies or phone home for that purpose. Tests use synthetic data and a fake PAT; no live YNAB account is needed.
