"""Account balance projections for a configured YNAB plan."""

from datetime import UTC, datetime
from typing import Any

from ynab_mcp.client import YnabClient
from ynab_mcp.errors import YnabError
from ynab_mcp.money import CurrencyFormat, format_milliunits

_TOTALS_BASIS = "signed net account balances; not spendable cash"


def currency_from_plan(metadata: dict[str, Any]) -> CurrencyFormat:
    """Extract and validate the configured plan's currency format."""
    currency_data = metadata.get("currency_format")
    if not isinstance(currency_data, dict):
        raise YnabError("incomplete_data")

    iso_code = currency_data.get("iso_code")
    decimal_digits = currency_data.get("decimal_digits")
    if (
        not isinstance(iso_code, str)
        or not iso_code
        or not isinstance(decimal_digits, int)
        or isinstance(decimal_digits, bool)
    ):
        raise YnabError("incomplete_data")
    return CurrencyFormat(iso_code, decimal_digits)


def _validate_account(account: dict[str, Any]) -> None:
    required_text = ("id", "name", "type")
    if any(not isinstance(account.get(key), str) for key in required_text):
        raise YnabError("incomplete_data")
    required_flags = ("on_budget", "closed", "deleted")
    if any(not isinstance(account.get(key), bool) for key in required_flags):
        raise YnabError("incomplete_data")
    required_balances = ("cleared_balance", "uncleared_balance", "balance")
    if any(
        not isinstance(account.get(key), int) or isinstance(account.get(key), bool)
        for key in required_balances
    ):
        raise YnabError("incomplete_data")


def _format_balance(value: int, currency: CurrencyFormat) -> str:
    try:
        return format_milliunits(value, currency)
    except ValueError:
        raise YnabError("incomplete_data") from None


def account_result(
    accounts: list[dict[str, Any]],
    on_budget: int,
    tracking: int,
    currency: CurrencyFormat,
) -> dict[str, object]:
    """Project signed totals and accounts into safe MCP data.

    ``all_included`` is a signed net balance across the selected scopes, not
    spendable cash.
    """
    if (
        not isinstance(on_budget, int)
        or isinstance(on_budget, bool)
        or not isinstance(tracking, int)
        or isinstance(tracking, bool)
    ):
        raise YnabError("incomplete_data")

    projected_accounts: list[dict[str, object]] = []
    for account in accounts:
        _validate_account(account)
        projected_accounts.append(
            {
                "id": account["id"],
                "name": account["name"],
                "type": account["type"],
                "on_budget": account["on_budget"],
                "closed": account["closed"],
                "cleared_balance": _format_balance(
                    account["cleared_balance"], currency
                ),
                "uncleared_balance": _format_balance(
                    account["uncleared_balance"], currency
                ),
                "balance": _format_balance(account["balance"], currency),
            }
        )

    return {
        "currency": currency.iso_code,
        "totals": {
            "on_budget": _format_balance(on_budget, currency),
            "tracking": _format_balance(tracking, currency),
            # This is a signed net balance across selected account scopes.
            "all_included": _format_balance(on_budget + tracking, currency),
        },
        "totals_basis": _TOTALS_BASIS,
        "accounts": projected_accounts,
        "as_of_utc": datetime.now(UTC).isoformat(),
        "complete": True,
    }


async def account_list(
    client: YnabClient, include_closed: bool = False
) -> dict[str, object]:
    """Return signed account balances with separate scope subtotals."""
    metadata, accounts = await client.get_plan_metadata(), await client.get_accounts()
    for account in accounts:
        _validate_account(account)

    included = [
        account
        for account in accounts
        if not account["deleted"] and (include_closed or not account["closed"])
    ]
    on_budget = sum(
        (account["balance"] for account in included if account["on_budget"]), 0
    )
    tracking = sum(
        (account["balance"] for account in included if not account["on_budget"]), 0
    )
    currency = currency_from_plan(metadata)
    return account_result(included, on_budget, tracking, currency)
