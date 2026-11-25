"""Visual theme: global CSS and the small HTML building blocks shared by the pages.

Every piece of dynamic text goes through esc() before it reaches the markup. Markup strings
are kept on one line with no leading indentation, because Markdown would otherwise treat
indented lines as code blocks.
"""

from __future__ import annotations

import html
from datetime import datetime

import streamlit as st

import config
from logic.money import money

PRIMARY = "#4D0CA6"
ACCENT = "#E4604F"

CATEGORY_ICONS = {
    "Smartphones": "📱",
    "Tablets": "📲",
    "Laptops": "💻",
    "Wearables": "⌚",
    "Audio": "🎧",
    "Cameras": "📷",
    "Accessories": "🔌",
    "Smart Home": "💡",
}
CATEGORY_TINTS = {
    "Smartphones": "#EEE8FF",
    "Tablets": "#FFE9E4",
    "Laptops": "#E4F1FF",
    "Wearables": "#E6F9EE",
    "Audio": "#FFF3D9",
    "Cameras": "#F1E9FF",
    "Accessories": "#E8F7F9",
    "Smart Home": "#FFF7D6",
}
DEFAULT_ICON = "🛍️"
DEFAULT_TINT = "#EEF0F7"

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap');

:root {
  --primary: #4D0CA6;
  --primary-deep: #3A0A7E;
  --accent: #E4604F;
  --ink: #1E1B2E;
  --muted: #8A8FA3;
  --line: #EEEBF6;
  --card: #FFFFFF;
  --page: #F6F6FB;
  --shadow: 0 10px 30px rgba(45, 25, 110, 0.07);
}

html, body, .stApp, button, input, select, textarea {
  font-family: 'Poppins', 'Segoe UI', system-ui, sans-serif !important;
}
.stApp { background: var(--page); color: var(--ink); }
.block-container { padding: 1.6rem 2.2rem 4rem; max-width: 1520px; }
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stAppDeployButton"] { visibility: hidden; height: 0; }
header[data-testid="stHeader"] { background: transparent; }

/* ---------- sidebar: purple rail with a white pill for the active page ----------
   Selectors follow Streamlit's radio markup: each option is label[data-testid="stRadioOption"],
   the active one carries data-selected="true", and its first inner div is the hidden radio dot. */
section[data-testid="stSidebar"] { background: var(--primary); border-right: none; }
section[data-testid="stSidebar"] > div { background: transparent; }
section[data-testid="stSidebar"] .stRadio > label { display: none; }
section[data-testid="stSidebar"] div[role="radiogroup"] { gap: 6px; }
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] {
  position: relative; width: 100%; margin: 0; padding: .65rem .95rem;
  border-radius: 14px; cursor: pointer; transition: background .15s ease;
}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] > div > div:first-child { display: none; }
section[data-testid="stSidebar"] label[data-testid="stRadioOption"]:hover { background: rgba(255,255,255,.12); }
section[data-testid="stSidebar"] label[data-testid="stRadioOption"] p {
  color: #EFE9FF !important; font-size: .95rem; font-weight: 500; margin: 0;
}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] {
  background: #FFFFFF; box-shadow: 0 8px 20px rgba(10, 0, 40, .22);
}
section[data-testid="stSidebar"] label[data-testid="stRadioOption"][data-selected="true"] p {
  color: var(--primary) !important; font-weight: 600;
}
.brand { display: flex; align-items: center; gap: .7rem; padding: .2rem .4rem 1.6rem; }
.brand-mark {
  width: 40px; height: 40px; border-radius: 13px; background: var(--accent); color: #fff;
  font-weight: 700; font-size: 1.3rem; display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 16px rgba(228, 96, 79, .45);
}
.brand-name { font-size: 1.55rem; font-weight: 700; color: #FFFFFF; letter-spacing: -.02em; line-height: 1; }
.brand-sub { font-size: .72rem; color: #CDBFF0; margin-top: 3px; }
.side-foot {
  margin-top: 2rem; padding: .95rem 1rem; border-radius: 16px;
  background: rgba(255,255,255,.10); color: #EDE6FF; font-size: .8rem; line-height: 1.5;
}
.side-foot b { color: #FFFFFF; font-weight: 600; }

/* ---------- page heading ---------- */
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin: 0 0 1.2rem; }
.page-head h1 { font-size: 1.9rem; font-weight: 700; letter-spacing: -.02em; margin: 0; color: var(--ink); line-height: 1.2; }
.page-head p { margin: .3rem 0 0; color: var(--muted); font-size: .92rem; }
.section-title { font-size: 1.1rem; font-weight: 600; margin: 1.5rem 0 .8rem; color: var(--ink); display: flex; align-items: baseline; gap: .5rem; }
.section-title small { color: var(--muted); font-weight: 400; font-size: .82rem; }
.section-title:first-child { margin-top: .2rem; }

/* ---------- cards ----------
   Every bordered container with a key starting "card_" is a white rounded card. Side panels
   (order, quote, overview) use their own keys so they can stick to the top of the viewport. */
[class*="st-key-card_"], .st-key-order_panel, .st-key-quote_panel, .st-key-overview_side {
  background: var(--card); border: none !important; border-radius: 20px; box-shadow: var(--shadow);
  padding: 1.1rem 1.2rem;
}
.st-key-order_panel [class*="st-key-card_"], .st-key-quote_panel [class*="st-key-card_"] {
  background: #FAF9FE; box-shadow: none; border-radius: 16px; padding: .9rem 1rem;
}
.st-key-order_panel, .st-key-quote_panel, .st-key-overview_side {
  position: sticky; top: 1rem; max-height: calc(100vh - 2rem); overflow-y: auto; scrollbar-width: thin;
}

/* ---------- product cards ---------- */
.pcard { display: flex; flex-direction: column; }
.pplate {
  height: 118px; border-radius: 18px; display: flex; align-items: center; justify-content: center;
  font-size: 3.1rem; margin-bottom: .65rem;
}
.pname { font-weight: 600; font-size: .95rem; color: var(--ink); line-height: 1.3; min-height: 2.5em; }
.psub { color: var(--muted); font-size: .76rem; margin-top: 2px; }
.pprice { color: var(--accent); font-weight: 700; font-size: 1.02rem; margin-top: .25rem; }
.pmeta { color: var(--muted); font-size: .76rem; }

/* ---------- list rows (best sellers, orders, cart lines) ---------- */
.lrow { display: flex; align-items: center; gap: .8rem; padding: .7rem 0; border-bottom: 1px solid var(--line); }
.lrow:last-child { border-bottom: none; }
.lthumb { width: 46px; height: 46px; min-width: 46px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.3rem; }
.lmain { flex: 1; min-width: 0; }
.lname { font-weight: 600; font-size: .9rem; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lsub { color: var(--muted); font-size: .76rem; line-height: 1.4; }
.lend { text-align: right; white-space: nowrap; }
.lval { color: var(--accent); font-weight: 600; font-size: .9rem; }

/* ---------- statistics tiles ---------- */
.kpi-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .8rem; }
.kpi { background: #FFFFFF; border-radius: 18px; padding: 1rem 1.1rem; box-shadow: var(--shadow); }
.kpi .k { color: var(--muted); font-size: .8rem; }
.kpi .v { font-size: 1.32rem; font-weight: 700; color: var(--ink); letter-spacing: -.02em; line-height: 1.25; margin-top: .15rem; }
.kpi.accent { background: #E35B4F; }
.kpi.accent .k, .kpi.accent .v { color: #FFFFFF; }

/* ---------- profile and status ---------- */
.profile { display: flex; align-items: center; gap: .75rem; padding-bottom: .9rem; border-bottom: 1px solid var(--line); margin-bottom: .4rem; }
.avatar {
  width: 44px; height: 44px; border-radius: 50%; background: #EEE8FF; color: var(--primary);
  font-weight: 700; font-size: 1.1rem; display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.profile .n { font-weight: 600; color: var(--ink); font-size: .95rem; }
.profile .s { color: var(--muted); font-size: .78rem; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .72rem; font-weight: 600; }
.badge.ok { background: #E6F8EE; color: #14864B; }
.badge.warn { background: #FFF1E6; color: #C2540B; }
.badge.bad { background: #FDECEC; color: #B42318; }
.badge.info { background: #EEE8FF; color: var(--primary); }

/* ---------- totals ---------- */
.total-row {
  display: flex; justify-content: space-between; align-items: center;
  padding: .9rem 0 .3rem; margin-top: .4rem; border-top: 1px dashed #E2DDF0;
  font-size: 1rem; font-weight: 500; color: var(--ink);
}
.total-row b { color: var(--accent); font-size: 1.45rem; font-weight: 700; letter-spacing: -.02em; }

/* ---------- Streamlit widgets: softer shapes, full-width primary action ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: 999px; font-weight: 600; padding: .45rem 1.15rem;
}
.st-key-pos_checkout, .st-key-pos_clear, .st-key-demo_clear, .st-key-dash_open_pos { width: 100%; }
.st-key-pos_checkout button, .st-key-dash_open_pos button {
  width: 100%; padding: .85rem 1rem; font-size: 1rem; box-shadow: 0 10px 22px rgba(77, 12, 166, .25);
}
.st-key-pos_clear button, .st-key-demo_clear button { width: 100%; }
div[data-testid="stMetric"] { background: #FFFFFF; border-radius: 18px; padding: 1rem 1.1rem; box-shadow: var(--shadow); }
div[data-testid="stMetric"] label p { color: var(--muted); font-weight: 500; font-size: .82rem; }
div[data-testid="stMetricValue"] { color: var(--ink); font-weight: 700; font-size: 1.45rem; }
div[data-testid="stDataFrame"] { background: #FFFFFF; border-radius: 18px; box-shadow: var(--shadow); padding: .35rem; }
div[data-baseweb="input"], div[data-baseweb="select"] > div, div[data-baseweb="textarea"] { border-radius: 14px !important; }
button[data-baseweb="tab"] { font-weight: 500; }
/* category pills wrap onto several lines instead of being clipped by a one-row container */
.st-key-pos_category, .st-key-pos_category *, .st-key-dash_category, .st-key-dash_category * {
  height: auto !important; max-height: none !important; overflow: visible !important;
}
.st-key-pos_category div[data-testid="stButtonGroup"] > div,
.st-key-dash_category div[data-testid="stButtonGroup"] > div { flex-wrap: wrap !important; row-gap: 6px; }
div[data-testid="stExpander"] details { border-radius: 14px; border-color: #ECE8F6; }

@media (max-width: 1000px) {
  .block-container { padding: 1rem; }
  .st-key-order_panel, .st-key-quote_panel, .st-key-overview_side { position: static; max-height: none; }
}
"""


def inject() -> None:
    """Add the theme stylesheet. Call once per run, before any other element."""
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def greeting(now: datetime | None = None) -> str:
    hour = (now or datetime.now()).hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def icon_for(category: str) -> str:
    return CATEGORY_ICONS.get(category, DEFAULT_ICON)


def tint_for(category: str) -> str:
    return CATEGORY_TINTS.get(category, DEFAULT_TINT)


def page_header(title: str, subtitle: str = "") -> None:
    sub = f"<p>{esc(subtitle)}</p>" if subtitle else ""
    st.markdown(f'<div class="page-head"><div><h1>{esc(title)}</h1>{sub}</div></div>', unsafe_allow_html=True)


def section_title(title: str, hint: str = "") -> None:
    extra = f"<small>{esc(hint)}</small>" if hint else ""
    st.markdown(f'<div class="section-title">{esc(title)}{extra}</div>', unsafe_allow_html=True)


def brand_html() -> str:
    initial = esc(config.STORE_NAME[:1].upper())
    return (
        '<div class="brand"><div class="brand-mark">' + initial + '</div><div>'
        f'<div class="brand-name">{esc(config.STORE_NAME)}</div>'
        '<div class="brand-sub">POS &amp; Inventory</div></div></div>'
    )


def sidebar_footer(data_file: str) -> str:
    return (
        '<div class="side-foot">Signed in as <b>' + esc(config.CASHIER_NAME) + '</b><br>'
        'Data file: ' + esc(data_file) + '</div>'
    )


def product_card(product: dict, meta: str) -> str:
    category = product.get("category", "")
    return (
        '<div class="pcard">'
        f'<div class="pplate" style="background:{tint_for(category)}">{icon_for(category)}</div>'
        f'<div class="pname">{esc(product["name"])}</div>'
        f'<div class="psub">{esc(product["sku"])} · {esc(category)}</div>'
        f'<div class="pprice">{esc(money(product["price"]))}</div>'
        f'<div class="pmeta">{esc(meta)}</div>'
        '</div>'
    )


def list_row(*, emoji: str, tint: str, title: str, subtitle: str, value: str = "", value_note: str = "") -> str:
    return (
        '<div class="lrow">'
        f'<div class="lthumb" style="background:{tint}">{emoji}</div>'
        '<div class="lmain">'
        f'<div class="lname">{esc(title)}</div>'
        f'<div class="lsub">{esc(subtitle)}</div>'
        '</div>'
        '<div class="lend">'
        f'<div class="lval">{esc(value)}</div>'
        f'<div class="lsub">{esc(value_note)}</div>'
        '</div></div>'
    )


def kpi(label: str, value, *, accent: bool = False) -> str:
    cls = "kpi accent" if accent else "kpi"
    return f'<div class="{cls}"><div class="k">{esc(label)}</div><div class="v">{esc(value)}</div></div>'


def kpi_grid(items: list[str]) -> str:
    return '<div class="kpi-grid">' + "".join(items) + "</div>"


def badge(text: str, kind: str = "ok") -> str:
    return f'<span class="badge {kind}">{esc(text)}</span>'


def avatar(letter: str) -> str:
    return f'<div class="avatar">{esc(letter.upper()[:1] or "?")}</div>'


def profile_html(title: str, subtitle: str) -> str:
    return (
        '<div class="profile">' + avatar(config.STORE_NAME) +
        f'<div><div class="n">{esc(title)}</div><div class="s">{esc(subtitle)}</div></div></div>'
    )


def revenue_chart(points: list[tuple[str, int]]) -> str:
    """Hand-drawn SVG area chart for the Statistics card. Unlike a generic chart widget it has no
    axis labels to format, and it draws a flat line cleanly when there are no sales yet."""
    width, height, left, right, top, bottom = 320, 150, 8, 8, 14, 26
    values = [value for _, value in points]
    labels = [label for label, _ in points]
    peak = max(values) or 1
    step = (width - left - right) / max(len(values) - 1, 1)
    xs = [left + i * step for i in range(len(values))]
    ys = [height - bottom - (value / peak) * (height - top - bottom) for value in values]

    line = f"M{xs[0]:.1f},{ys[0]:.1f}"
    for i in range(1, len(xs)):
        mid = (xs[i - 1] + xs[i]) / 2
        line += f" C{mid:.1f},{ys[i - 1]:.1f} {mid:.1f},{ys[i]:.1f} {xs[i]:.1f},{ys[i]:.1f}"
    base = height - bottom
    area = f"{line} L{xs[-1]:.1f},{base} L{xs[0]:.1f},{base} Z"

    peak_index = max(range(len(values)), key=lambda i: values[i])
    marker = (
        f'<circle cx="{xs[peak_index]:.1f}" cy="{ys[peak_index]:.1f}" r="4.5" fill="#E35B4F" stroke="#FFFFFF" stroke-width="2"/>'
    )
    text = "".join(
        f'<text x="{x:.1f}" y="{height - 6}" text-anchor="middle" font-size="10" fill="#8A8FA3">{esc(label)}</text>'
        for x, label in zip(xs, labels)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="Revenue for the last 7 days">'
        '<defs><linearGradient id="revFill" x1="0" x2="0" y1="0" y2="1">'
        f'<stop offset="0" stop-color="{PRIMARY}" stop-opacity="0.28"/>'
        f'<stop offset="1" stop-color="{PRIMARY}" stop-opacity="0"/></linearGradient></defs>'
        f'<path d="{area}" fill="url(#revFill)"/>'
        f'<path d="{line}" fill="none" stroke="{PRIMARY}" stroke-width="2.5" stroke-linecap="round"/>'
        f'{marker}{text}</svg>'
    )


def total_row(label: str, value: str) -> str:
    return f'<div class="total-row"><span>{esc(label)}</span><b>{esc(value)}</b></div>'
