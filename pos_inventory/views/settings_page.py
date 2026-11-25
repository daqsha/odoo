"""Settings: store info, how promotions are decided, and resetting the demo data."""

from __future__ import annotations

import streamlit as st

import config
from database.seed import reset_demo_data
from views import common

K_CONFIRM = "reset_confirm"


def _reset() -> None:
    reset_demo_data()
    st.session_state["pos_cart"] = []
    st.session_state["pos_applied"] = []
    st.session_state["pos_last_sale"] = None
    st.session_state["demo_cart"] = []
    st.session_state["demo_applied"] = []
    st.session_state[K_CONFIRM] = False
    common.flash("Demo data reloaded. Products, stock, payment options and promotions are back to the sample set.")


def render() -> None:
    st.header("⚙️ Settings & data")

    st.markdown("#### Store")
    st.markdown(
        f"- **Store name:** {config.STORE_NAME}\n"
        f"- **Currency:** {config.CURRENCY_SYMBOL} (whole rupiah)\n"
        f"- **Tax:** {config.TAX_LABEL}, included in shelf prices\n"
        f"- **Database file:** `{config.DB_PATH}`"
    )

    st.markdown("#### How promotion T&C are enforced")
    st.markdown(
        "1. Nothing unlocks until a payment method is chosen.\n"
        "2. A promotion unlocks only when its payment method, validity dates, eligible SKUs, "
        "minimum units and minimum eligible spend are all met.\n"
        "3. Locked promotions show each missing condition and cannot be applied.\n"
        "4. Conditions are checked against list prices, so the order of clicks never changes the result.\n"
        "5. Applied promotions are re-checked on every change and again at checkout. Any that no longer qualify are removed.\n"
        "6. Two price reductions cannot be combined unless both are marked as combinable. Cashback is a reward credit "
        "and never reduces the amount collected today."
    )

    st.markdown("#### Reset demo data")
    st.warning(
        "This deletes every product, sale, stock movement and promotion in the database, "
        "then reloads the sample data from `data/seed/`."
    )
    confirmed = st.checkbox("I understand that all current data will be deleted", key=K_CONFIRM)
    st.button("Reset to demo data", type="primary", disabled=not confirmed, on_click=_reset)
