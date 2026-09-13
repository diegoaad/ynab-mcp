from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CurrencyFormat:
    iso_code: str
    decimal_digits: int


def format_milliunits(value: int, currency: CurrencyFormat) -> str:
    if currency.decimal_digits not in (0, 1, 2, 3):
        raise ValueError("unsupported currency precision")
    quantum = 10 ** (3 - currency.decimal_digits)
    if value % quantum:
        raise ValueError("milliunits exceed currency precision")
    amount = Decimal(value) / Decimal(1000)
    return f"{amount:.{currency.decimal_digits}f}"
