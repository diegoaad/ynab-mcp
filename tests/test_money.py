from decimal import localcontext

import pytest

from ynab_mcp.money import CurrencyFormat, format_milliunits


@pytest.mark.parametrize(
    ("milliunits", "digits", "expected"),
    [
        (1000, 2, "1.00"),
        (123450, 2, "123.45"),
        (-42100, 2, "-42.10"),
        (1300, 1, "1.3"),
        (-395032, 3, "-395.032"),
    ],
)
def test_exact_money(milliunits: int, digits: int, expected: str) -> None:
    assert format_milliunits(milliunits, CurrencyFormat("USD", digits)) == expected


def test_invalid_precision_fails() -> None:
    with pytest.raises(ValueError):
        format_milliunits(1001, CurrencyFormat("USD", 2))


@pytest.mark.parametrize(
    "value, expected",
    [(1234567890, "1234567.890"), (-1234567890, "-1234567.890"), (-1001, "-1.001")],
)
def test_exact_money_ignores_decimal_context(value: int, expected: str) -> None:
    with localcontext() as context:
        context.prec = 3
        assert format_milliunits(value, CurrencyFormat("USD", 3)) == expected
