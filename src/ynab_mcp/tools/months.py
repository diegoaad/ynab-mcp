"""Bounded projections of one configured YNAB plan month."""

from datetime import UTC, date, datetime
from typing import Any

from ynab_mcp.client import YnabClient
from ynab_mcp.dates import parse_month
from ynab_mcp.errors import YnabError
from ynab_mcp.money import CurrencyFormat, format_milliunits
from ynab_mcp.tools.accounts import currency_from_plan

_AVAILABLE_SCOPE = (
    "signed balances of non-deleted, non-internal categories, including hidden; "
    "internal credit-card-payment category balances may be excluded"
)


def _money(value: object, currency: CurrencyFormat) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        raise YnabError("incomplete_data")
    try:
        return format_milliunits(value, currency)
    except ValueError:
        raise YnabError("incomplete_data") from None


def _month_categories(data: dict[str, Any], month: date) -> list[dict[str, Any]]:
    if data.get("month") != month.isoformat() or data.get("deleted") is not False:
        raise YnabError("incomplete_data")
    categories = data.get("categories")
    if not isinstance(categories, list) or not all(
        isinstance(category, dict) for category in categories
    ):
        raise YnabError("incomplete_data")
    for category in categories:
        if (
            any(
                not isinstance(category.get(field), str)
                for field in ("id", "name", "category_group_id")
            )
            or any(
                not isinstance(category.get(field), bool)
                for field in ("hidden", "internal", "deleted")
            )
            or any(
                not isinstance(category.get(field), int)
                or isinstance(category.get(field), bool)
                for field in ("budgeted", "activity", "balance")
            )
        ):
            raise YnabError("incomplete_data")
        group_name = category.get("category_group_name")
        if group_name is not None and not isinstance(group_name, str):
            raise YnabError("incomplete_data")
    return categories


def month_summary_result(
    metadata: dict[str, Any], data: dict[str, Any], month: date, available: int
) -> dict[str, object]:
    """Format a validated month without exposing the raw API response."""
    name = metadata.get("name")
    if not isinstance(name, str):
        raise YnabError("incomplete_data")
    currency = currency_from_plan(metadata)
    age = data.get("age_of_money")
    if age is not None and (not isinstance(age, int) or isinstance(age, bool)):
        raise YnabError("incomplete_data")
    return {
        "plan_name": name,
        "currency": currency.iso_code,
        "month": month.isoformat(),
        "assigned": _money(data.get("budgeted"), currency),
        "activity": _money(data.get("activity"), currency),
        "ready_to_assign": _money(data.get("to_be_budgeted"), currency),
        "age_of_money": age,
        "available_in_categories": _money(available, currency),
        "available_in_categories_scope": _AVAILABLE_SCOPE,
        "as_of_utc": datetime.now(UTC).isoformat(),
        "complete": True,
    }


async def budget_summary(
    client: YnabClient, month: str | None = None
) -> dict[str, object]:
    """Return one month's assigned, activity, Ready to Assign, and scoped available."""
    selected = parse_month(month)
    metadata, data = await client.get_plan_metadata(), await client.get_month(selected)
    categories = _month_categories(data, selected)
    available = sum(
        category["balance"]
        for category in categories
        if not category["deleted"] and not category["internal"]
    )
    return month_summary_result(metadata, data, selected, available)


def _optional_money(
    category: dict[str, Any], field: str, currency: CurrencyFormat
) -> str | None:
    value = category.get(field)
    return None if value is None else _money(value, currency)


async def category_list(
    client: YnabClient, month: str | None = None, include_hidden: bool = False
) -> dict[str, object]:
    """List IDs and month-specific amounts for non-deleted categories."""
    selected = parse_month(month)
    metadata, data = await client.get_plan_metadata(), await client.get_month(selected)
    currency = currency_from_plan(metadata)
    categories = _month_categories(data, selected)
    groups: list[dict[str, object]] = []
    group_ids: set[str] = set()
    rows: list[dict[str, object]] = []
    for category in categories:
        if category["deleted"] or (category["hidden"] and not include_hidden):
            continue
        group_id = category["category_group_id"]
        group_name = category.get("category_group_name")
        if group_id not in group_ids:
            groups.append({"id": group_id, "name": group_name})
            group_ids.add(group_id)
        goal_type = category.get("goal_type")
        goal_target_date = category.get("goal_target_date")
        if (goal_type is not None and not isinstance(goal_type, str)) or (
            goal_target_date is not None and not isinstance(goal_target_date, str)
        ):
            raise YnabError("incomplete_data")
        rows.append(
            {
                "id": category["id"],
                "group_id": group_id,
                "group_name": group_name,
                "name": category["name"],
                "hidden": category["hidden"],
                "internal": category["internal"],
                "assigned": _money(category["budgeted"], currency),
                "activity": _money(category["activity"], currency),
                "available": _money(category["balance"], currency),
                "goal_type": goal_type,
                "goal_target": _optional_money(category, "goal_target", currency),
                "goal_target_date": goal_target_date,
                "goal_under_funded": _optional_money(
                    category, "goal_under_funded", currency
                ),
            }
        )
    return {
        "currency": currency.iso_code,
        "month": selected.isoformat(),
        "groups": groups,
        "categories": rows,
        "as_of_utc": datetime.now(UTC).isoformat(),
        "complete": True,
    }
