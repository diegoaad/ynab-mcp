import pytest

from ynab_mcp.dates import parse_month, parse_window


@pytest.mark.parametrize("value", ["20260901", "2026-W36-2"])
def test_noncanonical_month_fails(value: str) -> None:
    with pytest.raises(ValueError):
        parse_month(value)


def test_invalid_month_fails() -> None:
    with pytest.raises(ValueError):
        parse_month("2026-09-13")


def test_window_is_inclusive_and_bounded() -> None:
    assert parse_window("2026-09-01", "2026-09-01")[0].day == 1
    with pytest.raises(ValueError):
        parse_window("2025-01-01", "2026-09-01")
