# Phase 1 final-review fix wave — 2026-09-13

## Changed files

- `src/ynab_mcp/dates.py`: public range dates now require canonical `YYYY-MM-DD`.
- `src/ynab_mcp/money.py`: integer-only fixed-scale conversion; sign is applied before formatting the absolute quotient and remainder.
- `src/ynab_mcp/server.py`: validation `ValueError` becomes sanitized MCP `ToolError("bad_request")` without retaining the caller argument as an exception cause.
- `src/ynab_mcp/tools/transactions.py`: parent or child payee/category IDs match; payee/category filters fetch the complete date-bounded plan transaction listing and filter locally. Account-only queries retain the account route.
- `src/ynab_mcp/tools/spending.py`: complete spending results carry stable exclusions metadata.
- `tests/test_dates.py`, `tests/test_money.py`, `tests/test_privacy.py`, `tests/test_spending.py`, `tests/test_transactions.py`: regression coverage for all five findings.

## RED/GREEN and verification evidence

All commands ran from `/Users/diegoduarte/code/ynab-mcp/.worktrees/codex/ynab-mcp-phase1`.

1. `UV_CACHE_DIR=/private/tmp/ynab-uv-cache uv run --offline pytest -q tests/test_dates.py tests/test_money.py tests/test_spending.py tests/test_transactions.py tests/test_privacy.py` before production edits: **12 failed, 34 passed**. Expected failures demonstrated noncanonical range acceptance, Decimal-context rounding, absent exclusions, narrow routes/child payee miss, and invalid-argument traceback leakage. First attempt without `UV_CACHE_DIR` could not initialize `/Users/diegoduarte/.cache/uv` under the sandbox and did not run tests.
2. The same focused command after implementation: **1 failed, 45 passed**. The remaining failure expected `bad_request` for an invalid `limit`; SDK Pydantic validation handles that before the tool function and emits a sanitized `greater_than_equal` error while logging only `['limit']`. The test was corrected to assert that existing boundary behavior.
3. `UV_CACHE_DIR=/private/tmp/ynab-uv-cache uv run --offline ruff format .`: 4 files reformatted, 29 unchanged.
4. `UV_CACHE_DIR=/private/tmp/ynab-uv-cache uv run --offline pytest -q tests/test_dates.py tests/test_money.py tests/test_spending.py tests/test_transactions.py tests/test_privacy.py`: **46 passed**.
5. `UV_CACHE_DIR=/private/tmp/ynab-uv-cache uv run --offline pytest -q`: **108 passed**. First lint pass found one test import ordering issue.
6. `UV_CACHE_DIR=/private/tmp/ynab-uv-cache uv run --offline ruff check --fix tests/test_money.py`: one import issue fixed.
7. `UV_CACHE_DIR=/private/tmp/ynab-uv-cache uv run --offline ruff format .`: 33 files unchanged.
8. `UV_CACHE_DIR=/private/tmp/ynab-uv-cache uv run --offline pytest -q`: **108 passed**.
9. `UV_CACHE_DIR=/private/tmp/ynab-uv-cache uv run --offline ruff check .`: **all checks passed**.
10. `UV_CACHE_DIR=/private/tmp/ynab-uv-cache uv run --offline ruff format --check .`: **33 files already formatted**.
11. `UV_CACHE_DIR=/private/tmp/ynab-uv-cache uv run --offline mypy src`: **no issues in 14 source files**.
12. `UV_CACHE_DIR=/private/tmp/ynab-uv-cache uv run --offline --frozen pytest -q tests/test_stdio.py`: **1 passed**, real subprocess stdio protocol smoke with synthetic credentials.
13. `UV_CACHE_DIR=/private/tmp/ynab-uv-cache uv run --offline --frozen pip-audit`: could not create its default cache under sandbox. Retried with `--cache-dir /private/tmp/ynab-pip-audit-cache`; DNS blocked by sandbox. Final command outside sandbox: `UV_CACHE_DIR=/private/tmp/ynab-uv-cache PIP_CACHE_DIR=/private/tmp/ynab-pip-cache uv run --offline --frozen pip-audit --cache-dir /private/tmp/ynab-pip-audit-cache`: **No known vulnerabilities found**.
14. `git diff --check`: clean.
15. `git ls-files` review: no tracked `.env`, database, private key, virtual environment, or cache paths. A scripted scan of 39 tracked files for non-placeholder `YNAB_PAT=` assignments found **0 suspicious assignments**.

## Self-review and concerns

The requested five findings are covered by failing-before/green-after regressions. Numeric aggregate totals are still returned only after all required data is fetched and validated. No new MCP tools, write methods, origins, persistence, personal data, or live PAT were added. The category/payee plan route can increase response size; an oversized body remains `incomplete_data` by the existing client limit. The SDK's invalid-limit classification differs from the tool's `bad_request` classification because schema validation runs before dispatch; it remains sanitized and enforces 1–500. No unresolved concern blocks this wave.
