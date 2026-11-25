"""Validation for IMEI and serial numbers."""

from __future__ import annotations

import re

from logic.errors import BusinessError

_SERIAL_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{3,39}$")


def _luhn_sum(digits: str) -> int:
    total = 0
    for offset, char in enumerate(reversed(digits)):
        value = int(char)
        if offset % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total


def luhn_valid(digits: str) -> bool:
    return digits.isdigit() and _luhn_sum(digits) % 10 == 0


def imei_check_digit(body14: str) -> int:
    """Check digit that makes a 14-digit IMEI body valid. Used by the seed generator and tests."""
    return (10 - _luhn_sum(body14 + "0") % 10) % 10


def normalize_identifier(raw: str, tracking: str) -> str:
    """IMEIs are digits only (spaces and dashes removed); serials are upper-cased."""
    text = (raw or "").strip()
    if tracking == "imei":
        return re.sub(r"[\s-]", "", text)
    return text.upper()


def validate_identifier(value: str, tracking: str) -> str:
    if tracking == "imei":
        if len(value) != 15 or not value.isdigit():
            raise BusinessError(f"IMEI '{value}' must be exactly 15 digits.")
        if not luhn_valid(value):
            raise BusinessError(f"IMEI '{value}' fails the checksum (Luhn) test. Check the number and re-enter it.")
    elif tracking == "serial":
        if not _SERIAL_RE.match(value):
            raise BusinessError(f"Serial '{value}' must be 4 to 40 letters, digits or dashes.")
    else:
        raise BusinessError("This product is not tracked by serial number.")
    return value


def split_identifiers(text: str) -> list[str]:
    """Accept one number per line, or several separated by commas or semicolons."""
    return [part.strip() for part in re.split(r"[\n,;]+", text or "") if part.strip()]
