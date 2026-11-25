"""Product catalogue: SKUs, prices, cost and how each product is tracked."""

from __future__ import annotations

import sqlite3

from logic.errors import BusinessError
from logic.utils import now_iso

TRACKING_LABELS = {"none": "Quantity", "serial": "Serial no.", "imei": "IMEI"}
_NUMERIC_FIELDS = ("price", "cost", "reorder_level")
_UPDATABLE = ("name", "brand", "category", "price", "cost", "reorder_level", "active")


def list_products(
    conn: sqlite3.Connection,
    *,
    search: str = "",
    category: str | None = None,
    active_only: bool = True,
) -> list[dict]:
    sql = "SELECT * FROM products WHERE 1 = 1"
    params: list = []
    if active_only:
        sql += " AND active = 1"
    if category:
        sql += " AND category = ?"
        params.append(category)
    term = search.strip().lower()
    if term:
        like = f"%{term}%"
        sql += " AND (lower(sku) LIKE ? OR lower(name) LIKE ? OR lower(brand) LIKE ?)"
        params.extend([like, like, like])
    sql += " ORDER BY category, name"
    return [dict(row) for row in conn.execute(sql, params)]


def get_product(conn: sqlite3.Connection, product_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return dict(row) if row else None


def get_product_by_sku(conn: sqlite3.Connection, sku: str) -> dict | None:
    row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku.strip().upper(),)).fetchone()
    return dict(row) if row else None


def list_categories(conn: sqlite3.Connection) -> list[str]:
    return [row["category"] for row in conn.execute("SELECT DISTINCT category FROM products ORDER BY category")]


def _validate(product: dict) -> None:
    if not str(product["name"]).strip():
        raise BusinessError("Product name is required.")
    if not str(product["category"]).strip():
        raise BusinessError("Category is required.")
    if int(product["price"]) < 0 or int(product["cost"]) < 0:
        raise BusinessError("Price and cost cannot be negative.")
    if int(product["reorder_level"]) < 0:
        raise BusinessError("Reorder level cannot be negative.")
    if product["tracking"] not in TRACKING_LABELS:
        raise BusinessError("Unknown tracking mode.")


def create_product(
    conn: sqlite3.Connection,
    *,
    sku: str,
    name: str,
    category: str,
    price: int,
    cost: int = 0,
    brand: str = "",
    tracking: str = "none",
    reorder_level: int = 0,
    active: bool = True,
) -> int:
    sku = sku.strip().upper()
    if not sku:
        raise BusinessError("SKU is required.")
    product = {
        "name": name.strip(),
        "category": category.strip(),
        "price": int(price),
        "cost": int(cost),
        "reorder_level": int(reorder_level),
        "tracking": tracking,
    }
    _validate(product)
    try:
        cur = conn.execute(
            """INSERT INTO products
               (sku, name, brand, category, tracking, cost, price, reorder_level, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sku,
                product["name"],
                brand.strip(),
                product["category"],
                tracking,
                product["cost"],
                product["price"],
                product["reorder_level"],
                1 if active else 0,
                now_iso(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise BusinessError(f"SKU {sku} already exists.") from exc
    return int(cur.lastrowid)


def update_product(conn: sqlite3.Connection, product_id: int, **changes) -> None:
    """Change editable fields. Tracking mode and SKU are fixed once a product exists."""
    unknown = set(changes) - set(_UPDATABLE)
    if unknown:
        raise BusinessError("Cannot change: " + ", ".join(sorted(unknown)))
    product = get_product(conn, product_id)
    if product is None:
        raise BusinessError("Product not found.")

    clean: dict = {}
    for field, value in changes.items():
        if field == "active":
            clean[field] = 1 if value else 0
        elif field in _NUMERIC_FIELDS:
            clean[field] = int(value)
        else:
            clean[field] = str(value).strip()
    _validate({**product, **clean})
    if not clean:
        return
    assignments = ", ".join(f"{field} = ?" for field in clean)
    conn.execute(f"UPDATE products SET {assignments} WHERE id = ?", (*clean.values(), product_id))
