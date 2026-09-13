from dataclasses import dataclass


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
    whole, remainder = divmod(abs(value), 1000)
    sign = "-" if value < 0 else ""
    if currency.decimal_digits == 0:
        return f"{sign}{whole}"
    fraction = remainder // quantum
    return f"{sign}{whole}.{fraction:0{currency.decimal_digits}d}"
