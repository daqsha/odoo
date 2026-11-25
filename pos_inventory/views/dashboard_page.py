"""Overview: greeting, popular products, best sellers, statistics and a sticky side panel."""

from __future__ import annotations

from datetime import date

import streamlit as st

import config
from database.db import transaction
from logic import catalog, inventory, pos, reports
from logic.errors import BusinessError
from logic.money import money
from views import common, theme

K_CATEGORY = "dash_category"
K_SEARCH = "dash_search"
POS_PAGE = "🛒 Point of Sale"


def _open_pos() -> None:
    st.session_state["nav"] = POS_PAGE


def _order(product_id: int) -> None:
    """'Order' on a popular product: quantity items go straight into the cart. Serialised items
    open Point of Sale filtered to that product, so the cashier picks the exact IMEI or serial."""
    with transaction() as conn:
        product = catalog.get_product(conn, product_id)
        on_hand = inventory.on_hand(conn, product_id)
    if product is None:
        common.flash("That product is no longer available.", "error")
    elif product["tracking"] == "none":
        try:
            pos.cart_add(st.session_state.setdefault("pos_cart", []), product=product, on_hand=on_hand)
        except BusinessError as exc:
            common.flash(str(exc), "error")
        else:
            common.flash(f"Added {product['name']} to the order.")
    else:
        st.session_state["pos_search"] = product["sku"]
        common.flash(f"Pick the IMEI or serial for {product['name']} in Point of Sale.", "info")
    st.session_state["nav"] = POS_PAGE


def render() -> None:
    today = date.today()
    with transaction() as conn:
        summary = reports.dashboard_summary(conn, today)
        catalogue = reports.product_sales(conn)
        on_hand = inventory.on_hand_map(conn)
        categories = catalog.list_categories(conn)

    category_of = {p["sku"]: p["category"] for p in catalogue}

    head, search_col = st.columns([3, 2], vertical_alignment="bottom")
    with head:
        theme.page_header(
            f"{theme.greeting()}, {config.CASHIER_NAME}",
            f"{config.STORE_NAME} · {today:%A, %d %B %Y}",
        )
    with search_col:
        search = st.text_input(
            "Search products",
            key=K_SEARCH,
            placeholder="Search products by name or SKU",
            label_visibility="collapsed",
        )

    selected = st.pills("Category", ["All", *categories], default="All", key=K_CATEGORY, label_visibility="collapsed")
    category = None if selected in (None, "All") else selected

    term = (search or "").strip().lower()
    popular: list[dict] = []
    for product in catalogue:
        stock = on_hand.get(product["id"], 0)
        if stock <= 0:
            continue
        if category and product["category"] != category:
            continue
        if term and term not in f"{product['sku']} {product['name']} {product['brand']}".lower():
            continue
        popular.append({**product, "on_hand": stock})
    popular = popular[:3]

    main, side = st.columns([3, 1.35], gap="large")
    with main:
        theme.section_title("Popular Orders")
        if popular:
            cards = st.columns(3)
            for column, product in zip(cards, popular):
                with column.container(border=True, key=f"card_popular_{product['id']}"):
                    st.markdown(
                        theme.product_card(product, f"{product['on_hand']} in stock · {product['units']} sold"),
                        unsafe_allow_html=True,
                    )
                    st.button(
                        "Order",
                        key=f"dash_order_{product['id']}",
                        type="primary",
                        on_click=_order,
                        args=(product["id"],),
                    )
        else:
            st.info("No in-stock products match this search or category.")

        best, stats = st.columns([1, 1.2], gap="large")
        with best:
            theme.section_title("Best Seller")
            with st.container(border=True, key="card_best"):
                if summary["top_products"]:
                    st.markdown(
                        "".join(
                            theme.list_row(
                                emoji=theme.icon_for(category_of.get(row["sku"], "")),
                                tint=theme.tint_for(category_of.get(row["sku"], "")),
                                title=row["name"],
                                subtitle=f"{row['sku']} · {row['units']} sold",
                                value=money(row["revenue"]),
                                value_note="revenue",
                            )
                            for row in summary["top_products"]
                        ),
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("No sales yet. Best sellers appear after the first completed sale.")

        with stats:
            theme.section_title("Statistics")
            st.markdown(
                theme.kpi_grid(
                    [
                        theme.kpi("Sales today", summary["sales_count"], accent=True),
                        theme.kpi("Units on hand", summary["units_on_hand"]),
                        theme.kpi("Low-stock items", len(summary["low_stock"])),
                        theme.kpi("Stock value (cost)", money(summary["inventory_value"])),
                    ]
                ),
                unsafe_allow_html=True,
            )
            with st.container(border=True, key="card_revenue"):
                st.markdown(
                    f'<div class="k" style="color:#8A8FA3;font-size:.8rem">Revenue today</div>'
                    f'<div style="font-size:1.6rem;font-weight:700;letter-spacing:-.02em">{theme.esc(money(summary["sales_total"]))}</div>'
                    f'<div style="color:#8A8FA3;font-size:.78rem">Promotions {theme.esc(money(summary["discounts"]))} · '
                    f'Cashback owed {theme.esc(money(summary["cashback"]))}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(theme.revenue_chart(summary["daily"]), unsafe_allow_html=True)
                st.caption("Revenue, last 7 days")

    with side:
        with st.container(border=True, key="overview_side"):
            st.markdown(
                theme.profile_html(config.STORE_NAME, f"{config.CASHIER_NAME} · on duty"),
                unsafe_allow_html=True,
            )
            st.button("Open Point of Sale", key="dash_open_pos", type="primary", on_click=_open_pos)

            theme.section_title("Recent orders")
            if summary["recent_sales"]:
                st.markdown(
                    "".join(
                        theme.list_row(
                            emoji="🧾",
                            tint="#EEF0FF",
                            title=sale["receipt_no"] or "-",
                            subtitle=f"{common.fmt_stamp(sale['created_at'])} · {sale['payment_label']}",
                            value=money(sale["total_due"]),
                            value_note="voided" if sale["status"] == "VOIDED" else "completed",
                        )
                        for sale in summary["recent_sales"]
                    ),
                    unsafe_allow_html=True,
                )
            else:
                st.caption("No sales recorded yet.")

            theme.section_title("Stock alerts")
            if summary["low_stock"]:
                st.markdown(
                    "".join(
                        theme.list_row(
                            emoji="⚠️",
                            tint="#FFF1E6",
                            title=row["name"],
                            subtitle=f"{row['sku']} · reorder at {row['reorder_level']}",
                            value=f"{row['on_hand']} left",
                            value_note="restock soon",
                        )
                        for row in summary["low_stock"]
                    ),
                    unsafe_allow_html=True,
                )
            else:
                st.success("Every product is above its reorder level.")
