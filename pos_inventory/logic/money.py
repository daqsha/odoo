"""Money helpers.

Amounts are whole-rupiah integers. Percentages are computed with Fraction so there is no
floating-point drift, and rounding is always half-up.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Sequence

import config


def to_fraction(value) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, float):
        return Fraction(repr(value))  # repr keeps 12.5 as 12.5, not 12.4999999...
    return Fraction(value)


def round_half_up(value) -> int:
    return math.floor(to_fraction(value) + Fraction(1, 2))


def percent_of(base: int, pct) -> int:
    return round_half_up(to_fraction(base) * to_fraction(pct) / 100)


def allocate(total: int, weights: Sequence[int]) -> list[int]:
    """Split `total` into integer shares proportional to `weights`.

    Uses the largest-remainder method, so the shares always add up to exactly `total`.
    """
    weight_sum = sum(weights)
    if total <= 0 or weight_sum <= 0:
        return [0] * len(weights)
    shares = [total * w // weight_sum for w in weights]
    leftover = total - sum(shares)
    by_remainder = sorted(
        range(len(weights)),
        key=lambda i: (-(total * weights[i] % weight_sum), i),
    )
    for i in by_remainder[:leftover]:
        shares[i] += 1
    return shares


def money(amount) -> str:
    value = round_half_up(amount)
    sign = "-" if value < 0 else ""
    digits = f"{abs(value):,}".replace(",", ".")
    return f"{sign}{config.CURRENCY_SYMBOL} {digits}"
