"""Numbers for the dashboard."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from logic import inventory, pos


def product_sales(conn: sqlite3.Connection) -> list[dict]:
    """Every active product with the units sold in completed sales, best sellers first."""
    rows = conn.execute(
        """SELECT p.id, p.sku, p.name, p.brand, p.category, p.price, p.tracking, p.reorder_level, p.active,
                  COALESCE(s.units, 0) AS units
           FROM products p
           LEFT JOIN (
               SELECT sl.product_id, SUM(sl.qty) AS units
               FROM sale_lines sl JOIN sales sa ON sa.id = sl.sale_id
               WHERE sa.status = 'COMPLETED'
               GROUP BY sl.product_id
           ) s ON s.product_id = p.id
           WHERE p.active = 1
           ORDER BY units DESC, p.name"""
    )
    return [dict(row) for row in rows]


def daily_revenue(conn: sqlite3.Connection, today: date, days: int = 7) -> list[tuple[str, int]]:
    """(weekday label, revenue) for the last `days` days, oldest first. Days without sales count as 0."""
    start = today - timedelta(days=days - 1)
    rows = conn.execute(
        """SELECT substr(created_at, 1, 10) AS day, COALESCE(SUM(total_due), 0) AS total
           FROM sales
           WHERE status = 'COMPLETED' AND substr(created_at, 1, 10) >= ?
           GROUP BY day""",
        (start.isoformat(),),
    )
    totals = {row["day"]: int(row["total"]) for row in rows}
    series = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        series.append((day.strftime("%a"), totals.get(day.isoformat(), 0)))
    return series


def dashboard_summary(conn: sqlite3.Connection, today: date) -> dict:
    today_row = conn.execute(
        """SELECT COUNT(*) AS n,
                  COALESCE(SUM(total_due), 0) AS total,
                  COALESCE(SUM(promo_discount), 0) AS discounts,
                  COALESCE(SUM(cashback), 0) AS cashback
           FROM sales
           WHERE status = 'COMPLETED' AND substr(created_at, 1, 10) = ?""",
        (today.isoformat(),),
    ).fetchone()

    overview = inventory.stock_overview(conn)
    top_products = [
        dict(row)
        for row in conn.execute(
            """SELECT sl.sku, sl.name, SUM(sl.qty) AS units, SUM(sl.net_total) AS revenue
               FROM sale_lines sl JOIN sales s ON s.id = sl.sale_id
               WHERE s.status = 'COMPLETED'
               GROUP BY sl.sku, sl.name
               ORDER BY units DESC, revenue DESC
               LIMIT 5"""
        )
    ]
    return {
        "sales_count": int(today_row["n"]),
        "sales_total": int(today_row["total"]),
        "discounts": int(today_row["discounts"]),
        "cashback": int(today_row["cashback"]),
        "units_on_hand": sum(row["on_hand"] for row in overview),
        "inventory_value": sum(row["value"] for row in overview),
        "low_stock": [row for row in overview if row["low_stock"]],
        "top_products": top_products,
        "recent_sales": pos.list_sales(conn, limit=6),
        "daily": daily_revenue(conn, today),
    }
