"""Pure normalization of YNAB transactions into on-budget spending postings."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from ynab_mcp.errors import YnabError


@dataclass(frozen=True, slots=True)
class Posting:
    transaction_id: str
    date: date
    account_id: str
    account_name: str
    category_id: str | None
    category_name: str
    payee_id: str | None
    payee_name: str | None
    milliunits: int


def _text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise YnabError("incomplete_data")
    return value


def _optional_text(row: dict[str, Any], key: str) -> str | None:
    if key not in row:
        raise YnabError("incomplete_data")
    value = row[key]
    if value is not None and not isinstance(value, str):
        raise YnabError("incomplete_data")
    return value


def _bool(row: dict[str, Any], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise YnabError("incomplete_data")
    return value


def eligible_posting(
    tx: dict[str, Any],
    part: dict[str, Any],
    internal_ids: set[str],
    on_budget_ids: set[str],
) -> Posting | None:
    """Return one eligible part, using its amount/category and its parent's account/date."""
    category_id = _optional_text(part, "category_id")
    payee_id = _optional_text(part, "payee_id")
    payee_name = _optional_text(part, "payee_name")
    transfer_account_id = _optional_text(part, "transfer_account_id")
    amount = part.get("amount")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise YnabError("incomplete_data")
    if category_id in internal_ids:
        return None
    if category_id is None:
        if amount >= 0 or transfer_account_id in on_budget_ids:
            return None
        category_name = "Uncategorized"
    else:
        category_name = _text(part, "category_name")
    try:
        posting_date = date.fromisoformat(_text(tx, "date"))
    except ValueError:
        raise YnabError("incomplete_data") from None
    return Posting(
        transaction_id=_text(part, "id"),
        date=posting_date,
        account_id=_text(tx, "account_id"),
        account_name=_text(tx, "account_name"),
        category_id=category_id,
        category_name=category_name,
        payee_id=payee_id,
        payee_name=payee_name,
        milliunits=amount,
    )


def extract_postings(
    transactions: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    categories: list[dict[str, Any]],
) -> list[Posting]:
    """Extract complete, non-duplicated spending postings from raw API records."""
    account_names: dict[str, str] = {}
    on_budget_ids: set[str] = set()
    for account in accounts:
        account_id = _text(account, "id")
        account_names[account_id] = _text(account, "name")
        if _bool(account, "on_budget") and not _bool(account, "deleted"):
            on_budget_ids.add(account_id)

    category_names: dict[str, str] = {}
    internal_ids: set[str] = set()
    for category in categories:
        category_id = _text(category, "id")
        category_names[category_id] = _text(category, "name")
        if _bool(category, "internal"):
            internal_ids.add(category_id)

    postings: list[Posting] = []
    for tx in transactions:
        if _bool(tx, "deleted"):
            continue
        account_id = _text(tx, "account_id")
        if account_id not in account_names:
            raise YnabError("incomplete_data")
        if account_id not in on_budget_ids:
            continue
        parts = tx.get("subtransactions")
        if not isinstance(parts, list) or not all(
            isinstance(part, dict) for part in parts
        ):
            raise YnabError("incomplete_data")
        enriched_tx = {**tx, "account_name": account_names[account_id]}
        for part in parts if parts else [tx]:
            transfer_account_id = _optional_text(part, "transfer_account_id")
            if (
                transfer_account_id is not None
                and transfer_account_id not in account_names
            ):
                raise YnabError("incomplete_data")
            part_category_id = _optional_text(part, "category_id")
            if part_category_id is not None and part_category_id not in category_names:
                raise YnabError("incomplete_data")
            enriched_part = dict(part)
            if part_category_id is not None:
                enriched_part["category_name"] = category_names[part_category_id]
            posting = eligible_posting(
                enriched_tx, enriched_part, internal_ids, on_budget_ids
            )
            if posting is not None:
                postings.append(posting)
    return postings


def merge_month_categories(
    month_data: list[dict[str, Any]], months: list[date]
) -> list[dict[str, Any]]:
    """Retain category identities across months, rejecting conflicting scope flags."""
    categories_by_id: dict[str, dict[str, Any]] = {}
    if len(month_data) != len(months):
        raise YnabError("incomplete_data")
    for data, month in zip(month_data, months, strict=True):
        if data.get("month") != month.isoformat() or data.get("deleted") is not False:
            raise YnabError("incomplete_data")
        categories = data.get("categories")
        if not isinstance(categories, list) or not all(
            isinstance(category, dict) for category in categories
        ):
            raise YnabError("incomplete_data")
        for category in categories:
            category_id = _text(category, "id")
            _text(category, "name")
            internal = _bool(category, "internal")
            previous = categories_by_id.get(category_id)
            if previous is not None and previous["internal"] != internal:
                raise YnabError("incomplete_data")
            categories_by_id[category_id] = category
    return list(categories_by_id.values())
