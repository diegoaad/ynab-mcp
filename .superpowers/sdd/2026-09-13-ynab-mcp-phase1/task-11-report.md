# Task 11 milestone — Phase 1 privacy and release gate

Status: complete after the checks below, using only synthetic fixtures and a fake PAT. No live YNAB account was used.

## Implemented

- Added MCP-boundary privacy regressions for a fake PAT embedded in an upstream 401 body, instruction-like payee/memo text kept as structured data, offline startup, and GET-only requests to `https://api.ynab.com`.
- Mapped deliberate `YnabError` classifications to the MCP SDK's `ToolError`, exposing a stable sanitized code such as `unauthorized` without an unexpected-exception traceback. The raw body and PAT remain absent from host results and captured logs.
- Removed the parsed-but-ignored `LOG_LEVEL` setting. Startup now rejects it explicitly; logging remains fixed at `WARNING`. Updated configuration tests, `.env.example`, and the binding spec.
- Wrote the README with frozen checkout setup, setup-only plan discovery, host configuration, PAT revocation, server-only read restrictions, host/model exposure, no persistence, financial labels, UTC dates, limits, month-to-date comparisons, and the `available_in_categories` credit-card-payment caveat.
- Formatted only the existing Python code fences in the committed plan Markdown and the new test so repository-wide `ruff format --check .` passes transparently.

Changed files: `README.md`, `.env.example`, `src/ynab_mcp/config.py`, `src/ynab_mcp/server.py`, `tests/test_config.py`, `tests/test_privacy.py`, `docs/superpowers/specs/2026-09-13-ynab-mcp-phase1-design.md`, and formatting-only changes to `docs/superpowers/plans/2026-09-13-ynab-mcp-phase1.md`.

## RED / GREEN

- Initial privacy/config run: 3 expected failures — missing `<secret>` placeholder, generic MCP error instead of a stable classification, and ignored `LOG_LEVEL`. Other new boundary checks passed.
- After the placeholder/config change: `12 passed` in the focused privacy/config run.
- The classification regression was rerun before the MCP adapter change and failed as expected: the host saw only `Error executing tool list_accounts`, and the SDK logged an unexpected exception.
- After the adapter change: `4 passed` in `tests/test_privacy.py`; final complete suite: `98 passed`.

## Final verification

Commands were run from this worktree. `UV_CACHE_DIR=/private/tmp/ynab-mcp-uv-cache` was used because the default user cache is outside the writable sandbox.

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/private/tmp/ynab-mcp-uv-cache uv sync --frozen` | Exit 0; checked 67 packages. |
| `UV_CACHE_DIR=/private/tmp/ynab-mcp-uv-cache uv run --frozen pytest -q` | Exit 0; 98 passed in 1.27s. |
| `UV_CACHE_DIR=/private/tmp/ynab-mcp-uv-cache uv run --frozen ruff check .` | Exit 0; all checks passed. |
| `UV_CACHE_DIR=/private/tmp/ynab-mcp-uv-cache uv run --frozen ruff format --check .` | Exit 0; 33 files already formatted, including the plan Markdown. |
| `UV_CACHE_DIR=/private/tmp/ynab-mcp-uv-cache uv run --frozen mypy src` | Exit 0; no issues in 14 source files. |
| `UV_CACHE_DIR=/private/tmp/ynab-mcp-uv-cache uv run --frozen pip-audit --cache-dir /private/tmp/ynab-mcp-pip-audit-cache` | Exit 0 outside the restricted network sandbox; no known vulnerabilities found. Initial sandbox-only attempts failed on cache permissions, then PyPI DNS, so those were not treated as audit results. |
| `UV_CACHE_DIR=/private/tmp/ynab-mcp-uv-cache uv run --frozen pytest -q tests/test_stdio.py` | Exit 0; 1 protocol-level subprocess smoke test passed with a fake PAT. |
| `git diff --check` | Exit 0; no whitespace errors. |
| `git status --short` | Reviewed before staging; only the intended Task 11 files were modified or added. |
| `git ls-files` and tracked-file path/token scan | Reviewed tracked paths for local env files, databases, caches, keys, and token-shaped values; no unexpected paths or credential-shaped values found. Synthetic `sentinel-secret` fixtures are intentional. |

## Remaining risks and next step

- A PAT is not provider-enforced read-only; a stolen token retains its YNAB permissions. The fixed-plan and GET-only restrictions apply only to this server.
- Internal credit-card-payment category balances may be absent from `available_in_categories` because the documented schema lacks a stable discriminator. The README and result scope disclose this.
- The response-size ceiling and 366-day range can reject large requests; aggregates do not return partial totals. The HTTP read timeout is per operation, not a wall-clock deadline.
- Deferred minor ledger items outside this release/privacy scope remain: huge-integer Decimal-context formatting, optional date-input strictness at internal client methods, and a few fixture/helper coverage or naming cleanups. None was broadened into feature work here.

Next step: parent controller review and Phase 1 integration. No Phase 2 write capability is included.
