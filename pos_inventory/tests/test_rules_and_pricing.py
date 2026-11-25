"""Pure tests for the promotion rule engine and the price calculator. No database needed."""

from datetime import date

import pytest

from logic import pricing, rules
from logic.errors import PromotionError
from logic.models import CASHBACK, FIXED_OFF, PERCENT_OFF, CartLine, PaymentOption, Promotion

TODAY = date(2026, 11, 25)

PHONE = CartLine(product_id=1, sku="NX-X1-128-BLK", name="Nimbus X1", unit_price=4_599_000, qty=1)
PHONE_2 = CartLine(product_id=1, sku="NX-X1-128-BLK", name="Nimbus X1", unit_price=4_599_000, qty=1, serial_no="S2")
CHARGER = CartLine(product_id=2, sku="CH-GAN-65W", name="Charger", unit_price=299_000, qty=2)
CASE = CartLine(product_id=3, sku="CS-NX1-SLM", name="Case", unit_price=99_000, qty=1)


def promo(**overrides) -> Promotion:
    values = dict(
        id=1,
        code="P1",
        name="Promo one",
        description="",
        reward_type=PERCENT_OFF,
        reward_value=10.0,
        max_reward=None,
        min_spend=0,
        min_qty=1,
        stackable=False,
        start_date=None,
        end_date=None,
        active=True,
        eligible_skus=frozenset(),
        required_payments=(),
    )
    values.update(overrides)
    return Promotion(**values)


def payment(code="CASH", surcharge=0.0) -> PaymentOption:
    return PaymentOption(
        id=hash(code) % 1000,
        code=code,
        label=code,
        method="CASH",
        issuer="",
        tenor_months=0,
        surcharge_pct=surcharge,
        active=True,
    )


def evaluate(p, lines, pay, applied=(), today=TODAY):
    return rules.evaluate_promotion(p, lines, pay, today, applied)


# ----- rule engine: gating and T&C -----

def test_nothing_unlocks_before_a_payment_method_is_chosen():
    ev = evaluate(promo(), [PHONE], None)
    assert not ev.eligible
    assert ev.reasons == ("Select a payment method first",)


def test_plain_promotion_unlocks_once_payment_is_chosen_and_cart_qualifies():
    ev = evaluate(promo(), [PHONE], payment("CASH"))
    assert ev.eligible and ev.reasons == ()


def test_required_payment_locks_other_payment_methods_and_names_the_requirement():
    p = promo(required_payments=(("BCA-CC-12M", "BCA Credit Card 12-month"),))
    ev = evaluate(p, [PHONE], payment("CASH"))
    assert not ev.eligible
    assert ev.reasons == ("Requires payment: BCA Credit Card 12-month",)
    assert evaluate(p, [PHONE], payment("BCA-CC-12M")).eligible


def test_min_spend_is_checked_on_eligible_lines_only_and_shows_the_shortfall():
    p = promo(min_spend=3_000_000, eligible_skus=frozenset({"NX-X1-128-BLK"}))
    ev = evaluate(p, [PHONE, CASE], payment())
    assert ev.eligible  # phone alone (4.599.000) already meets it
    ev = evaluate(p, [CASE, CHARGER], payment())
    assert not ev.eligible
    assert ev.reasons == ("Needs an eligible item: NX-X1-128-BLK",)


def test_min_spend_shortfall_message_gives_the_exact_gap():
    p = promo(min_spend=5_000_000)
    ev = evaluate(p, [PHONE], payment())  # 4.599.000 so far
    assert ev.reasons == ("Add Rp 401.000 more eligible items (minimum Rp 5.000.000)",)


def test_min_qty_counts_eligible_units_only():
    p = promo(min_qty=2, eligible_skus=frozenset({"CH-GAN-65W"}))
    assert evaluate(p, [CHARGER], payment()).eligible  # 2 units
    ev = evaluate(p, [PHONE, PHONE_2], payment())
    assert ev.reasons == ("Needs an eligible item: CH-GAN-65W",)


def test_validity_window_locks_before_start_and_after_end():
    future = promo(start_date=date(2026, 12, 1))
    assert evaluate(future, [PHONE], payment()).reasons == ("Starts 01 Dec 2026",)
    expired = promo(end_date=date(2025, 12, 31))
    assert evaluate(expired, [PHONE], payment()).reasons == ("Expired on 31 Dec 2025",)
    assert evaluate(promo(start_date=date(2026, 11, 1), end_date=date(2026, 11, 30)), [PHONE], payment()).eligible


def test_switched_off_promotion_is_locked():
    assert evaluate(promo(active=False), [PHONE], payment()).reasons == ("Promotion is switched off",)


def test_two_non_stackable_discounts_cannot_be_combined():
    a = promo(id=1, code="A", name="Alpha")
    b = promo(id=2, code="B", name="Beta", reward_type=FIXED_OFF, reward_value=100_000)
    ev = evaluate(b, [PHONE], payment(), applied=[a])
    assert ev.reasons == ("Cannot be combined with Alpha",)


def test_two_stackable_discounts_can_be_combined():
    a = promo(id=1, code="A", stackable=True)
    b = promo(id=2, code="B", stackable=True, reward_type=FIXED_OFF, reward_value=100_000)
    assert evaluate(b, [PHONE], payment(), applied=[a]).eligible


def test_cashback_never_conflicts_with_a_discount():
    discount = promo(id=1, code="D")
    cashback = promo(id=2, code="CB", reward_type=CASHBACK, reward_value=10)
    assert evaluate(cashback, [PHONE], payment(), applied=[discount]).eligible


def test_evaluate_all_marks_each_promotion_independently():
    promos = [
        promo(id=1, code="OPEN"),
        promo(id=2, code="BCA", required_payments=(("BCA", "BCA card"),)),
    ]
    results = {ev.promotion.code: ev for ev in rules.evaluate_all(promos, [PHONE], payment("CASH"), TODAY)}
    assert results["OPEN"].eligible
    assert not results["BCA"].eligible


def test_prune_removes_an_applied_promotion_when_payment_changes():
    p = promo(id=7, code="BCA7", required_payments=(("BCA", "BCA card"),))
    kept, removed = rules.prune_applied([p], [PHONE], payment("BCA"), TODAY, [7])
    assert [k.id for k in kept] == [7]
    kept, removed = rules.prune_applied([p], [PHONE], payment("CASH"), TODAY, [7])
    assert kept == []
    assert removed == [("Promo one", ("Requires payment: BCA card",))]


def test_prune_removes_a_promotion_when_cart_no_longer_meets_min_spend():
    p = promo(id=3, min_spend=5_000_000)  # the phone alone is 4.599.000
    kept, removed = rules.prune_applied([p], [PHONE], payment(), TODAY, [3])
    assert kept == [] and removed[0][1][0].startswith("Add Rp 401.000")


def test_try_apply_raises_with_every_missing_condition():
    p = promo(id=5, code="LOCK", min_spend=9_000_000, required_payments=(("OVO", "OVO"),))
    with pytest.raises(PromotionError) as info:
        rules.try_apply([p], [PHONE], payment("CASH"), TODAY, [], 5)
    assert "Requires payment: OVO" in str(info.value)
    assert "Add Rp" in str(info.value)


def test_try_apply_returns_new_ids_in_order():
    a = promo(id=1, code="A", stackable=True)
    b = promo(id=2, code="B", stackable=True)
    assert rules.try_apply([a, b], [PHONE], payment(), TODAY, [1], 2) == [1, 2]


def test_auto_select_picks_the_larger_of_two_conflicting_discounts():
    big = promo(id=1, code="PCT", reward_value=10, max_reward=500_000)
    small = promo(id=2, code="FIX", reward_type=FIXED_OFF, reward_value=250_000)
    chosen = rules.auto_select([big, small], [PHONE], payment(), TODAY)
    assert [p.code for p in chosen] == ["PCT"]


def test_auto_select_stacks_compatible_discounts_biggest_saving_first():
    pct = promo(id=1, code="PCT", reward_value=5, stackable=True)  # 229.950 off the phone
    fixed = promo(id=2, code="FIX", reward_type=FIXED_OFF, reward_value=100_000, stackable=True)
    chosen = rules.auto_select([pct, fixed], [PHONE], payment(), TODAY)
    assert [p.code for p in chosen] == ["PCT", "FIX"]


def test_terms_describe_the_conditions_in_plain_language():
    p = promo(
        min_spend=3_000_000,
        max_reward=500_000,
        eligible_skus=frozenset({"NX-X1-128-BLK"}),
        required_payments=(("BCA", "BCA Credit Card"),),
    )
    lines = rules.terms(p)
    assert lines[0] == "10% off eligible items, capped at Rp 500.000"
    assert "Minimum eligible spend Rp 3.000.000" in lines
    assert "Eligible items: NX-X1-128-BLK" in lines
    assert "Payment: BCA Credit Card" in lines


# ----- pricing -----

def test_percent_discount_respects_the_cap():
    p = promo(reward_value=10, max_reward=500_000)
    big = CartLine(product_id=9, sku="X", name="Big", unit_price=9_198_000)  # 10% would be 919.800
    assert pricing.build_quote([big], payment(), [p]).promo_discount == 500_000


def test_percent_discount_below_cap_is_exact():
    p = promo(reward_value=10, max_reward=500_000)
    assert pricing.build_quote([PHONE], payment(), [p]).promo_discount == 459_900


def test_fixed_discount_never_exceeds_the_eligible_amount():
    cheap = CartLine(product_id=5, sku="CB", name="Cable", unit_price=79_000)
    p = promo(reward_type=FIXED_OFF, reward_value=150_000, eligible_skus=frozenset({"CB"}))
    quote = pricing.build_quote([cheap], payment(), [p])
    assert quote.promo_discount == 79_000
    assert quote.items_net == 0


def test_discounts_apply_in_sequence_on_remaining_amounts():
    a = promo(id=1, code="A", reward_value=10, stackable=True)
    b = promo(id=2, code="B", reward_value=10, stackable=True)
    quote = pricing.build_quote([CartLine(product_id=1, sku="X", name="X", unit_price=1_000_000)], payment(), [a, b])
    # 10% of 1.000.000 = 100.000, then 10% of the remaining 900.000 = 90.000
    assert quote.promo_discount == 190_000
    assert quote.items_net == 810_000


def test_line_level_discounts_add_up_to_the_promotion_total():
    p = promo(reward_type=FIXED_OFF, reward_value=100_000)
    quote = pricing.build_quote([PHONE, CHARGER], payment(), [p])
    assert sum(line.discount for line in quote.lines) == 100_000
    assert quote.promo_discount == 100_000


def test_surcharge_is_applied_after_discounts():
    p = promo(reward_value=10)
    quote = pricing.build_quote([PHONE], payment("BCA-12", surcharge=1.5), [p])
    assert quote.items_net == 4_599_000 - 459_900  # 4.139.100
    assert quote.surcharge == 62_087  # 1.5% of 4.139.100 = 62.086,5, rounded half-up
    assert quote.total_due == quote.items_net + quote.surcharge


def test_cashback_is_a_credit_and_does_not_reduce_the_amount_collected():
    cb = promo(reward_type=CASHBACK, reward_value=15, max_reward=150_000)
    quote = pricing.build_quote([PHONE], payment("GOPAY"), [cb])
    assert quote.total_due == 4_599_000
    assert quote.cashback == 150_000  # 15% of 4.599.000 = 689.850, capped
    assert quote.effective_total == 4_599_000 - 150_000


def test_tax_is_shown_as_included_in_the_total():
    line = CartLine(product_id=1, sku="A", name="A", unit_price=1_110_000)
    quote = pricing.build_quote([line], payment(), [], tax_rate=0.11)
    assert quote.total_due == 1_110_000
    assert quote.tax_included == 110_000
