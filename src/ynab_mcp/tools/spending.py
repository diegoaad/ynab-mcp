"""Complete, integer-based spending summaries for inclusive date windows."""

from calendar import monthrange
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any, Literal

from ynab_mcp.analysis import Posting, extract_postings, merge_month_categories
from ynab_mcp.client import YnabClient
from ynab_mcp.dates import parse_window
from ynab_mcp.errors import YnabError
from ynab_mcp.money import format_milliunits
from ynab_mcp.tools.accounts import currency_from_plan

GroupBy = Literal["category", "payee", "account", "month"]


def months_between(start: date, end: date) -> list[date]:
    """List first days of every month touched by an inclusive range."""
    if start > end:
        raise ValueError("start must precede end")
    months: list[date] = []
    current = start.replace(day=1)
    while current <= end:
        months.append(current)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return months


def _month_coverage(month: date, start: date, end: date, today: date) -> str:
    last_day = date(month.year, month.month, monthrange(month.year, month.month)[1])
    covered_start = max(start, month)
    covered_end = min(end, last_day)
    if covered_start == month and covered_end == last_day:
        return "full_month"
    if (
        month == today.replace(day=1)
        and covered_start == month
        and covered_end == today
    ):
        return "month_to_date"
    return "partial_month"


def aggregate_postings(
    postings: list[Posting],
    group_by: GroupBy,
    start: date,
    end: date,
    *,
    today: date,
) -> dict[str, dict[str, int | str]]:
    """Sum signed posting milliunits, then negate for net spending."""
    if group_by not in ("category", "payee", "account", "month"):
        raise ValueError("unsupported grouping")
    if start > end:
        raise ValueError("start must precede end")

    if group_by == "month":
        monthly_amounts = {
            month.strftime("%Y-%m"): 0 for month in months_between(start, end)
        }
        for posting in postings:
            if start <= posting.date <= end:
                monthly_amounts[posting.date.strftime("%Y-%m")] -= posting.milliunits
        return {
            month.strftime("%Y-%m"): {
                "milliunits": monthly_amounts[month.strftime("%Y-%m")],
                "coverage": _month_coverage(month, start, end, today),
            }
            for month in months_between(start, end)
        }

    amounts_by_key: dict[tuple[str, str], int] = defaultdict(int)
    names_by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    for posting in postings:
        if not start <= posting.date <= end:
            continue
        if group_by == "category":
            identifier, name = posting.category_id, posting.category_name
            unnamed = False
        elif group_by == "payee":
            raw_name = posting.payee_name
            unnamed = raw_name is None or not raw_name.strip()
            identifier = posting.payee_id
            name = (
                raw_name
                if raw_name is not None and raw_name.strip()
                else "Unknown payee"
            )
        else:
            identifier, name = posting.account_id, posting.account_name
            unnamed = False
        if identifier is not None:
            key = ("id", identifier)
        elif unnamed:
            key = ("unknown", "")
        else:
            key = ("name", name)
        amounts_by_key[key] -= posting.milliunits
        names_by_key[key].add(name)

    name_counts: dict[str, int] = defaultdict(int)
    display_names = {key: min(names) for key, names in names_by_key.items()}
    for name in display_names.values():
        name_counts[name] += 1
    groups: dict[str, dict[str, int | str]] = {}
    for key, total in amounts_by_key.items():
        name = display_names[key]
        if key[0] == "id":
            qualifier = key[1]
        elif key[0] == "name":
            qualifier = "name-only"
        else:
            qualifier = "unnamed"
        label = name if name_counts[name] == 1 else f"{name} [{qualifier}]"
        if label in groups:
            raise YnabError("incomplete_data")
        groups[label] = {"milliunits": total, "coverage": "selected_range"}
    return groups


def spending_result(
    totals: dict[str, dict[str, int | str]],
    metadata: dict[str, Any],
    start: date,
    end: date,
    complete: bool,
) -> dict[str, object]:
    """Format only complete numeric totals using the plan's currency scale."""
    if not complete:
        raise YnabError("incomplete_data")
    currency = currency_from_plan(metadata)
    groups: dict[str, str] = {}
    coverage: dict[str, str] = {}
    for label, bucket in totals.items():
        amount = bucket.get("milliunits")
        bucket_coverage = bucket.get("coverage")
        if (
            not isinstance(amount, int)
            or isinstance(amount, bool)
            or not isinstance(bucket_coverage, str)
        ):
            raise YnabError("incomplete_data")
        try:
            groups[label] = format_milliunits(amount, currency)
        except ValueError:
            raise YnabError("incomplete_data") from None
        coverage[label] = bucket_coverage
    return {
        "currency": currency.iso_code,
        "since_date": start.isoformat(),
        "until_date": end.isoformat(),
        "groups": groups,
        "coverage": coverage,
        "as_of_utc": datetime.now(UTC).isoformat(),
        "complete": True,
    }


async def spending_summary(
    client: YnabClient, start_date: str, end_date: str, group_by: GroupBy
) -> dict[str, object]:
    """Fetch every required response before producing any formatted total."""
    start, end = parse_window(start_date, end_date)
    transactions = await client.get_transactions(start, end)
    accounts = await client.get_accounts()
    metadata = await client.get_plan_metadata()
    months = months_between(start, end)
    month_data = [await client.get_month(month) for month in months]
    categories = merge_month_categories(month_data, months)
    postings = extract_postings(transactions, accounts, categories)
    totals = aggregate_postings(
        postings, group_by, start, end, today=datetime.now(UTC).date()
    )
    return spending_result(totals, metadata, start, end, complete=True)
