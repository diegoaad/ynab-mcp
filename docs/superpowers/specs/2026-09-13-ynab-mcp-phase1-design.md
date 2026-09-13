# YNAB MCP Server — Phase 1 Design Spec

**Status:** Proposed for review

**Date:** 2026-09-13

**Scope:** Local, read-only access to one personal YNAB plan through MCP

## 1. Purpose and success criteria

Build a small Python MCP server that lets an assistant answer questions about one personal YNAB plan without giving the server a code path that modifies YNAB. The server runs locally over `stdio`, reads current state from the official YNAB API on demand, and does not persist financial data.

Phase 1 succeeds when an MCP-compatible host can correctly answer these questions with complete, clearly labeled data:

1. How much money do I have across my YNAB accounts?
2. Show my spending by category this month.
3. What did I spend on restaurants over the last three months?
4. Show uncategorized transactions that need attention.
5. Compare this month's spending with last month's.

Correctness takes precedence over returning an answer: if the server cannot process the full requested range within its safety bounds, it reports an incomplete-data error rather than a partial total.

## 2. Decisions and boundaries

| Decision | Phase 1 rule | Reason |
| --- | --- | --- |
| Transport | Local `stdio` only | No listener, remote auth surface, or hosting infrastructure. |
| Credential | `YNAB_PAT` from the process environment | Matches the personal-use brief and avoids an OAuth setup service. |
| Read-only enforcement | Only GET endpoint methods exist in the YNAB client; no write tools are registered; `YNAB_READ_ONLY=false` fails startup | A hidden tool or a tool annotation alone is not an enforcement boundary. |
| Plan scope | `YNAB_PLAN_ID` is a fixed UUID supplied at startup | MCP callers cannot choose another plan or use the moving `last-used` alias. |
| Network | Only `https://api.ynab.com/v1` during server operation | One auditable outbound client. |
| Persistence | No database, disk cache, financial snapshots, or telemetry | Reduces local exposure. |
| Mutations | Out of scope | Requires a separate design and explicit user approval. |

**Credential limitation:** A YNAB Personal Access Token is not itself read-only. Phase 1's non-mutation guarantee applies to this server's code and registered MCP interface; it is not a provider-enforced restriction on a stolen token. YNAB supports a `read-only` OAuth scope that rejects modifying requests. If provider-enforced read-only access becomes a hard requirement, the credential and setup design must be revised before implementation rather than described as a PAT feature.

The fixed plan ID is also an application boundary, not a reduction in the PAT's underlying account permissions. The README must explain both limitations.

## 3. Configuration and installation

Required environment variable, plus the plan ID for normal operation:

```text
YNAB_PAT=<secret>
YNAB_PLAN_ID=<plan UUID>
```

Optional environment variables:

```text
YNAB_READ_ONLY=true
LOG_LEVEL=WARNING
```

`YNAB_READ_ONLY` defaults to `true`. In Phase 1, any other value fails startup. The token must never appear in configuration errors, object representations, logs, stack traces returned to MCP clients, or documentation. Reject missing or blank tokens and malformed plan IDs before starting the MCP transport. Do not accept `default` or `last-used` as a plan ID.

With no `YNAB_PLAN_ID`, the server starts in **setup-only mode**: it exposes `list_plans` and no plan-scoped tools. The user selects a UUID, sets `YNAB_PLAN_ID`, and restarts. When a plan ID is configured, `list_plans` is absent. The server makes no network request merely to start.

The application does not automatically load `.env` in Phase 1. A placeholder-only `.env.example` documents local configuration; `.env` is gitignored for users who choose to load it through their shell. Development and MCP-host examples run the audited checkout from a locked environment. Publishing and `uvx` installation instructions are deferred until a package actually exists; the README must not suggest an unpinned package name that could resolve to unrelated code.

Python 3.12+, `uv`, the current pinned major version of the official MCP Python SDK, and `httpx` are the runtime baseline. Use validation libraries only where they materially reduce code. `pytest`, `ruff`, and one static type checker are development dependencies. Commit `uv.lock` and document a reproducible dependency audit command.

## 4. Architecture and data flow

The implementation has four boundaries:

1. **Configuration and startup:** validates environment, chooses setup-only or scoped mode, creates the client, registers the appropriate tools, and runs `stdio`.
2. **YNAB client:** owns the fixed origin, bearer header, explicit GET routes, request timeouts, response-size checks, API error classification, and JSON validation. MCP input never supplies a URL or raw path.
3. **Normalization and money:** turns the narrow API responses into typed internal records while preserving integer milliunits and the plan currency format. It rejects malformed required fields rather than guessing.
4. **Tools and analysis:** maps validated arguments to client methods and returns concise structured results. Aggregation is pure local logic over complete fetched data.

Do not request the full `/plans/{plan_id}` export for ordinary tools. Use the most specific endpoint that supplies the required data. Do not add a database, generic HTTP proxy, background worker, MCP resources, prompts, sampling, or elicitation in Phase 1.

The client uses HTTPS certificate verification, explicit connect and read timeouts (initially 5 and 30 seconds), `follow_redirects=False`, and `trust_env=False` so environment proxy settings cannot silently change the destination. It accepts only a closed set of known GET route templates and validated path segments. Stream responses and reject bodies above an initial 8 MiB ceiling before parsing. This ceiling is configurable in code, not by MCP callers. Do not retry automatically; in particular, never retry a future mutation by reusing read-path logic.

## 5. API mapping and tool contracts

YNAB's current documented resource name is **plan**. Human-facing tool descriptions may use “budget,” but the client uses `/plans/{plan_id}` and the corresponding `plans` and `plan` response keys.

| MCP tool | Arguments and result | YNAB source |
| --- | --- | --- |
| `list_plans` | Setup-only. IDs and names, no full export. | `GET /plans` |
| `get_budget_summary` | Optional month (default current UTC month). Plan name, currency, month, assigned, activity, Ready to Assign, Age of Money, and `available_in_categories`. | `GET /plans/{id}/months/{month}` and `GET /plans` for the configured plan's name and currency format; discard other plan entries |
| `list_accounts` | `include_closed=false`. Account ID, name, type, `on_budget`, closed status, three balances, plus signed totals for included accounts and separate on-budget/tracking subtotals. | `GET /plans/{id}/accounts` |
| `list_categories` | Month (default current UTC month), `include_hidden=false`. Groups and categories with IDs, assigned, activity, available, and available goal information. | `GET /plans/{id}/months/{month}` |
| `list_transactions` | Required inclusive `since_date` and `until_date`; optional account/category/payee IDs; `limit` defaults to 100 and cannot exceed 500. Returns selected transaction details and an explicit truncation flag. Memo is omitted unless `include_memo=true`. | The most specific documented transaction listing endpoint, with date filters |
| `get_spending_summary` | Required inclusive start/end dates; `group_by` is category, payee, account, or month. Returns complete net-spending groups, range, currency, and exclusions. | Date-bounded transaction listing; local aggregation |
| `get_uncategorized_transactions` | Required inclusive start/end dates; `limit` defaults to 100 and cannot exceed 500. Returns outflows requiring a category and truncation status. | Date-bounded transaction listing followed by local eligibility checks; use `type=uncategorized` only if its split-transaction behavior is verified complete |

`get_category_spending` can be added later if the above tools prove insufficient; it does not need to duplicate `get_spending_summary` in the first release. General payee and scheduled-transaction lists, and a broad `get_month` dump, are likewise deferred because the acceptance questions do not require them. Each additional tool must have a demonstrated use and bounded output.

`available_in_categories` means the signed sum of `balance` for non-deleted, non-internal categories in the selected month, including hidden categories and credit-card payment categories. Ready to Assign is reported separately. This number is **not** labeled “cash available” or equated with the sum of account balances.

All month arguments are `YYYY-MM-01`; invalid calendar dates or other days of month fail validation. “Current month” uses UTC, matching YNAB's documented date convention. Dates in ranges are inclusive. Date ranges cannot exceed 366 days in Phase 1. Financial results identify their as-of time or date range, currency, and whether they are complete. IDs are exact identifiers, never guessed from a name. A host can obtain a category ID from `list_categories`; ambiguous names require user clarification rather than silent selection.

## 6. Financial semantics

All calculations use integer YNAB milliunits. Convert to normal currency units only at the MCP output boundary, serialized as fixed-scale decimal strings plus the plan's ISO currency code. The scale comes from the plan's currency format; do not assume two decimal places. Do not parse YNAB's numeric `..._currency` values through binary floating-point for calculations.

For Phase 1, **net spending** is the negated sum of expense-category postings and uncategorized outflows on on-budget accounts over the requested inclusive range. Negative outflows increase spending; positive refunds assigned to an expense category reduce it. A category grouping places uncategorized outflows in an explicit `Uncategorized` bucket. For a split transaction, aggregate the subtransactions by their category and do not also count the parent amount. Exclude deleted records, pending transactions that the listing API does not return, tracking-account postings, Ready to Assign inflows, and ordinary uncategorized transfers between on-budget accounts. A categorized transfer to a tracking account may count through its on-budget category posting; it must not also count the tracking-side transaction. Where the API response cannot establish these rules reliably, return an explicit incomplete-data error and add a fixture before broadening the claim.

`get_uncategorized_transactions` returns open-account, on-budget outflows with no category that are not ordinary account transfers. It does not claim that every transaction lacking a category needs user action.

A calendar-month spending bucket is labeled as complete or month-to-date. If the host compares the current month with the previous full month, it must disclose that unequal coverage. Documentation should show an equal-days month-to-date comparison for a like-for-like answer, clamping the prior month end when necessary.

## 7. Bounds, rate limits, and failures

YNAB documents `since_date` and `until_date` filters and delta requests for transaction listings, but no native page or row limit. `limit` therefore caps MCP output **after** the API response has been processed. A truncated transaction list carries `truncated=true`; an aggregate is never computed from a deliberately truncated list. If the required response exceeds the byte ceiling, the tool returns a named incomplete-data error with guidance to narrow the dates.

Delta `last_knowledge_of_server` is change tracking, not pagination. Because Phase 1 has no persistent cache, it does not expose or use a delta cursor. It may be added with a carefully specified in-memory cache later. Omitted transaction `since_date` is not allowed because YNAB currently defaults it to one year ago, which could silently omit older history.

The token has a 200-requests-per-rolling-hour YNAB limit. Avoid duplicate requests within a single tool call. On 429, return a rate-limit classification without inventing a reset time; do not rely on a rate-limit header being present. Map 400, 401, 403, 404, 409, 429, 500, 503, timeout, oversized body, and malformed response to stable, sanitized MCP errors. Never return raw `httpx` exception strings or YNAB response bodies to the host. Retain only safe diagnostics such as status, classification, and tool name.

## 8. Security and privacy contract

`stdout` is reserved for MCP protocol messages. Conservative logs go to `stderr` and may contain startup, tool name, duration, HTTP status, and error class. They must not contain the PAT, request/response bodies, URL query values, account balances, transaction details, payee names, memos, or user-controlled arguments. Debug mode does not enable body or header logging.

Tool results cross a second trust boundary: the MCP host receives financial data and may transmit it to a remote model or store it in its own history. “No local persistence” applies to this server, not to every host. The README must explain that boundary and advise using a host whose data-handling policy the user accepts. Payee names, category names, and memos are untrusted data; tool descriptions must not imply that text found in YNAB can instruct the assistant.

All read tools carry MCP `readOnlyHint=true` annotations for client UX, but the GET-only client and absence of write registrations enforce Phase 1 behavior. The server must not call arbitrary URLs, honor redirects, emit telemetry, or support client-supplied origins. Do not include an HTTP server.

## 9. Verification and acceptance

Use synthetic fixtures and a mocked YNAB transport; tests never need a real PAT or personal financial data. The minimum suite covers:

- Credential redaction in normal output, validation, HTTP errors, logs, and exception representations.
- Fixed-origin and fixed-plan routing, invalid IDs, no caller-controlled URLs, disabled proxy/redirect behavior, and GET-only requests.
- MCP `tools/list` in setup-only and configured modes, including absence of every write name and failure of manually invoked write calls.
- Exact milliunit conversion for positive and negative amounts and currencies with two and three decimal digits.
- Current versus historical month category data, hidden/deleted/internal handling, account subtotal labels, and Ready to Assign separation.
- Split transactions, refunds, on-budget transfers, tracking accounts, categorized tracking transfers, uncategorized eligibility, and partial-month labels.
- Date validation, 366-day bound, 500-row output cap, truncation metadata, oversized responses, and refusal to issue partial aggregate totals.
- All named API errors, timeout, malformed JSON/schema, 429 handling, and no automatic startup request.
- A protocol-level smoke test using the pinned MCP SDK client over `stdio`, not only direct Python function tests.

Before claiming Phase 1 complete, run tests, lint, format check, type check, dependency audit, and a secret scan of tracked files. Use mocked or disposable data for the MCP host smoke test. A live personal-account check is optional and must not be required by CI. Record the commands and any documented exceptions in the milestone report.

## 10. Delivery sequence

1. **Foundation:** package and lockfile, config, GET-only client, error model, money conversion, `stdio` startup, setup-only `list_plans`, and protocol smoke test.
2. **Core reads:** scoped summary, accounts, month categories, and bounded transactions.
3. **Analysis:** spending summary and uncategorized transactions, with edge-case fixtures and the five acceptance questions.
4. **Hardening:** response-size enforcement, redaction tests, dependency audit, documentation, and complete verification.

Each milestone ends with changed files, tests, verification commands, remaining limits, and the next step. Phase 2 starts only after separate user approval and its own design. In particular, moving money between categories is not atomic through the currently documented API, and transaction updates have field-specific restrictions; pre/post verification alone does not make those operations safe.

## 11. Source of API and protocol facts

- [YNAB API documentation, authentication, data formats, rate limit, and changelog](https://api.ynab.com/)
- [YNAB v1 endpoint reference](https://api.ynab.com/v1)
- [Official MCP Python SDK v2 documentation](https://py.sdk.modelcontextprotocol.io/)
- [MCP tool annotations and schemas](https://modelcontextprotocol.io/specification/2025-11-25/schema)

Endpoint and SDK assumptions must be checked against these sources again when implementation begins.
