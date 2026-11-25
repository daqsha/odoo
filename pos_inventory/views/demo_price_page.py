"""Demo Price: a what-if price calculator for sales staff.

Quote any catalogue product whether or not it is in stock or has an IMEI scanned. Test payment
methods and promotions with the same rule engine the POS uses. Nothing is sold, reserved or
deducted from inventory.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from database.db import transaction
from logic import catalog, inventory, payments, pos, pricing, receipts, rules
from logic import promotions as promo_store
from logic.errors import BusinessError
from logic.money import money
from views import common, theme

K_CART = "demo_cart"
K_APPLIED = "demo_applied"
K_PAYMENT = "demo_payment"
K_PICK = "demo_pick"
K_QTY = "demo_qty"
K_NOTICES = "demo_notices"


def _init_state() -> None:
    st.session_state.setdefault(K_CART, [])
    st.session_state.setdefault(K_APPLIED, [])
    st.session_state.setdefault(K_NOTICES, [])


def _snapshot() -> dict:
    with transaction() as conn:
        return {
            "products": {p["id"]: p for p in catalog.list_products(conn)},
            "on_hand": inventory.on_hand_map(conn),
            "payments": payments.load_payment_options(conn),
            "promotions": [p for p in promo_store.load_promotions(conn) if p.active],
        }


def _label(product: dict, on_hand: int) -> str:
    status = f"{on_hand} in stock" if on_hand > 0 else "not in stock (demo only)"
    return f"{product['name']} · {product['sku']} · {money(product['price'])} · {status}"


def _add_item() -> None:
    cart = st.session_state[K_CART]
    try:
        pos.merge_quantity(cart, int(st.session_state[K_PICK]), int(st.session_state.get(K_QTY) or 1))
    except (BusinessError, TypeError, ValueError) as exc:
        st.session_state[K_NOTICES].append(("error", str(exc) or "Choose a product first."))


def _remove_item(index: int) -> None:
    pos.cart_remove(st.session_state[K_CART], index)


def _apply_promo(promo_id: int) -> None:
    snap = _snapshot()
    try:
        lines = pos.build_cart_lines(st.session_state[K_CART], snap["products"])
        payment = next((p for p in snap["payments"] if p.code == st.session_state.get(K_PAYMENT)), None)
        st.session_state[K_APPLIED] = rules.try_apply(
            snap["promotions"], lines, payment, date.today(), st.session_state[K_APPLIED], promo_id
        )
    except BusinessError as exc:
        st.session_state[K_NOTICES].append(("error", str(exc)))


def _remove_promo(promo_id: int) -> None:
    st.session_state[K_APPLIED] = [i for i in st.session_state[K_APPLIED] if i != promo_id]


def _clear() -> None:
    st.session_state[K_CART] = []
    st.session_state[K_APPLIED] = []


def _comparison_rows(snap: dict, lines, today: date) -> list[dict]:
    """Price the same cart under every payment method, using the best eligible promotions for each."""
    rows = []
    for option in snap["payments"]:
        chosen = rules.auto_select(snap["promotions"], lines, option, today)
        quote = pricing.build_quote(lines, option, chosen)
        rows.append(
            {
                "_sort": quote.effective_total,
                "Payment method": payments.payment_label(option),
                "Promotions used": ", ".join(p.code for p in chosen) or "none",
                "Total to pay": money(quote.total_due),
                "Cashback": money(quote.cashback) if quote.cashback else "—",
                "Effective price": money(quote.effective_total),
            }
        )
    rows.sort(key=lambda row: row.pop("_sort"))
    return rows


def render() -> None:
    _init_state()
    today = date.today()
    head, _ = st.columns([3, 2], vertical_alignment="bottom")
    with head:
        theme.page_header(
            "Demo Price",
            "Quote any product for a customer on the spot. Stock and IMEIs are not checked, and nothing is sold.",
        )
    common.show_notices(st.session_state[K_NOTICES])
    st.session_state[K_NOTICES] = []

    snap = _snapshot()
    products = snap["products"]

    cart = [item for item in st.session_state[K_CART] if item["product_id"] in products]
    st.session_state[K_CART] = cart
    lines = pos.build_cart_lines(cart, products)

    payment_code = st.session_state.get(K_PAYMENT)
    payment = next((p for p in snap["payments"] if p.code == payment_code), None)
    if payment_code and payment is None:
        st.session_state[K_PAYMENT] = None

    kept, _ = rules.prune_applied(snap["promotions"], lines, payment, today, st.session_state[K_APPLIED])
    st.session_state[K_APPLIED] = [p.id for p in kept]
    evaluations = rules.evaluate_all(snap["promotions"], lines, payment, today, [p.id for p in kept])
    quote = pricing.build_quote(lines, payment, kept)
    savings = common.savings_by_promo(lines, payment, kept, evaluations)

    left, right = st.columns([5, 3], gap="large")
    with left:
        with st.container(border=True, key="card_demo_add"):
            st.markdown('<div class="section-title">Add a product</div>', unsafe_allow_html=True)
            st.selectbox(
                "Product",
                list(products),
                format_func=lambda pid: _label(products[pid], snap["on_hand"].get(pid, 0)),
                key=K_PICK,
            )
            qty_col, btn_col = st.columns([1, 1], vertical_alignment="bottom")
            qty_col.number_input("Quantity", min_value=1, max_value=99, value=1, step=1, key=K_QTY)
            btn_col.button("Add to quote", type="primary", on_click=_add_item)
            st.caption("Serial-tracked items can be quoted without scanning their IMEI or serial.")

        theme.section_title("Quote items", "Stock is not reserved")
        with st.container(border=True, key="card_demo_items"):
            if not lines:
                st.info("Add products to build a quote.")
            for index, (item, line) in enumerate(zip(cart, lines)):
                category = products[line.product_id]["category"]
                st.markdown(
                    theme.list_row(
                        emoji=theme.icon_for(category),
                        tint=theme.tint_for(category),
                        title=line.name,
                        subtitle=line.sku,
                        value=money(line.line_total),
                        value_note=f"{line.qty} × {money(line.unit_price)}",
                    ),
                    unsafe_allow_html=True,
                )
                st.button("Remove", key=f"demo_remove_{index}", on_click=_remove_item, args=(index,))
            st.button("Clear quote", key="demo_clear", disabled=not lines, on_click=_clear)

    with right:
        with st.container(border=True, key="quote_panel"):
            st.markdown('<div class="section-title">Price estimate</div>', unsafe_allow_html=True)
            st.markdown("**Payment method**")
            labels = {p.code: payments.payment_label(p) for p in snap["payments"]}
            st.selectbox(
                "Payment method",
                [None, *labels],
                key=K_PAYMENT,
                format_func=lambda code: "Choose how the customer pays…" if code is None else labels.get(code, code),
                label_visibility="collapsed",
            )

            st.markdown("**Promotions (T&C checked)**")
            if payment is None:
                st.info("Choose a payment method first. Promotions stay locked until their T&C can be checked.")
            common.promo_panel(
                evaluations,
                st.session_state[K_APPLIED],
                prefix="demo",
                on_apply=_apply_promo,
                on_remove=_remove_promo,
                savings=savings,
            )

            st.markdown(theme.total_row("Customer pays today", money(quote.total_due)), unsafe_allow_html=True)
            common.totals_block(quote)
            if lines:
                with st.expander("Copy-ready estimate for the customer"):
                    st.code(receipts.estimate_text(quote), language=None)

            st.markdown("**Compare payment methods**")
            if not lines:
                st.caption("Add products to compare every payment method side by side.")
            else:
                st.caption(
                    "Each row uses the best promotions that payment method qualifies for. Lowest effective price first."
                )
                st.dataframe(_comparison_rows(snap, lines, today), hide_index=True)
