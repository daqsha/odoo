"""Promotion rule engine.

A promotion is UNLOCKED only when every term holds for the current cart and payment method:

  1. A payment method has been chosen. Nothing unlocks before this step.
  2. The promotion is switched on and inside its validity window.
  3. The payment method is one of the methods it names (if it names any).
  4. The cart has an eligible SKU (if it names any), at least `min_qty` eligible units,
     and an eligible subtotal of at least `min_spend`.
  5. It does not clash with a discount that has already been applied (unless both are stackable).

Terms are checked against list prices before any promotion is applied, so the result never
depends on the order in which the cashier clicked.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Sequence

from logic import pricing
from logic.errors import PromotionError
from logic.models import (
    DISCOUNT_TYPES,
    FIXED_OFF,
    PERCENT_OFF,
    CartLine,
    Evaluation,
    PaymentOption,
    Promotion,
)
from logic.money import money
from logic.utils import fmt_date


def conflicts(a: Promotion, b: Promotion) -> bool:
    """Two price reductions clash unless both are marked stackable. Cashback never clashes."""
    if a.id == b.id:
        return False
    both_discounts = a.reward_type in DISCOUNT_TYPES and b.reward_type in DISCOUNT_TYPES
    return both_discounts and not (a.stackable and b.stackable)


def _sku_summary(skus: Iterable[str]) -> str:
    ordered = sorted(skus)
    shown = ", ".join(ordered[:4])
    return shown + (f" +{len(ordered) - 4} more" if len(ordered) > 4 else "")


def evaluate_promotion(
    promo: Promotion,
    lines: Sequence[CartLine],
    payment: PaymentOption | None,
    today: date,
    applied: Iterable[Promotion] = (),
) -> Evaluation:
    eligible_lines = [line for line in lines if promo.covers(line)]
    subtotal = sum(line.line_total for line in eligible_lines)
    qty = sum(line.qty for line in eligible_lines)

    def result(reasons: list[str]) -> Evaluation:
        return Evaluation(
            promotion=promo,
            eligible=not reasons,
            reasons=tuple(reasons),
            eligible_subtotal=subtotal,
            eligible_qty=qty,
        )

    if payment is None:
        return result(["Select a payment method first"])

    reasons: list[str] = []
    if not promo.active:
        reasons.append("Promotion is switched off")
    if promo.start_date and today < promo.start_date:
        reasons.append(f"Starts {fmt_date(promo.start_date)}")
    if promo.end_date and today > promo.end_date:
        reasons.append(f"Expired on {fmt_date(promo.end_date)}")
    if promo.required_payments and payment.code not in promo.allowed_payment_codes:
        reasons.append("Requires payment: " + " or ".join(label for _, label in promo.required_payments))
    if promo.eligible_skus and not eligible_lines:
        reasons.append("Needs an eligible item: " + _sku_summary(promo.eligible_skus))
    else:
        if qty < promo.min_qty:
            reasons.append(f"Needs {promo.min_qty} eligible item(s), cart has {qty}")
        if subtotal < promo.min_spend:
            reasons.append(
                f"Add {money(promo.min_spend - subtotal)} more eligible items "
                f"(minimum {money(promo.min_spend)})"
            )
    for other in applied:
        if conflicts(promo, other):
            reasons.append(f"Cannot be combined with {other.name}")
            break
    return result(reasons)


def evaluate_all(
    promotions: Sequence[Promotion],
    lines: Sequence[CartLine],
    payment: PaymentOption | None,
    today: date,
    applied_ids: Iterable[int] = (),
) -> list[Evaluation]:
    by_id = {p.id: p for p in promotions}
    applied = [by_id[i] for i in applied_ids if i in by_id]
    return [
        evaluate_promotion(promo, lines, payment, today, [p for p in applied if p.id != promo.id])
        for promo in promotions
    ]


def prune_applied(
    promotions: Sequence[Promotion],
    lines: Sequence[CartLine],
    payment: PaymentOption | None,
    today: date,
    applied_ids: Iterable[int],
) -> tuple[list[Promotion], list[tuple[str, tuple[str, ...]]]]:
    """Keep only the applied promotions whose T&C still hold. Used whenever the cart or payment changes.

    Returns (kept promotions in order, [(promotion name, reasons), ...] for the removed ones).
    """
    by_id = {p.id: p for p in promotions}
    kept: list[Promotion] = []
    removed: list[tuple[str, tuple[str, ...]]] = []
    for promo_id in dict.fromkeys(applied_ids):
        promo = by_id.get(promo_id)
        if promo is None:
            removed.append((f"Promotion #{promo_id}", ("Promotion no longer exists",)))
            continue
        evaluation = evaluate_promotion(promo, lines, payment, today, kept)
        if evaluation.eligible:
            kept.append(promo)
        else:
            removed.append((promo.name, evaluation.reasons))
    return kept, removed


def try_apply(
    promotions: Sequence[Promotion],
    lines: Sequence[CartLine],
    payment: PaymentOption | None,
    today: date,
    applied_ids: Iterable[int],
    promo_id: int,
) -> list[int]:
    """Apply one promotion, or raise PromotionError listing exactly what is missing."""
    kept, _ = prune_applied(promotions, lines, payment, today, applied_ids)
    kept_ids = [p.id for p in kept]
    if promo_id in kept_ids:
        return kept_ids
    promo = next((p for p in promotions if p.id == promo_id), None)
    if promo is None:
        raise PromotionError("This promotion is not available.")
    evaluation = evaluate_promotion(promo, lines, payment, today, kept)
    if not evaluation.eligible:
        raise PromotionError(f"{promo.name} is locked: " + "; ".join(evaluation.reasons))
    return kept_ids + [promo_id]


def auto_select(
    promotions: Sequence[Promotion],
    lines: Sequence[CartLine],
    payment: PaymentOption | None,
    today: date,
) -> list[Promotion]:
    """Greedy 'best eligible combination': repeatedly add the promotion that lowers the
    effective price the most, until nothing else qualifies. Used by the Demo Price comparison."""
    if payment is None:
        return []
    chosen: list[Promotion] = []
    current = pricing.build_quote(lines, payment, chosen).effective_total
    while True:
        best: tuple[int, Promotion] | None = None
        for promo in promotions:
            if any(p.id == promo.id for p in chosen):
                continue
            if not evaluate_promotion(promo, lines, payment, today, chosen).eligible:
                continue
            candidate = pricing.build_quote(lines, payment, [*chosen, promo]).effective_total
            if candidate < current and (best is None or candidate < best[0]):
                best = (candidate, promo)
        if best is None:
            return chosen
        current, promo = best
        chosen.append(promo)


def _pct(value: float) -> str:
    return f"{value:g}"


def reward_summary(promo: Promotion) -> str:
    cap = f", capped at {money(promo.max_reward)}" if promo.max_reward else ""
    if promo.reward_type == PERCENT_OFF:
        return f"{_pct(promo.reward_value)}% off eligible items{cap}"
    if promo.reward_type == FIXED_OFF:
        return f"{money(promo.reward_value)} off eligible items"
    return f"{_pct(promo.reward_value)}% cashback on eligible items{cap}"


def terms(promo: Promotion) -> list[str]:
    """Plain-language T&C lines shown to cashiers and in the admin screen."""
    lines = [reward_summary(promo)]
    if promo.min_spend:
        lines.append(f"Minimum eligible spend {money(promo.min_spend)}")
    if promo.min_qty > 1:
        lines.append(f"Minimum {promo.min_qty} eligible items")
    lines.append("Eligible items: " + (", ".join(sorted(promo.eligible_skus)) if promo.eligible_skus else "all products"))
    if promo.required_payments:
        lines.append("Payment: " + " or ".join(label for _, label in promo.required_payments))
    else:
        lines.append("Payment: any method (after a payment method is chosen)")
    if promo.start_date or promo.end_date:
        start = fmt_date(promo.start_date) if promo.start_date else "now"
        end = fmt_date(promo.end_date) if promo.end_date else "open-ended"
        lines.append(f"Valid {start} to {end}")
    if promo.reward_type in DISCOUNT_TYPES:
        lines.append(
            "Can be combined with other discounts" if promo.stackable else "Cannot be combined with other discounts"
        )
    else:
        lines.append("Cashback is a reward credit and does not change the amount paid today")
    return lines
