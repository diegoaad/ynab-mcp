"""Bounded, locally filtered transaction details for one configured plan."""

from datetime import date
from typing import Any
from uuid import UUID

from ynab_mcp.client import YnabClient
from ynab_mcp.dates import parse_window
from ynab_mcp.errors import YnabError
from ynab_mcp.money import CurrencyFormat, format_milliunits
from ynab_mcp.tools.accounts import currency_from_plan


def validate_optional_uuids(
    account_id: str | None, category_id: str | None, payee_id: str | None
) -> dict[str, UUID | None]:
    ids: dict[str, UUID | None] = {}
    for name, value in (
        ("account_id", account_id),
        ("category_id", category_id),
        ("payee_id", payee_id),
    ):
        if value is None:
            ids[name] = None
            continue
        try:
            ids[name] = UUID(value)
        except (TypeError, ValueError, AttributeError):
            raise ValueError(f"{name} must be a UUID") from None
    return ids


def _subtransactions(row: dict[str, Any]) -> list[dict[str, Any]]:
    value = row.get("subtransactions", [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise YnabError("incomplete_data")
    return value


def filter_and_sort_transactions(
    rows: list[dict[str, Any]],
    ids: dict[str, UUID | None],
    start: date | None = None,
    end: date | None = None,
) -> list[dict[str, Any]]:
    """Apply all requested IDs and local dates to a complete API listing."""
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row.get("deleted"), bool):
            raise YnabError("incomplete_data")
        if row["deleted"]:
            continue
        row_id, row_date = row.get("id"), row.get("date")
        if not isinstance(row_id, str) or not isinstance(row_date, str):
            raise YnabError("incomplete_data")
        try:
            parsed_date = date.fromisoformat(row_date)
        except ValueError:
            raise YnabError("incomplete_data") from None
        if (start is not None and parsed_date < start) or (
            end is not None and parsed_date > end
        ):
            continue
        account_id = ids.get("account_id")
        if account_id is not None and row.get("account_id") != str(account_id):
            continue
        payee_id = ids.get("payee_id")
        if (
            payee_id is not None
            and row.get("payee_id") != str(payee_id)
            and not any(
                part.get("payee_id") == str(payee_id) for part in _subtransactions(row)
            )
        ):
            continue
        category_id = ids.get("category_id")
        if (
            category_id is not None
            and row.get("category_id") != str(category_id)
            and not any(
                part.get("category_id") == str(category_id)
                for part in _subtransactions(row)
            )
        ):
            continue
        filtered.append(row)
    return sorted(
        filtered,
        key=lambda row: (-date.fromisoformat(row["date"]).toordinal(), row["id"]),
    )


def _optional_text(row: dict[str, Any], name: str) -> str | None:
    value = row.get(name)
    if value is not None and not isinstance(value, str):
        raise YnabError("incomplete_data")
    return value


def _amount(row: dict[str, Any], currency: CurrencyFormat) -> str:
    value = row.get("amount")
    if not isinstance(value, int) or isinstance(value, bool):
        raise YnabError("incomplete_data")
    try:
        return format_milliunits(value, currency)
    except ValueError:
        raise YnabError("incomplete_data") from None


def _project_subtransaction(
    row: dict[str, Any], currency: CurrencyFormat, include_memo: bool
) -> dict[str, object]:
    result: dict[str, object] = {
        "id": _optional_text(row, "id"),
        "amount": _amount(row, currency),
        "category_id": _optional_text(row, "category_id"),
        "category_name": _optional_text(row, "category_name"),
        "payee_id": _optional_text(row, "payee_id"),
        "payee_name": _optional_text(row, "payee_name"),
    }
    if include_memo:
        result["memo"] = _optional_text(row, "memo")
    return result


def transaction_result(
    rows: list[dict[str, Any]],
    *,
    truncated: bool,
    include_memo: bool,
    start: date,
    end: date,
    currency: CurrencyFormat,
) -> dict[str, object]:
    """Project a bounded list without leaking upstream fields."""
    transactions: list[dict[str, object]] = []
    for row in rows:
        row_id, row_date = row.get("id"), row.get("date")
        if not isinstance(row_id, str) or not isinstance(row_date, str):
            raise YnabError("incomplete_data")
        cleared = _optional_text(row, "cleared")
        approved = row.get("approved")
        if not isinstance(approved, bool):
            raise YnabError("incomplete_data")
        item: dict[str, object] = {
            "id": row_id,
            "date": row_date,
            "amount": _amount(row, currency),
            "account_id": _optional_text(row, "account_id"),
            "account_name": _optional_text(row, "account_name"),
            "category_id": _optional_text(row, "category_id"),
            "category_name": _optional_text(row, "category_name"),
            "payee_id": _optional_text(row, "payee_id"),
            "payee_name": _optional_text(row, "payee_name"),
            "cleared": cleared,
            "approved": approved,
            "transfer_account_id": _optional_text(row, "transfer_account_id"),
            "subtransactions": [
                _project_subtransaction(part, currency, include_memo)
                for part in _subtransactions(row)
            ],
        }
        if include_memo:
            item["memo"] = _optional_text(row, "memo")
        transactions.append(item)
    return {
        "currency": currency.iso_code,
        "since_date": start.isoformat(),
        "until_date": end.isoformat(),
        "transactions": transactions,
        "truncated": truncated,
        "complete": not truncated,
    }


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
    """Return at most ``limit`` transactions from a complete date-bounded listing."""
    start, end = parse_window(since_date, until_date)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("limit must be 1 through 500")
    ids = validate_optional_uuids(account_id, category_id, payee_id)
    # Category and payee routes may omit a split parent whose child matches.
    route_account = (
        ids["account_id"] if not (ids["category_id"] or ids["payee_id"]) else None
    )
    rows = await client.get_transactions(start, end, account_id=route_account)
    filtered = filter_and_sort_transactions(rows, ids, start, end)
    currency = currency_from_plan(await client.get_plan_metadata())
    return transaction_result(
        filtered[:limit],
        truncated=len(filtered) > limit,
        include_memo=include_memo,
        start=start,
        end=end,
        currency=currency,
    )


def actionable_uncategorized(
    transactions: list[dict[str, Any]], accounts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Flatten actionable uncategorized outflows, retaining parent context."""
    accounts_by_id: dict[str, dict[str, Any]] = {}
    for account in accounts:
        account_id = account.get("id")
        if not isinstance(account_id, str) or not account_id:
            raise YnabError("incomplete_data")
        if any(
            not isinstance(account.get(flag), bool)
            for flag in ("on_budget", "closed", "deleted")
        ):
            raise YnabError("incomplete_data")
        accounts_by_id[account_id] = account

    eligible: list[dict[str, Any]] = []
    for tx in transactions:
        if not isinstance(tx.get("deleted"), bool):
            raise YnabError("incomplete_data")
        if tx["deleted"]:
            continue
        account_id = tx.get("account_id")
        if not isinstance(account_id, str) or account_id not in accounts_by_id:
            raise YnabError("incomplete_data")
        account = accounts_by_id[account_id]
        if not account["on_budget"] or account["closed"] or account["deleted"]:
            continue

        parts = _subtransactions(tx)
        for part in parts if parts else [tx]:
            amount = part.get("amount")
            if not isinstance(amount, int) or isinstance(amount, bool):
                raise YnabError("incomplete_data")
            category_id = _optional_text(part, "category_id")
            transfer_id = _optional_text(part, "transfer_account_id")
            if transfer_id is not None and transfer_id not in accounts_by_id:
                raise YnabError("incomplete_data")
            if amount >= 0 or category_id is not None:
                continue
            if transfer_id is not None and accounts_by_id[transfer_id]["on_budget"]:
                continue
            if parts:
                part_id = part.get("id")
                if not isinstance(part_id, str):
                    raise YnabError("incomplete_data")
                eligible.append(
                    {
                        **tx,
                        **part,
                        "id": part_id,
                        "date": tx["date"],
                        "account_id": account_id,
                        "account_name": tx.get("account_name"),
                        "amount": amount,
                        "category_id": None,
                        "category_name": None,
                        "subtransactions": [],
                    }
                )
            else:
                eligible.append(tx)
    return eligible


async def uncategorized_transactions(
    client: YnabClient, since_date: str, until_date: str, limit: int = 100
) -> dict[str, object]:
    """Return bounded uncategorized outflows from open on-budget accounts."""
    start, end = parse_window(since_date, until_date)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("limit must be 1 through 500")
    transactions = await client.get_transactions(start, end)
    accounts = await client.get_accounts()
    filtered = filter_and_sort_transactions(transactions, {}, start, end)
    eligible = actionable_uncategorized(filtered, accounts)
    currency = currency_from_plan(await client.get_plan_metadata())
    return transaction_result(
        eligible[:limit],
        truncated=len(eligible) > limit,
        include_memo=False,
        start=start,
        end=end,
        currency=currency,
    )
