"""Numbers for the dashboard."""

from __future__ import annotations

import sqlite3
from datetime import date

from logic import inventory, pos


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
    }
