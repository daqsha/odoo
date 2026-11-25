"""Promotions & payment options: maintain the T&C that the rule engine enforces."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from database.db import transaction
from logic import catalog, payments, rules
from logic import promotions as promo_store
from logic.errors import BusinessError
from logic.money import money
from views import common

K_VERSION = "promo_form_version"
PAYMENT_METHOD_LABELS = payments.METHOD_LABELS


def _version() -> int:
    return st.session_state.setdefault(K_VERSION, 0)


def _done(message: str) -> None:
    st.session_state[K_VERSION] = _version() + 1
    common.flash(message)
    st.rerun()


def _toggle_promo(promo_id: int, currently_active: bool) -> None:
    with transaction(write=True) as conn:
        promo_store.set_promotion_active(conn, promo_id, not currently_active)


def _toggle_payment(code: str, currently_active: bool) -> None:
    with transaction(write=True) as conn:
        payments.set_payment_active(conn, code, not currently_active)


def render() -> None:
    st.header("🎯 Promotions & payment options")
    st.caption(
        "A promotion unlocks at the POS only when its T&C are met for the chosen payment method and the cart. "
        "The rule engine re-checks every applied promotion on each change and at checkout."
    )
    list_tab, new_promo_tab, payments_tab, new_payment_tab = st.tabs(
        ["Promotions", "New promotion", "Payment options", "New payment option"]
    )
    with list_tab:
        _promotion_list()
    with new_promo_tab:
        _new_promotion()
    with payments_tab:
        _payment_list()
    with new_payment_tab:
        _new_payment()


def _period(promo) -> str:
    if not promo.start_date and not promo.end_date:
        return "Open-ended"
    start = promo.start_date.strftime("%d %b %Y") if promo.start_date else "now"
    end = promo.end_date.strftime("%d %b %Y") if promo.end_date else "open-ended"
    return f"{start} to {end}"


def _promotion_list() -> None:
    with transaction() as conn:
        promos = promo_store.load_promotions(conn, active_only=False)
    if not promos:
        st.info("No promotions yet. Create one in the New promotion tab.")
        return

    st.dataframe(
        [
            {
                "Code": p.code,
                "Name": p.name,
                "Reward": rules.reward_summary(p),
                "Min spend": money(p.min_spend) if p.min_spend else "none",
                "Eligible items": f"{len(p.eligible_skus)} SKU(s)" if p.eligible_skus else "all",
                "Payment": " / ".join(label for _, label in p.required_payments) or "any",
                "Valid": _period(p),
                "Combinable": "yes" if p.stackable else "no",
                "Status": "On" if p.active else "Off",
            }
            for p in promos
        ],
        hide_index=True,
    )

    by_id = {p.id: p for p in promos}
    pick = st.selectbox("Promotion", list(by_id), format_func=lambda x: f"{by_id[x].code} · {by_id[x].name}", key="promo_pick")
    promo = by_id[pick]
    st.markdown(f"**Terms for {promo.code}**")
    for line in rules.terms(promo):
        st.markdown(f"- {line}")
    st.button(
        "Switch off" if promo.active else "Switch on",
        key=f"promo_toggle_{promo.id}",
        on_click=_toggle_promo,
        args=(promo.id, promo.active),
    )


def _new_promotion() -> None:
    version = _version()
    with transaction() as conn:
        products = catalog.list_products(conn)
        payment_options = payments.load_payment_options(conn, active_only=False)
    payment_labels = {p.code: payments.payment_label(p) for p in payment_options}
    reward_labels = promo_store.REWARD_LABELS

    with st.form(f"new_promo_form_{version}"):
        code = st.text_input("Promotion code", placeholder="e.g. RAYA25", key=f"np_code_{version}")
        name = st.text_input("Name shown to cashiers", key=f"np_name_{version}")
        description = st.text_input("Description (optional)", key=f"np_desc_{version}")
        reward_type = st.selectbox(
            "Reward type", list(reward_labels), format_func=reward_labels.get, key=f"np_type_{version}"
        )
        reward_value = st.number_input(
            "Reward value (percent, or Rp for amount off)", min_value=0.0, value=10.0, step=1.0, key=f"np_value_{version}"
        )
        max_reward = st.number_input(
            "Maximum reward in Rp (0 = no cap)", min_value=0, value=0, step=10000, key=f"np_max_{version}"
        )
        min_spend = st.number_input(
            "Minimum eligible spend in Rp (0 = none)", min_value=0, value=0, step=50000, key=f"np_min_{version}"
        )
        min_qty = st.number_input("Minimum eligible units", min_value=1, value=1, step=1, key=f"np_qty_{version}")
        skus = st.multiselect(
            "Eligible products (leave empty for all products)",
            [p["sku"] for p in products],
            key=f"np_skus_{version}",
        )
        pay_codes = st.multiselect(
            "Payment options that unlock it (leave empty for any payment method)",
            list(payment_labels),
            format_func=lambda c: payment_labels[c],
            key=f"np_pay_{version}",
        )
        stackable = st.checkbox(
            "Can be combined with other discounts", key=f"np_stack_{version}"
        )
        limit_dates = st.checkbox("Limit validity dates", key=f"np_dates_{version}")
        start = st.date_input("Valid from", value=date.today(), key=f"np_start_{version}")
        end = st.date_input("Valid until", value=date.today() + timedelta(days=30), key=f"np_end_{version}")
        submitted = st.form_submit_button("Create promotion", type="primary")

    if submitted:
        try:
            with transaction(write=True) as conn:
                promo_store.create_promotion(
                    conn,
                    code=code,
                    name=name,
                    description=description,
                    reward_type=reward_type,
                    reward_value=float(reward_value),
                    max_reward=int(max_reward) or None,
                    min_spend=int(min_spend),
                    min_qty=int(min_qty),
                    skus=skus,
                    payment_codes=pay_codes,
                    stackable=stackable,
                    start_date=start if limit_dates else None,
                    end_date=end if limit_dates else None,
                )
        except BusinessError as exc:
            st.error(str(exc))
        else:
            _done(f"Promotion {code.strip().upper().replace(' ', '-')} created.")


def _payment_list() -> None:
    with transaction() as conn:
        options = payments.load_payment_options(conn, active_only=False)
    st.dataframe(
        [
            {
                "Code": o.code,
                "Label": o.label,
                "Method": PAYMENT_METHOD_LABELS.get(o.method, o.method),
                "Issuer": o.issuer or "—",
                "Tenor": f"{o.tenor_months} months" if o.tenor_months else "Full payment",
                "Fee": f"{o.surcharge_pct:g}%" if o.surcharge_pct else "0%",
                "Status": "On" if o.active else "Off",
            }
            for o in options
        ],
        hide_index=True,
    )
    by_code = {o.code: o for o in options}
    pick = st.selectbox("Payment option", list(by_code), format_func=lambda c: by_code[c].label, key="pay_pick")
    option = by_code[pick]
    st.button(
        "Switch off" if option.active else "Switch on",
        key=f"pay_toggle_{option.code}",
        on_click=_toggle_payment,
        args=(option.code, option.active),
    )


def _new_payment() -> None:
    version = _version()
    with st.form(f"new_payment_form_{version}"):
        code = st.text_input("Code", placeholder="e.g. BRI-CC-3M", key=f"nq_code_{version}")
        label = st.text_input("Label shown at checkout", key=f"nq_label_{version}")
        method = st.selectbox(
            "Method", list(PAYMENT_METHOD_LABELS), format_func=PAYMENT_METHOD_LABELS.get, key=f"nq_method_{version}"
        )
        issuer = st.text_input("Bank or provider (optional)", key=f"nq_issuer_{version}")
        tenor = st.number_input(
            "Installment tenor in months (0 = full payment)", min_value=0, value=0, step=1, key=f"nq_tenor_{version}"
        )
        fee = st.number_input(
            "Payment fee in percent (0 = no fee)", min_value=0.0, max_value=10.0, value=0.0, step=0.5, key=f"nq_fee_{version}"
        )
        submitted = st.form_submit_button("Create payment option", type="primary")
    if submitted:
        try:
            with transaction(write=True) as conn:
                payments.create_payment_option(
                    conn,
                    code=code,
                    label=label,
                    method=method,
                    issuer=issuer,
                    tenor_months=int(tenor),
                    surcharge_pct=float(fee),
                )
        except BusinessError as exc:
            st.error(str(exc))
        else:
            _done(f"Payment option {code.strip().upper()} created.")
