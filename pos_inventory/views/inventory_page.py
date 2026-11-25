"""Inventory: stock overview, stock-in, stock-out and count adjustments, catalogue maintenance, movement history."""

from __future__ import annotations

import streamlit as st

from database.db import transaction
from logic import catalog, inventory
from logic.catalog import TRACKING_LABELS
from logic.errors import BusinessError
from logic.identifiers import split_identifiers
from logic.inventory import STOCK_OUT_REASONS
from logic.money import money
from views import common

K_VERSION = "inv_form_version"
MOVE_LABELS = {
    "STOCK_IN": "Stock-in",
    "STOCK_OUT": "Stock-out",
    "ADJUSTMENT": "Count adjustment",
    "SALE": "Sale",
    "VOID_SALE": "Sale voided (returned)",
}


def _version() -> int:
    return st.session_state.setdefault(K_VERSION, 0)


def _done(message: str) -> None:
    """Show a success message on the next run and reset the form widgets."""
    st.session_state[K_VERSION] = _version() + 1
    common.flash(message)
    st.rerun()


def _product_name(products: dict[int, dict], pid: int) -> str:
    product = products[pid]
    return f"{product['sku']} · {product['name']}"


def render() -> None:
    st.header("📦 Inventory")
    overview_tab, stock_in_tab, stock_out_tab, catalogue_tab, history_tab = st.tabs(
        ["Stock overview", "Stock-in", "Stock-out & adjustments", "Catalogue", "Movement history"]
    )
    with overview_tab:
        _overview()
    with stock_in_tab:
        _stock_in()
    with stock_out_tab:
        _stock_out()
    with catalogue_tab:
        _catalogue()
    with history_tab:
        _history()


# ----- stock overview -----

def _overview() -> None:
    with transaction() as conn:
        categories = catalog.list_categories(conn)
    left, right = st.columns([3, 2])
    search = left.text_input("Search", placeholder="SKU, name or brand", key="inv_search")
    category = right.selectbox("Category", ["All categories", *categories], key="inv_category")

    with transaction() as conn:
        rows = inventory.stock_overview(
            conn, search=search, category=None if category == "All categories" else category
        )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Products", len(rows))
    m2.metric("Units on hand", sum(r["on_hand"] for r in rows))
    m3.metric("Stock value (at cost)", money(sum(r["value"] for r in rows)))
    m4.metric("Low-stock items", sum(1 for r in rows if r["low_stock"]))

    table = []
    for r in rows:
        if r["on_hand"] <= 0:
            status = "🔴 Out of stock"
        elif r["low_stock"]:
            status = "🟠 Low"
        else:
            status = "🟢 OK"
        table.append(
            {
                "SKU": r["sku"],
                "Product": r["name"],
                "Category": r["category"],
                "Tracking": TRACKING_LABELS[r["tracking"]],
                "On hand": r["on_hand"],
                "Reorder at": r["reorder_level"],
                "Status": status,
                "Cost": money(r["cost"]),
                "Price": money(r["price"]),
                "Active": "yes" if r["active"] else "no",
            }
        )
    st.dataframe(table, hide_index=True)

    tracked = [r for r in rows if r["tracking"] != "none"]
    st.markdown("#### Serial / IMEI units in stock")
    if not tracked:
        st.info("No serial or IMEI tracked products match this filter.")
        return
    options = {r["id"]: f"{r['sku']} · {r['name']}" for r in tracked}
    pid = st.selectbox("Product", list(options), format_func=lambda x: options[x], key="inv_serial_product")
    with transaction() as conn:
        units = inventory.serial_details(conn, pid)
    if units:
        st.dataframe(
            [{"Serial / IMEI": u["serial_no"], "Received": common.fmt_stamp(u["received_at"])} for u in units],
            hide_index=True,
        )
    else:
        st.info("No units of this product are in stock.")


# ----- stock-in -----

def _stock_in() -> None:
    version = _version()
    with transaction() as conn:
        products = {p["id"]: p for p in catalog.list_products(conn)}
    if not products:
        st.info("Add a product in the Catalogue tab first.")
        return

    pid = st.selectbox(
        "Product",
        list(products),
        format_func=lambda x: _product_name(products, x),
        key=f"si_product_{version}",
    )
    product = products[pid]
    tracked = product["tracking"] != "none"
    label = "IMEI" if product["tracking"] == "imei" else "serial number"

    with st.form(f"stock_in_form_{version}"):
        if tracked:
            serial_text = st.text_area(
                f"{label.capitalize()}s received (one per line or comma-separated)",
                key=f"si_serials_{version}",
                height=150,
                help="IMEIs must be 15 digits and pass the checksum. Serial numbers are letters, digits or dashes.",
            )
        else:
            qty = st.number_input("Quantity received", min_value=1, value=1, step=1, key=f"si_qty_{version}")
        unit_cost = st.number_input(
            "Unit cost (Rp)", min_value=0, value=int(product["cost"]), step=1000, key=f"si_cost_{version}"
        )
        reference = st.text_input("Reference (PO or delivery note)", key=f"si_ref_{version}")
        note = st.text_input("Note (optional)", key=f"si_note_{version}")
        submitted = st.form_submit_button("Receive stock", type="primary")

    if submitted:
        try:
            with transaction(write=True) as conn:
                if tracked:
                    count = inventory.receive_stock(
                        conn,
                        product_id=pid,
                        serials=split_identifiers(serial_text),
                        unit_cost=int(unit_cost),
                        reference=reference.strip(),
                        note=note.strip(),
                    )
                else:
                    count = inventory.receive_stock(
                        conn,
                        product_id=pid,
                        qty=int(qty),
                        unit_cost=int(unit_cost),
                        reference=reference.strip(),
                        note=note.strip(),
                    )
        except BusinessError as exc:
            st.error(str(exc))
        else:
            _done(f"Received {count} unit(s) of {product['name']}.")


# ----- stock-out and adjustments -----

def _stock_out() -> None:
    version = _version()
    with transaction() as conn:
        products = {p["id"]: p for p in catalog.list_products(conn)}
    if not products:
        st.info("No products yet.")
        return

    pid = st.selectbox(
        "Product",
        list(products),
        format_func=lambda x: _product_name(products, x),
        key=f"so_product_{version}",
    )
    product = products[pid]

    if product["tracking"] != "none":
        label = "IMEI" if product["tracking"] == "imei" else "serial number"
        with transaction() as conn:
            serials = inventory.in_stock_serials(conn, pid)
        if not serials:
            st.info("No units of this product are in stock.")
            return
        with st.form(f"stock_out_serial_form_{version}"):
            chosen = st.multiselect(f"{label.capitalize()}s to write off", serials, key=f"so_serials_{version}")
            reason = st.selectbox("Reason", STOCK_OUT_REASONS, key=f"so_reason_{version}")
            note = st.text_input("Note (optional)", key=f"so_note_{version}")
            submitted = st.form_submit_button("Write off selected units", type="primary")
        if submitted:
            try:
                with transaction(write=True) as conn:
                    count = inventory.stock_out(
                        conn, product_id=pid, reason=reason, serials=chosen, note=note.strip()
                    )
            except BusinessError as exc:
                st.error(str(exc))
            else:
                _done(f"Wrote off {count} unit(s) of {product['name']}.")
        return

    with transaction() as conn:
        available = inventory.on_hand(conn, pid)
    st.caption(f"Currently on hand: **{available}**")
    mode = st.radio(
        "What do you need to record?",
        ["Stock-out (damaged, lost, internal use)", "Count adjustment (set the counted quantity)"],
        key=f"so_mode_{version}",
    )

    if mode.startswith("Stock-out"):
        with st.form(f"stock_out_form_{version}"):
            qty = st.number_input("Quantity to remove", min_value=1, value=1, step=1, key=f"so_qty_{version}")
            reason = st.selectbox("Reason", STOCK_OUT_REASONS, key=f"so_reason_{version}")
            note = st.text_input("Note (optional)", key=f"so_note_{version}")
            submitted = st.form_submit_button("Record stock-out", type="primary")
        if submitted:
            try:
                with transaction(write=True) as conn:
                    inventory.stock_out(conn, product_id=pid, reason=reason, qty=int(qty), note=note.strip())
            except BusinessError as exc:
                st.error(str(exc))
            else:
                _done(f"Removed {int(qty)} unit(s) of {product['name']} from stock.")
    else:
        with st.form(f"count_form_{version}"):
            counted = st.number_input(
                "Physically counted quantity", min_value=0, value=available, step=1, key=f"ct_qty_{version}"
            )
            reason = st.text_input("Reason", value="Stock count", key=f"ct_reason_{version}")
            note = st.text_input("Note (optional)", key=f"ct_note_{version}")
            submitted = st.form_submit_button("Apply count adjustment", type="primary")
        if submitted:
            try:
                with transaction(write=True) as conn:
                    diff = inventory.adjust_count(
                        conn, product_id=pid, counted_qty=int(counted), reason=reason, note=note.strip()
                    )
            except BusinessError as exc:
                st.error(str(exc))
            else:
                _done(f"Adjusted {product['name']} by {diff:+d} unit(s).")


# ----- catalogue -----

def _catalogue() -> None:
    version = _version()
    with transaction() as conn:
        products = catalog.list_products(conn, active_only=False)
        categories = catalog.list_categories(conn)

    st.dataframe(
        [
            {
                "SKU": p["sku"],
                "Name": p["name"],
                "Brand": p["brand"],
                "Category": p["category"],
                "Tracking": TRACKING_LABELS[p["tracking"]],
                "Cost": money(p["cost"]),
                "Price": money(p["price"]),
                "Reorder at": p["reorder_level"],
                "Active": "yes" if p["active"] else "no",
            }
            for p in products
        ],
        hide_index=True,
    )

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### Add product")
        with st.form(f"new_product_form_{version}"):
            sku = st.text_input("SKU", placeholder="e.g. NX-X1-128-BLK", key=f"np_sku_{version}")
            name = st.text_input("Name", key=f"np_name_{version}")
            brand = st.text_input("Brand", key=f"np_brand_{version}")
            category = st.text_input(
                "Category", value=categories[0] if categories else "General", key=f"np_cat_{version}"
            )
            tracking = st.selectbox(
                "Tracking", list(TRACKING_LABELS), format_func=TRACKING_LABELS.get, key=f"np_track_{version}"
            )
            cost = st.number_input("Cost (Rp)", min_value=0, value=0, step=1000, key=f"np_cost_{version}")
            price = st.number_input("Selling price (Rp)", min_value=0, value=0, step=1000, key=f"np_price_{version}")
            reorder = st.number_input("Reorder level", min_value=0, value=0, step=1, key=f"np_reorder_{version}")
            submitted = st.form_submit_button("Create product", type="primary")
        if submitted:
            try:
                with transaction(write=True) as conn:
                    catalog.create_product(
                        conn,
                        sku=sku,
                        name=name,
                        brand=brand,
                        category=category,
                        tracking=tracking,
                        cost=int(cost),
                        price=int(price),
                        reorder_level=int(reorder),
                    )
            except BusinessError as exc:
                st.error(str(exc))
            else:
                _done(f"Created product {sku.strip().upper()}. Receive its stock in the Stock-in tab.")

    with right:
        st.markdown("#### Edit product")
        if not products:
            st.info("No products yet.")
            return
        by_id = {p["id"]: p for p in products}
        pid = st.selectbox(
            "Product",
            list(by_id),
            format_func=lambda x: f"{by_id[x]['sku']} · {by_id[x]['name']}",
            key=f"ep_product_{version}",
        )
        product = by_id[pid]
        with st.form(f"edit_product_form_{version}_{pid}"):
            name = st.text_input("Name", value=product["name"], key=f"ep_name_{version}_{pid}")
            brand = st.text_input("Brand", value=product["brand"], key=f"ep_brand_{version}_{pid}")
            category = st.text_input("Category", value=product["category"], key=f"ep_cat_{version}_{pid}")
            price = st.number_input(
                "Selling price (Rp)", min_value=0, value=int(product["price"]), step=1000, key=f"ep_price_{version}_{pid}"
            )
            cost = st.number_input(
                "Cost (Rp)", min_value=0, value=int(product["cost"]), step=1000, key=f"ep_cost_{version}_{pid}"
            )
            reorder = st.number_input(
                "Reorder level",
                min_value=0,
                value=int(product["reorder_level"]),
                step=1,
                key=f"ep_reorder_{version}_{pid}",
            )
            active = st.checkbox("Active (shown in POS and Demo Price)", value=bool(product["active"]), key=f"ep_active_{version}_{pid}")
            submitted = st.form_submit_button("Save changes")
        if submitted:
            try:
                with transaction(write=True) as conn:
                    catalog.update_product(
                        conn,
                        pid,
                        name=name,
                        brand=brand,
                        category=category,
                        price=int(price),
                        cost=int(cost),
                        reorder_level=int(reorder),
                        active=active,
                    )
            except BusinessError as exc:
                st.error(str(exc))
            else:
                _done(f"Saved {product['sku']}.")
        st.caption(
            "SKU and tracking mode are fixed once a product exists. Deactivate products instead of deleting them, "
            "so sales history stays intact."
        )


# ----- movement history -----

def _history() -> None:
    with transaction() as conn:
        products = {p["id"]: p for p in catalog.list_products(conn, active_only=False)}
    pid = st.selectbox(
        "Product",
        [None, *products],
        format_func=lambda x: "All products" if x is None else _product_name(products, x),
        key="hist_product",
    )
    with transaction() as conn:
        moves = inventory.movement_history(conn, product_id=pid, limit=300)
    st.dataframe(
        [
            {
                "When": common.fmt_stamp(m["created_at"]),
                "SKU": m["sku"],
                "Movement": MOVE_LABELS.get(m["move_type"], m["move_type"]),
                "Qty": f"{m['qty']:+d}",
                "Serial / IMEI": m["serial_no"] or "",
                "Reference": m["reference"],
                "Note": m["note"],
                "Unit cost": money(m["unit_cost"]) if m["unit_cost"] else "",
            }
            for m in moves
        ],
        hide_index=True,
    )
    st.caption("Latest 300 movements. Every on-hand number in the app is the sum of these rows.")
