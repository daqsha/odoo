"""Turns cart lines + payment method + applied promotions into a Quote.

Price reductions (percent / fixed) are applied in the order the promotions were applied.
Each one works on the amount still left on its eligible lines, so a price can never go
negative. Cashback is calculated last, on the net amount, and is a reward credit: it does
not change the amount collected today.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import config
from logic.models import (
    CASHBACK,
    PERCENT_OFF,
    CartLine,
    LineQuote,
    PaymentOption,
    PromoApplication,
    Promotion,
    Quote,
)
from logic.money import allocate, percent_of, round_half_up, to_fraction


def _eligible_indexes(promo: Promotion, lines: Sequence[CartLine]) -> list[int]:
    return [i for i, line in enumerate(lines) if promo.covers(line)]


def build_quote(
    lines: Iterable[CartLine],
    payment: PaymentOption | None,
    promotions: Iterable[Promotion],
    tax_rate: float = config.TAX_RATE,
) -> Quote:
    lines = list(lines)
    promotions = list(promotions)
    remaining = [line.line_total for line in lines]
    line_discounts = [0] * len(lines)
    discount_by_promo: dict[int, int] = {}
    cashback_by_promo: dict[int, int] = {}

    # 1. Price reductions, in the order they were applied.
    for promo in promotions:
        if promo.reward_type == CASHBACK:
            continue
        indexes = _eligible_indexes(promo, lines)
        base = sum(remaining[i] for i in indexes)
        if promo.reward_type == PERCENT_OFF:
            amount = percent_of(base, promo.reward_value)
            if promo.max_reward is not None:
                amount = min(amount, promo.max_reward)
        else:  # FIXED_OFF
            amount = round_half_up(to_fraction(promo.reward_value))
        amount = max(0, min(amount, base))
        if amount:
            shares = allocate(amount, [remaining[i] for i in indexes])
            for i, share in zip(indexes, shares):
                remaining[i] -= share
                line_discounts[i] += share
        discount_by_promo[promo.id] = amount

    # 2. Cashback on what the customer actually pays for the eligible items.
    for promo in promotions:
        if promo.reward_type != CASHBACK:
            continue
        indexes = _eligible_indexes(promo, lines)
        base = sum(remaining[i] for i in indexes)
        amount = percent_of(base, promo.reward_value)
        if promo.max_reward is not None:
            amount = min(amount, promo.max_reward)
        cashback_by_promo[promo.id] = max(0, min(amount, base))

    applications = tuple(
        PromoApplication(
            promotion=promo,
            discount=discount_by_promo.get(promo.id, 0),
            cashback=cashback_by_promo.get(promo.id, 0),
        )
        for promo in promotions
    )

    subtotal = sum(line.line_total for line in lines)
    items_net = sum(remaining)
    promo_discount = sum(app.discount for app in applications)
    cashback = sum(app.cashback for app in applications)
    surcharge_pct = payment.surcharge_pct if payment else 0.0
    surcharge = percent_of(items_net, surcharge_pct)
    total_due = items_net + surcharge

    tax_included = 0
    if tax_rate > 0:
        # Prices already include tax, so the tax is the part of the total that is not base price.
        tax_included = total_due - round_half_up(to_fraction(total_due) / (1 + to_fraction(tax_rate)))

    line_quotes = tuple(
        LineQuote(
            index=i,
            product_id=line.product_id,
            sku=line.sku,
            name=line.name,
            serial_no=line.serial_no,
            qty=line.qty,
            unit_price=line.unit_price,
            list_total=line.line_total,
            discount=line_discounts[i],
            net_total=remaining[i],
        )
        for i, line in enumerate(lines)
    )

    return Quote(
        lines=line_quotes,
        payment=payment,
        applications=applications,
        subtotal=subtotal,
        promo_discount=promo_discount,
        items_net=items_net,
        surcharge=surcharge,
        total_due=total_due,
        cashback=cashback,
        effective_total=total_due - cashback,
        tax_included=tax_included,
    )
