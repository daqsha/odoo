"""Point of Sale: scan or pick products, check promotion T&Cs, take payment, print a receipt."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import streamlit as st

from database.db import transaction
from logic import catalog, inventory, payments, pos, receipts, rules
from logic import promotions as promo_store
from logic.errors import BusinessError
from logic.models import PaymentOption, Promotion
from logic.money import money
from logic.pricing import build_quote
from views import common

K_CART = "pos_cart"
K_APPLIED = "pos_applied"
K_NOTICES = "pos_notices"
K_LAST_SALE = "pos_last_sale"
K_PAYMENT = "pos_payment"
K_CUSTOMER = "pos_customer"
K_SCAN = "pos_scan"
K_SEARCH = "pos_search"
MAX_TILES = 48


@dataclass
class _Snapshot:
    products: dict[int, dict]
    on_hand: dict[int, int]
    serials: dict[int, list[str]]
    payments: list[PaymentOption]
    promotions: list[Promotion]


def _snapshot() -> _Snapshot:
    with transaction() as conn:
        return _Snapshot(
            products={p["id"]: p for p in catalog.list_products(conn)},
            on_hand=inventory.on_hand_map(conn),
            serials=inventory.in_stock_serial_map(conn),
            payments=payments.load_payment_options(conn),
            promotions=promo_store.load_promotions(conn, active_only=False),
        )


def _payment(snap: _Snapshot, code: str | None) -> PaymentOption | None:
    return next((p for p in snap.payments if p.code == code), None)


def _notice(kind: str, message: str) -> None:
    st.session_state[K_NOTICES].append((kind, message))


def _init_state() -> None:
    st.session_state.setdefault(K_CART, [])
    st.session_state.setdefault(K_APPLIED, [])
    st.session_state.setdefault(K_NOTICES, [])
    st.session_state.setdefault(K_LAST_SALE, None)


# ----- callbacks: they run before the page is rebuilt, so the cart is always current -----

def _add_to_cart(product_id: int, serial_no: str | None) -> None:
    snap = _snapshot()
    try:
        pos.cart_add(
            st.session_state[K_CART],
            product=snap.products.get(product_id),
            on_hand=snap.on_hand.get(product_id, 0),
            in_stock_serials=snap.serials.get(product_id, []),
            serial_no=serial_no,
        )
    except BusinessError as exc:
        _notice("error", str(exc))


def _add_quantity(product_id: int) -> None:
    _add_to_cart(product_id, None)


def _add_picked_unit(product_id: int) -> None:
    _add_to_cart(product_id, st.session_state.get(f"pos_pick_{product_id}"))


def _scan() -> None:
    raw = str(st.session_state.get(K_SCAN) or "").strip()
    st.session_state[K_SCAN] = ""
    if not raw:
        return
    snap = _snapshot()
    owner = {serial: pid for pid, serials in snap.serials.items() for serial in serials}
    candidates = list(dict.fromkeys([raw.upper(), re.sub(r"[\s-]", "", raw).upper()]))
    for candidate in candidates:
        if candidate in owner:
            _add_to_cart(owner[candidate], candidate)
            return
    product = next((p for p in snap.products.values() if p["sku"] == raw.upper()), None)
    if product is None:
        _notice("error", f"Nothing matches '{raw}'. Check the code, or the unit may already be sold.")
        return
    if product["tracking"] != "none":
        _notice("warning", f"{product['name']} is serial-tracked. Scan its IMEI or serial, or pick one from the list.")
        return
    _add_to_cart(product["id"], None)


def _change_qty(index: int, delta: int) -> None:
    snap = _snapshot()
    item = st.session_state[K_CART][index]
    try:
        pos.cart_change_qty(
            st.session_state[K_CART], index, delta, on_hand=snap.on_hand.get(item["product_id"], 0)
        )
    except BusinessError as exc:
        _notice("error", str(exc))


def _remove_line(index: int) -> None:
    pos.cart_remove(st.session_state[K_CART], index)


def _clear_cart() -> None:
    st.session_state[K_CART] = []
    st.session_state[K_APPLIED] = []


def _apply_promo(promo_id: int) -> None:
    snap = _snapshot()
    try:
        lines = pos.build_cart_lines(st.session_state[K_CART], snap.products)
        st.session_state[K_APPLIED] = rules.try_apply(
            snap.promotions,
            lines,
            _payment(snap, st.session_state.get(K_PAYMENT)),
            date.today(),
            st.session_state[K_APPLIED],
            promo_id,
        )
    except BusinessError as exc:
        _notice("error", str(exc))


def _remove_promo(promo_id: int) -> None:
    st.session_state[K_APPLIED] = [i for i in st.session_state[K_APPLIED] if i != promo_id]


def _checkout() -> None:
    try:
        with transaction(write=True) as conn:
            sale_id = pos.checkout(
                conn,
                items=st.session_state[K_CART],
                payment_code=st.session_state.get(K_PAYMENT),
                promotion_ids=st.session_state[K_APPLIED],
                customer_name=str(st.session_state.get(K_CUSTOMER) or ""),
            )
    except BusinessError as exc:
        _notice("error", str(exc))
        return
    st.session_state[K_LAST_SALE] = sale_id
    st.session_state[K_CART] = []
    st.session_state[K_APPLIED] = []
    st.session_state[K_CUSTOMER] = ""
    st.session_state[K_PAYMENT] = None


def _dismiss_receipt() -> None:
    st.session_state[K_LAST_SALE] = None


# ----- rendering -----

def render() -> None:
    _init_state()
    st.header("🛒 Point of Sale")

    pending = st.session_state[K_NOTICES]
    st.session_state[K_NOTICES] = []

    snap = _snapshot()
    today = date.today()

    cart, cart_messages = pos.sanitize_cart(
        st.session_state[K_CART], snap.products, snap.on_hand, snap.serials
    )
    pending.extend(("warning", message) for message in cart_messages)
    if cart != st.session_state[K_CART]:
        st.session_state[K_CART] = cart

    lines = pos.build_cart_lines(cart, snap.products)
    payment_code = st.session_state.get(K_PAYMENT)
    payment = _payment(snap, payment_code)
    if payment_code and payment is None:
        st.session_state[K_PAYMENT] = None

    # Strict rule check on every run: an applied promotion whose T&C no longer hold is removed.
    kept, removed = rules.prune_applied(snap.promotions, lines, payment, today, st.session_state[K_APPLIED])
    for name, reasons in removed:
        pending.append(("warning", f"Removed {name}: {reasons[0]}"))
    st.session_state[K_APPLIED] = [p.id for p in kept]

    evaluations = rules.evaluate_all([p for p in snap.promotions if p.active], lines, payment, today, [p.id for p in kept])
    quote = build_quote(lines, payment, kept)
    savings = common.savings_by_promo(lines, payment, kept, evaluations)

    common.show_notices(pending)
    if st.session_state[K_LAST_SALE]:
        _render_receipt(st.session_state[K_LAST_SALE])

    left, right = st.columns([3, 2], gap="large")
    with left:
        _render_catalog(snap, cart)
    with right:
        _render_checkout(snap, cart, lines, payment, quote, evaluations, savings)


def _render_receipt(sale_id: int) -> None:
    with transaction() as conn:
        sale = pos.get_sale(conn, sale_id)
    text = receipts.receipt_text(sale)
    with st.container(border=True):
        st.success(
            f"Sale {sale['receipt_no']} completed. {money(sale['total_due'])} paid by {sale['payment_label']}."
        )
        st.code(text, language=None)
        a, b, c = st.columns(3)
        a.download_button(
            "Download receipt (.txt)",
            text,
            file_name=f"{sale['receipt_no']}.txt",
            mime="text/plain",
            key="pos_dl_txt",
        )
        b.download_button(
            "Download receipt (.html)",
            receipts.receipt_html(sale),
            file_name=f"{sale['receipt_no']}.html",
            mime="text/html",
            key="pos_dl_html",
        )
        c.button("Start next sale", key="pos_next_sale", on_click=_dismiss_receipt, type="primary")


def _render_catalog(snap: _Snapshot, cart: list[dict]) -> None:
    st.subheader("Products")
    st.text_input(
        "Scan or type an SKU, IMEI or serial, then press Enter",
        key=K_SCAN,
        on_change=_scan,
        placeholder="e.g. NX-X1-128-BLK or 990012…",
    )
    search = st.text_input("Filter catalogue", key=K_SEARCH, placeholder="Name, SKU or brand")
    term = search.strip().lower()
    in_cart_serials = {item["serial_no"] for item in cart if item["serial_no"]}

    tiles = []
    for product in snap.products.values():
        if term and term not in f"{product['sku']} {product['name']} {product['brand']}".lower():
            continue
        if product["tracking"] == "none":
            in_cart = sum(i["qty"] for i in cart if i["product_id"] == product["id"] and not i["serial_no"])
            free: list[str] = []
            available = snap.on_hand.get(product["id"], 0) - in_cart
        else:
            free = [s for s in snap.serials.get(product["id"], []) if s not in in_cart_serials]
            available = len(free)
        tiles.append((product, max(available, 0), free))

    if not tiles:
        st.info("No products match that filter.")
        return
    if len(tiles) > MAX_TILES:
        st.caption(f"Showing the first {MAX_TILES} of {len(tiles)} products. Refine the filter to narrow the list.")

    columns = st.columns(3)
    for index, (product, available, free) in enumerate(tiles[:MAX_TILES]):
        with columns[index % 3].container(border=True):
            st.markdown(f"**{product['name']}**")
            st.caption(f"{product['sku']} · {money(product['price'])}")
            if available <= 0:
                st.caption("Out of stock. Quote it on the Demo Price tab.")
                st.button("Add", key=f"pos_add_{product['id']}", disabled=True)
            elif product["tracking"] != "none":
                label = "IMEI" if product["tracking"] == "imei" else "Serial no."
                st.selectbox(label, free, key=f"pos_pick_{product['id']}")
                st.button(
                    "Add unit",
                    key=f"pos_add_{product['id']}",
                    on_click=_add_picked_unit,
                    args=(product["id"],),
                )
                st.caption(f"{available} unit(s) in stock")
            else:
                st.caption(f"{available} in stock")
                st.button(
                    "Add",
                    key=f"pos_add_{product['id']}",
                    on_click=_add_quantity,
                    args=(product["id"],),
                )


def _render_checkout(snap: _Snapshot, cart, lines, payment, quote, evaluations, savings) -> None:
    st.subheader("Cart")
    if not lines:
        st.info("The cart is empty. Scan a barcode or pick products on the left.")
    for index, (item, line) in enumerate(zip(cart, lines)):
        with st.container(border=True):
            info, amount = st.columns([3, 2])
            with info:
                st.markdown(f"**{line.name}**")
                st.caption(line.sku + (f" · S/N {line.serial_no}" if line.serial_no else ""))
            with amount:
                st.markdown(f"**{money(line.line_total)}**")
                st.caption(f"{line.qty} × {money(line.unit_price)}")
            if line.serial_no is None:
                minus, plus, remove = st.columns([1, 1, 2])
                minus.button("−", key=f"pos_minus_{index}", on_click=_change_qty, args=(index, -1))
                plus.button("+", key=f"pos_plus_{index}", on_click=_change_qty, args=(index, 1))
                remove.button("Remove", key=f"pos_remove_{index}", on_click=_remove_line, args=(index,))
            else:
                st.button("Remove unit", key=f"pos_remove_{index}", on_click=_remove_line, args=(index,))

    st.text_input("Customer name (optional)", key=K_CUSTOMER)

    st.markdown("**1 · Payment method**")
    labels = {p.code: payments.payment_label(p) for p in snap.payments}
    st.selectbox(
        "Payment method",
        [None, *labels],
        key=K_PAYMENT,
        format_func=lambda code: "Choose how the customer pays…" if code is None else labels.get(code, code),
        label_visibility="collapsed",
    )

    st.markdown("**2 · Promotions**")
    if payment is None:
        st.info("Choose a payment method first. Promotions stay locked until their T&C can be checked.")
    common.promo_panel(
        evaluations,
        st.session_state[K_APPLIED],
        prefix="pos",
        on_apply=_apply_promo,
        on_remove=_remove_promo,
        savings=savings,
    )

    st.markdown("**3 · Total**")
    st.metric("Total to pay", money(quote.total_due))
    common.totals_block(quote)

    st.button(
        "✅ Complete sale",
        key="pos_checkout",
        type="primary",
        disabled=not lines or payment is None,
        on_click=_checkout,
    )
    if lines and payment is None:
        st.caption("Choose a payment method to enable checkout.")
    st.button("Clear cart", key="pos_clear", disabled=not lines, on_click=_clear_cart)
