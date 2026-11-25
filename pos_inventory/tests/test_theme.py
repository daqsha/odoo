"""Pure checks for the HTML helpers: escaping of user text and the revenue chart edge cases."""

from datetime import datetime

from views import theme


def test_product_card_escapes_user_supplied_text():
    card = theme.product_card(
        {"name": "<img src=x onerror=alert(1)>", "sku": "A&B", "category": "Audio", "price": 1000},
        meta="5 in stock",
    )
    assert "<img" not in card
    assert "&lt;img" in card
    assert "A&amp;B" in card


def test_list_row_escapes_titles_and_values():
    row = theme.list_row(emoji="🧾", tint="#fff", title="<b>x</b>", subtitle="s", value="Rp 1", value_note="n")
    assert "<b>x</b>" not in row and "&lt;b&gt;x&lt;/b&gt;" in row


def test_revenue_chart_draws_flat_line_when_there_are_no_sales():
    svg = theme.revenue_chart([("Mon", 0), ("Tue", 0), ("Wed", 0)])
    assert svg.startswith("<svg")
    assert "NaN" not in svg


def test_revenue_chart_scales_to_the_peak_day():
    svg = theme.revenue_chart([("Mon", 5), ("Tue", 10), ("Wed", 0)])
    assert svg.startswith("<svg") and "NaN" not in svg
    assert svg.count("<text") == 3


def test_greeting_follows_time_of_day():
    assert theme.greeting(datetime(2026, 1, 1, 9)) == "Good morning"
    assert theme.greeting(datetime(2026, 1, 1, 14)) == "Good afternoon"
    assert theme.greeting(datetime(2026, 1, 1, 21)) == "Good evening"
