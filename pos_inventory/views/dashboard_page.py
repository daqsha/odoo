"""Dashboard: today's trading, stock health and recent activity."""

from __future__ import annotations

from datetime import date

import streamlit as st

from database.db import transaction
from logic import reports
from logic.money import money
from views import common


def render() -> None:
    today = date.today()
    st.header("🏠 Dashboard")
    st.caption(f"Today is {today:%A %d %B %Y}")

    with transaction() as conn:
        summary = reports.dashboard_summary(conn, today)

    a, b, c, d = st.columns(4)
    a.metric("Sales today", summary["sales_count"])
    b.metric("Revenue today", money(summary["sales_total"]))
    c.metric("Promotions given today", money(summary["discounts"]))
    d.metric("Cashback owed today", money(summary["cashback"]))

    e, f = st.columns(2)
    e.metric("Units on hand", summary["units_on_hand"])
    f.metric("Stock value (at cost)", money(summary["inventory_value"]))

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### Low stock")
        if summary["low_stock"]:
            st.dataframe(
                [
                    {
                        "SKU": r["sku"],
                        "Product": r["name"],
                        "On hand": r["on_hand"],
                        "Reorder at": r["reorder_level"],
                    }
                    for r in summary["low_stock"]
                ],
                hide_index=True,
            )
        else:
            st.success("Every product is above its reorder level.")
    with right:
        st.markdown("#### Top sellers (all time)")
        if summary["top_products"]:
            st.dataframe(
                [
                    {"SKU": r["sku"], "Product": r["name"], "Units": r["units"], "Revenue": money(r["revenue"])}
                    for r in summary["top_products"]
                ],
                hide_index=True,
            )
        else:
            st.info("No sales yet. Top sellers appear after the first completed sale.")

    st.markdown("#### Recent sales")
    if summary["recent_sales"]:
        st.dataframe(
            [
                {
                    "Receipt": s["receipt_no"],
                    "When": common.fmt_stamp(s["created_at"]),
                    "Paid with": s["payment_label"],
                    "Total": money(s["total_due"]),
                    "Status": "Voided" if s["status"] == "VOIDED" else "Completed",
                }
                for s in summary["recent_sales"]
            ],
            hide_index=True,
        )
    else:
        st.caption("No sales recorded yet.")
