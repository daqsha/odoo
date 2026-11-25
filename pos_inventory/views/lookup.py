"""Stock lookup shared by Inventory and Point of Sale.

Type a full or partial IMEI/serial, an SKU, a product name or a brand. Results show every
matching unit with its exact status (available, sold, written off) and, for an exact
IMEI/serial, a detail card with the unit's full movement history.
"""

from __future__ import annotations

from typing import Callable, Collection

import streamlit as st

from database.db import transaction
from logic import inventory
from logic.money import money
from views import common, theme

STATUS_BADGES = {"in_stock": ("Available", "ok"), "sold": ("Sold", "info"), "written_off": ("Written off", "bad")}
STOCK_BADGES = {"ok": ("In stock", "ok"), "low": ("Low stock", "warn"), "out": ("Out of stock", "bad")}
MOVE_LABELS = {
    "STOCK_IN": "Received into stock",
    "STOCK_OUT": "Written off",
    "ADJUSTMENT": "Count adjustment",
    "SALE": "Sold",
    "VOID_SALE": "Returned to stock (sale voided)",
}

OnAdd = Callable[[int, "str | None"], None]


def _unit_detail(unit: dict) -> str:
    if unit["status"] == "sold":
        customer = unit["customer_name"] or "walk-in customer"
        return f"Sold {common.fmt_stamp(unit['sold_at'])} · receipt {unit['receipt_no']} · {customer}"
    if unit["status"] == "written_off":
        return f"Written off · {unit['writeoff_note'] or 'no reason recorded'}"
    return f"In stock since {common.fmt_stamp(unit['received_at'])}"


def _unit_row(unit: dict) -> str:
    label, kind = STATUS_BADGES.get(unit["status"], (unit["status"], "info"))
    kind_label = "IMEI" if unit["tracking"] == "imei" else "S/N"
    return (
        '<div class="lrow">'
        f'<div class="lthumb" style="background:{theme.tint_for(unit["category"])}">{theme.icon_for(unit["category"])}</div>'
        '<div class="lmain">'
        f'<div class="lname"><span class="mono">{kind_label} {theme.esc(unit["serial_no"])}</span></div>'
        f'<div class="lsub">{theme.esc(unit["name"])} · {theme.esc(unit["sku"])}</div>'
        f'<div class="lsub">{theme.esc(_unit_detail(unit))}</div>'
        "</div>"
        f'<div class="lend">{theme.badge(label, kind)}<div class="lsub">{theme.esc(money(unit["price"]))}</div></div>'
        "</div>"
    )


def _product_row(product: dict) -> str:
    label, kind = STOCK_BADGES[product["stock_state"]]
    if product["tracking"] == "none":
        detail = f"{product['on_hand']} on hand · {product['qty_sold']} sold"
    else:
        detail = (
            f"{product['units_available']} available · {product['units_sold']} sold"
            + (f" · {product['units_written_off']} written off" if product["units_written_off"] else "")
        )
    if not product["active"]:
        detail += " · inactive"
    return (
        '<div class="lrow">'
        f'<div class="lthumb" style="background:{theme.tint_for(product["category"])}">{theme.icon_for(product["category"])}</div>'
        '<div class="lmain">'
        f'<div class="lname">{theme.esc(product["name"])}</div>'
        f'<div class="lsub">{theme.esc(product["sku"])} · {theme.esc(product["category"])} · {theme.esc(money(product["price"]))}</div>'
        f'<div class="lsub">{theme.esc(detail)}</div>'
        "</div>"
        f'<div class="lend">{theme.badge(label, kind)}<div class="lsub">reorder at {product["reorder_level"]}</div></div>'
        "</div>"
    )


def _hero(unit: dict, history: list[dict]) -> str:
    label, kind = STATUS_BADGES.get(unit["status"], (unit["status"], "info"))
    kind_label = "IMEI" if unit["tracking"] == "imei" else "Serial number"
    facts = [("Product", unit["name"]), ("SKU", unit["sku"]), ("Price", money(unit["price"])),
             ("Received", common.fmt_stamp(unit["received_at"]))]
    if unit["status"] == "sold":
        facts += [("Receipt", unit["receipt_no"] or "-"), ("Sold", common.fmt_stamp(unit["sold_at"])),
                  ("Customer", unit["customer_name"] or "Walk-in")]
    elif unit["status"] == "written_off":
        facts.append(("Reason", unit["writeoff_note"] or "-"))
    fact_html = "".join(
        f'<div class="fact"><div class="k">{theme.esc(k)}</div><div class="v">{theme.esc(v)}</div></div>' for k, v in facts
    )
    events = "".join(
        f'<div class="ev">{theme.esc(MOVE_LABELS.get(m["move_type"], m["move_type"]))}'
        f'<small>{theme.esc(common.fmt_stamp(m["created_at"]))}'
        f'{" · " + theme.esc(m["reference"]) if m["reference"] else ""}'
        f'{" · " + theme.esc(m["note"]) if m["note"] else ""}</small></div>'
        for m in history
    )
    return (
        '<div class="unit-hero"><div class="top">'
        f'<div><div class="meta">{theme.esc(kind_label)} · exact match</div>'
        f'<div class="sn mono">{theme.esc(unit["serial_no"])}</div></div>'
        f"{theme.badge(label, kind)}</div>"
        f'<div class="facts">{fact_html}</div>'
        f'<div class="tl">{events}</div></div>'
    )


def render(
    prefix: str,
    *,
    on_add: OnAdd | None = None,
    in_cart_serials: Collection[str] = (),
    placeholder: str = "Scan or type an IMEI, serial, SKU or product name, then press Enter",
) -> None:
    query = st.text_input(
        "Look up stock",
        key=f"{prefix}_lookup",
        placeholder=placeholder,
        label_visibility="collapsed",
    )
    text = (query or "").strip()
    if not text:
        st.markdown(
            theme.empty_state(
                "🔎",
                "Find any unit instantly",
                "Full or partial IMEI or serial, an SKU, a product name or a brand.",
            ),
            unsafe_allow_html=True,
        )
        return

    with transaction() as conn:
        result = inventory.lookup(conn, text)
        exact = result["exact_unit"]
        history = inventory.serial_history(conn, exact["serial_no"]) if exact else []
    units, products = result["units"], result["products"]

    if not units and not products:
        st.markdown(
            theme.empty_state("🤷", f"No stock matches “{text}”", "Check the number, or search by product name or SKU."),
            unsafe_allow_html=True,
        )
        return

    st.caption(f"{len(units)} unit(s) and {len(products)} product(s) match “{text}”")

    if exact:
        st.markdown(_hero(exact, history), unsafe_allow_html=True)
        _add_button(prefix, on_add, exact, in_cart_serials, key=f"{prefix}_lkadd_x_{exact['serial_no']}")

    if products:
        theme.section_title("Products", f"{len(products)}")
        for product in products:
            st.markdown(_product_row(product), unsafe_allow_html=True)
            if on_add and product["tracking"] == "none" and product["active"] and product["on_hand"] > 0:
                st.button(
                    "Add 1 to order",
                    key=f"{prefix}_lkadd_p_{product['id']}",
                    on_click=on_add,
                    args=(product["id"], None),
                )

    others = [u for u in units if not exact or u["serial_no"] != exact["serial_no"]]
    if others:
        theme.section_title("Units", f"{len(others)}")
        for unit in others:
            st.markdown(_unit_row(unit), unsafe_allow_html=True)
            _add_button(prefix, on_add, unit, in_cart_serials, key=f"{prefix}_lkadd_u_{unit['serial_no']}")


def _add_button(prefix: str, on_add: OnAdd | None, unit: dict, in_cart: Collection[str], *, key: str) -> None:
    if not on_add or unit["status"] != "in_stock":
        return
    if unit["serial_no"] in in_cart:
        st.caption("✔ Already in this order")
        return
    st.button("Add unit to order", key=key, type="primary", on_click=on_add, args=(unit["product_id"], unit["serial_no"]))
