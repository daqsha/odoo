"""blibli POS & Inventory: Streamlit entry point.

Run with:   streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

import config
from database.db import init_database
from views import (
    common,
    dashboard_page,
    demo_price_page,
    inventory_page,
    pos_page,
    promo_admin_page,
    sales_page,
    settings_page,
    theme,
)

st.set_page_config(page_title=config.APP_TITLE, page_icon="🛒", layout="wide")


@st.cache_resource(show_spinner="Preparing the database…")
def _bootstrap() -> str:
    init_database()
    return str(config.DB_PATH)


_bootstrap()
theme.inject()

PAGES = {
    "🏠 Dashboard": dashboard_page.render,
    "🛒 Point of Sale": pos_page.render,
    "🏷️ Demo Price": demo_price_page.render,
    "📦 Inventory": inventory_page.render,
    "🧾 Sales & Receipts": sales_page.render,
    "🎯 Promotions & Payments": promo_admin_page.render,
    "⚙️ Settings": settings_page.render,
}

with st.sidebar:
    st.markdown(theme.brand_html(), unsafe_allow_html=True)
    page = st.radio("Navigate", list(PAGES), key="nav", label_visibility="collapsed")
    st.markdown(theme.sidebar_footer(config.DB_PATH.name), unsafe_allow_html=True)

common.show_flash()
common.show_toasts()
PAGES[page]()
