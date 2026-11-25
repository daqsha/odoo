"""Sales & receipts: browse completed sales, reprint or download a receipt, and void a sale."""

from __future__ import annotations

import streamlit as st

from database.db import transaction
from logic import pos, receipts
from logic.errors import BusinessError
from logic.money import money
from views import common


def _void(sale_id: int, receipt_no: str) -> None:
    reason = str(st.session_state.get(f"void_reason_{sale_id}") or "")
    try:
        with transaction(write=True) as conn:
            pos.void_sale(conn, sale_id=sale_id, reason=reason)
    except BusinessError as exc:
        common.flash(str(exc), "error")
        return
    common.flash(f"Sale {receipt_no} voided. Its items are back in stock.")


def render() -> None:
    st.header("🧾 Sales & receipts")
    with transaction() as conn:
        sales = pos.list_sales(conn, limit=300)

    if not sales:
        st.info("No sales yet. Complete a sale on the Point of Sale tab.")
        return

    st.dataframe(
        [
            {
                "Receipt": s["receipt_no"],
                "Date & time": common.fmt_stamp(s["created_at"]),
                "Customer": s["customer_name"] or "Walk-in",
                "Paid with": s["payment_label"],
                "Total": money(s["total_due"]),
                "Promotions": money(s["promo_discount"]) if s["promo_discount"] else "",
                "Status": "Voided" if s["status"] == "VOIDED" else "Completed",
            }
            for s in sales
        ],
        hide_index=True,
    )

    labels = {
        s["id"]: f"{s['receipt_no']} · {common.fmt_stamp(s['created_at'])} · {money(s['total_due'])}"
        + (" · voided" if s["status"] == "VOIDED" else "")
        for s in sales
    }
    sale_id = st.selectbox("Open a receipt", list(labels), format_func=lambda x: labels[x], key="sales_pick")
    with transaction() as conn:
        sale = pos.get_sale(conn, sale_id)

    text = receipts.receipt_text(sale)
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.code(text, language=None)
        a, b = st.columns(2)
        a.download_button(
            "Download receipt (.txt)",
            text,
            file_name=f"{sale['receipt_no']}.txt",
            mime="text/plain",
            key=f"dl_txt_{sale_id}",
        )
        b.download_button(
            "Download receipt (.html)",
            receipts.receipt_html(sale),
            file_name=f"{sale['receipt_no']}.html",
            mime="text/html",
            key=f"dl_html_{sale_id}",
        )

    with right:
        st.markdown("#### Void this sale")
        if sale["status"] == "VOIDED":
            st.warning(f"This sale was voided on {common.fmt_stamp(sale['voided_at'])}. Reason: {sale['void_reason']}")
            return
        st.caption("Use this for a mistake or a returned unit. Items go back into stock and the sale is marked voided.")
        st.text_input("Reason for voiding", key=f"void_reason_{sale_id}", placeholder="e.g. customer returned item")
        confirmed = st.checkbox("I understand the sale will be marked as voided", key=f"void_confirm_{sale_id}")
        st.button(
            "Void sale and restore stock",
            key=f"void_btn_{sale_id}",
            disabled=not confirmed,
            on_click=_void,
            args=(sale_id, sale["receipt_no"]),
        )
