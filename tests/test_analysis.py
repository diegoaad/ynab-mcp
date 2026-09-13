from collections import defaultdict
from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from tests.fixtures import (
    spending_fixture_accounts,
    spending_fixture_categories,
    spending_fixture_tracking_transfer,
    spending_fixture_transactions,
)
from ynab_mcp.analysis import extract_postings
from ynab_mcp.errors import YnabError


def test_split_refund_and_transfer_are_counted_once() -> None:
    postings = extract_postings(
        spending_fixture_transactions(),
        spending_fixture_accounts(),
        spending_fixture_categories(),
    )
    by_category: dict[str, int] = defaultdict(int)
    for posting in postings:
        by_category[posting.category_name] += posting.milliunits
    assert by_category == {
        "Restaurants": -65000,
        "Groceries": -20000,
        "Uncategorized": -10000,
    }
    assert [p.transaction_id for p in postings] == [
        "split-restaurants",
        "split-groceries",
        "refund",
        "uncategorized-purchase",
    ]
    assert postings[0].date == date(2026, 9, 10)
    assert postings[0].account_name == "Checking"
    with pytest.raises(FrozenInstanceError):
        postings[0].milliunits = 1  # type: ignore[misc]


def test_categorized_tracking_transfer_counts_only_on_budget_side() -> None:
    postings = extract_postings(
        spending_fixture_tracking_transfer(),
        spending_fixture_accounts(),
        spending_fixture_categories(),
    )
    assert [(p.transaction_id, p.category_name, p.milliunits) for p in postings] == [
        ("tracking-transfer", "Groceries", -7000),
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rows: rows[0].pop("date"),
        lambda rows: rows[0].pop("subtransactions"),
        lambda rows: rows[1].pop("amount"),
        lambda rows: rows[1].__setitem__("category_id", "unknown"),
        lambda rows: rows[1].__setitem__("account_id", "unknown"),
    ],
)
def test_required_transaction_data_is_not_guessed(mutation: object) -> None:
    rows = spending_fixture_transactions()
    mutation(rows)  # type: ignore[operator]
    with pytest.raises(YnabError, match="incomplete_data"):
        extract_postings(
            rows, spending_fixture_accounts(), spending_fixture_categories()
        )


def test_missing_reference_names_are_incomplete_data() -> None:
    accounts = spending_fixture_accounts()
    accounts[0].pop("name")
    with pytest.raises(YnabError, match="incomplete_data"):
        extract_postings(
            spending_fixture_transactions(), accounts, spending_fixture_categories()
        )
