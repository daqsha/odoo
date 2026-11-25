"""Widgets and helpers shared by several pages."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable, Sequence

import streamlit as st

import config
from logic import pricing, rules
from logic.models import Evaluation, PaymentOption, CartLine, Promotion, Quote
from logic.money import money

FLASH_KEY = "_flash"


def flash(message: str, kind: str = "success") -> None:
    """Queue a message that is shown at the top of the next run (survives st.rerun)."""
    st.session_state[FLASH_KEY] = (kind, message)


def show_flash() -> None:
    item = st.session_state.pop(FLASH_KEY, None)
    if item:
        kind, message = item
        getattr(st, kind)(message)


TOAST_KEY = "_toasts"


def toast(message: str, icon: str = "✅") -> None:
    """Queue a short, non-blocking confirmation that pops up in the corner on the next run."""
    st.session_state.setdefault(TOAST_KEY, []).append((message, icon))


def show_toasts() -> None:
    for message, icon in st.session_state.pop(TOAST_KEY, []):
        st.toast(message, icon=icon)


def show_notices(notices: Sequence[tuple[str, str]]) -> None:
    for kind, message in notices:
        getattr(st, kind)(message)


def fmt_stamp(value: str | None) -> str:
    try:
        return datetime.fromisoformat(value or "").strftime("%d %b %Y %H:%M")
    except (TypeError, ValueError):
        return value or ""


def kv_rows(rows: Sequence[tuple[str, str]], *, emphasise_last: bool = False) -> None:
    for index, (label, value) in enumerate(rows):
        strong = emphasise_last and index == len(rows) - 1
        left, right = st.columns([3, 2])
        left.markdown(f"**{label}**" if strong else label)
        shown = f"<b>{value}</b>" if strong else value
        right.markdown(f"<div style='text-align:right'>{shown}</div>", unsafe_allow_html=True)


def totals_block(quote: Quote) -> None:
    rows = [("Subtotal", money(quote.subtotal))]
    if quote.promo_discount:
        rows.append(("Promotions", f"−{money(quote.promo_discount)}"))
    if quote.surcharge and quote.payment:
        rows.append((f"Payment fee ({quote.payment.surcharge_pct:g}%)", money(quote.surcharge)))
    rows.append((f"Included {config.TAX_LABEL}", money(quote.tax_included)))
    if quote.cashback:
        rows.append(("Cashback reward (credited later)", money(quote.cashback)))
        rows.append(("Effective price after rewards", money(quote.effective_total)))
    kv_rows(rows)


def savings_by_promo(
    lines: Sequence[CartLine],
    payment: PaymentOption | None,
    applied: Sequence[Promotion],
    evaluations: Iterable[Evaluation],
) -> dict[int, int]:
    """How much each unlocked-but-not-applied promotion would save right now."""
    if not lines or payment is None:
        return {}
    base = pricing.build_quote(lines, payment, applied).effective_total
    applied_ids = {p.id for p in applied}
    result: dict[int, int] = {}
    for ev in evaluations:
        if ev.eligible and ev.promotion.id not in applied_ids:
            after = pricing.build_quote(lines, payment, [*applied, ev.promotion]).effective_total
            result[ev.promotion.id] = base - after
    return result


def _promo_card(ev: Evaluation, applied: bool, *, prefix, on_apply, on_remove, saving: int) -> None:
    promo = ev.promotion
    with st.container(border=True, key=f"card_promo_{prefix}_{promo.id}"):
        st.markdown(f"**{promo.name}** · `{promo.code}`")
        st.caption(rules.reward_summary(promo))
        if applied:
            st.markdown(":green[✔ Applied to this sale]")
        elif ev.eligible:
            text = ":green[🔓 Unlocked. T&C met]"
            if saving:
                text += f" · saves **{money(saving)}**"
            st.markdown(text)
        else:
            st.markdown(":red[🔒 Locked]")
            for reason in ev.reasons:
                st.caption(f"✖ {reason}")
        with st.expander("Terms & conditions"):
            for line in rules.terms(promo):
                st.markdown(f"- {line}")
        if applied:
            st.button("Remove", key=f"{prefix}_promo_remove_{promo.id}", on_click=on_remove, args=(promo.id,))
        else:
            st.button(
                "Apply",
                key=f"{prefix}_promo_apply_{promo.id}",
                type="primary" if ev.eligible else "secondary",
                disabled=not ev.eligible,
                on_click=on_apply,
                args=(promo.id,),
            )


def promo_panel(
    evaluations: Iterable[Evaluation],
    applied_ids: Iterable[int],
    *,
    prefix: str,
    on_apply: Callable[[int], None],
    on_remove: Callable[[int], None],
    savings: dict[int, int] | None = None,
) -> None:
    """Applied and unlocked promotions first; locked ones grouped below with what each is missing.

    The locked group opens by itself when nothing qualifies yet, so the cashier always sees why.
    """
    applied_set = set(applied_ids)
    savings = savings or {}
    evaluations = list(evaluations)
    if not evaluations:
        st.info("No promotions are configured.")
        return

    ready = sorted(
        (ev for ev in evaluations if ev.promotion.id in applied_set or ev.eligible),
        key=lambda ev: (ev.promotion.id not in applied_set, -savings.get(ev.promotion.id, 0), ev.promotion.code),
    )
    locked = sorted((ev for ev in evaluations if ev not in ready), key=lambda ev: ev.promotion.code)

    for ev in ready:
        _promo_card(
            ev, ev.promotion.id in applied_set, prefix=prefix, on_apply=on_apply, on_remove=on_remove,
            saving=savings.get(ev.promotion.id, 0),
        )
    if not ready:
        st.caption("No promotion qualifies yet. Each locked card below lists what is missing.")
    if locked:
        label = f"🔒 {len(locked)} locked promotion(s) · see what is missing"
        with st.expander(label, expanded=not ready):
            for ev in locked:
                _promo_card(ev, False, prefix=prefix, on_apply=on_apply, on_remove=on_remove, saving=0)
