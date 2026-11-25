"""Small helpers shared by the logic modules."""

from __future__ import annotations

from datetime import date, datetime


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    return date.fromisoformat(text) if text else None


def iso_date(value: date | str | None) -> str | None:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else None


def fmt_date(value: date) -> str:
    return value.strftime("%d %b %Y")
