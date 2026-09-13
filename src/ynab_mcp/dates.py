from datetime import UTC, date, datetime


def parse_month(value: str | None) -> date:
    if value is None:
        month = datetime.now(UTC).date().replace(day=1)
    else:
        month = date.fromisoformat(value)
        if month.isoformat() != value:
            raise ValueError("month must use YYYY-MM-01")
    if month.day != 1:
        raise ValueError("month must be the first day")
    return month


def parse_window(start: str, end: str) -> tuple[date, date]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if not first <= last or (last - first).days + 1 > 366:
        raise ValueError("date window must span 1 through 366 days")
    return first, last
