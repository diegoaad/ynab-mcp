# Task 5 report: account totals with clear scope labels

Status: DONE

Branch: `codex/ynab-mcp-phase1`

## Files

- `src/ynab_mcp/tools/__init__.py`: initializes the focused tool package.
- `src/ynab_mcp/tools/accounts.py`: validates plan currency/account fields, filters deleted and closed accounts, preserves signed balances, computes on-budget/tracking/all-included totals, formats milliunits at the plan scale, and returns `as_of_utc` plus `complete=true` metadata. The all-included total is explicitly a signed net balance rather than spendable cash.
- `src/ynab_mcp/server.py`: registers the read-only `list_accounts(include_closed=false)` tool only when a plan UUID is configured.
- `tests/fixtures.py`: adds a synthetic checking, credit-card, tracking, and closed-account client with the exact brief balances (`1000000`, `-150000`, `200000`, and `50000` milliunits) and private upstream fields.
- `tests/test_accounts.py`: covers signed scope totals, closed-account inclusion, fixed-scale per-account balances, completeness/as-of metadata, scoped read-only registration, setup-mode exclusion, and projection privacy.

## TDD evidence

1. Added the fixture and account tests before creating the tool package.
2. RED command:

   ```text
   UV_CACHE_DIR=/private/tmp/ynab-mcp-phase1-uv-cache uv run pytest tests/test_accounts.py -q
   ```

   Result: collection failed as expected with `ModuleNotFoundError: No module named 'ynab_mcp.tools'`.
3. Added the minimal account projection and scoped registration.
4. GREEN focused command:

   ```text
   UV_CACHE_DIR=/private/tmp/ynab-mcp-phase1-uv-cache uv run pytest tests/test_accounts.py -q
   ```

   Result: `4 passed in 0.45s`.

## Verification

- `UV_CACHE_DIR=/private/tmp/ynab-mcp-phase1-uv-cache uv run pytest -q` — `49 passed in 0.85s`.
- `UV_CACHE_DIR=/private/tmp/ynab-mcp-phase1-uv-cache uv run ruff check src tests` — `All checks passed!`.
- `UV_CACHE_DIR=/private/tmp/ynab-mcp-phase1-uv-cache uv run ruff format --check src tests` — `19 files already formatted`.
- `UV_CACHE_DIR=/private/tmp/ynab-mcp-phase1-uv-cache uv run mypy src` — `Success: no issues found in 10 source files`.
- `git diff --check` — passed with no output.

## Self-review and concerns

The projection exposes only stable account identity/scope fields and formatted cleared, uncleared, and total balances; it does not return raw YNAB metadata, bodies, headers, notes, or other upstream fields. Account and currency shape failures become the sanitized `incomplete_data` error. The server conditional keeps setup mode limited to `list_plans`, and the account tool carries `readOnlyHint=true`.

No Task 5 implementation concerns remain. As with earlier tasks, the verification uses synthetic offline responses and does not assert live API behavior. Repository-wide formatting of pre-existing Markdown plan snippets remains outside the source/test check.
