"""Stock control.

Every quantity change is a row in stock_moves, and on-hand = SUM(qty) for a product. The
ledger is the single source of truth. Serial/IMEI-tracked products also keep one row per
unit in `serials`, whose status (in_stock / sold / written_off) decides whether it can be sold.
"""

from __future__ import annotations

import sqlite3

from logic.catalog import get_product, list_products
from logic.errors import BusinessError, StockError
from logic.identifiers import normalize_identifier, validate_identifier
from logic.utils import now_iso

STOCK_OUT_REASONS = (
    "Damaged",
    "Lost / missing",
    "Internal use / demo unit",
    "Returned to supplier",
    "Other",
)


def _require_product(conn: sqlite3.Connection, product_id: int | None) -> dict:
    product = get_product(conn, product_id) if product_id else None
    if product is None:
        raise BusinessError("Choose a product first.")
    return product


def _label(product: dict) -> str:
    return "IMEI" if product["tracking"] == "imei" else "serial number"


def record_move(
    conn: sqlite3.Connection,
    product_id: int,
    qty: int,
    move_type: str,
    *,
    serial_no: str | None = None,
    reference: str = "",
    note: str = "",
    unit_cost: int | None = None,
) -> None:
    conn.execute(
        """INSERT INTO stock_moves
           (product_id, qty, move_type, serial_no, reference, note, unit_cost, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (product_id, qty, move_type, serial_no, reference, note, unit_cost, now_iso()),
    )


def on_hand_map(conn: sqlite3.Connection) -> dict[int, int]:
    rows = conn.execute("SELECT product_id, SUM(qty) AS qty FROM stock_moves GROUP BY product_id")
    return {row["product_id"]: int(row["qty"]) for row in rows}


def on_hand(conn: sqlite3.Connection, product_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(qty), 0) AS qty FROM stock_moves WHERE product_id = ?", (product_id,)
    ).fetchone()
    return int(row["qty"])


def in_stock_serials(conn: sqlite3.Connection, product_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT serial_no FROM serials WHERE product_id = ? AND status = 'in_stock' ORDER BY received_at, id",
        (product_id,),
    )
    return [row["serial_no"] for row in rows]


def in_stock_serial_map(conn: sqlite3.Connection) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    rows = conn.execute(
        "SELECT product_id, serial_no FROM serials WHERE status = 'in_stock' ORDER BY received_at, id"
    )
    for row in rows:
        result.setdefault(row["product_id"], []).append(row["serial_no"])
    return result


def stock_overview(conn: sqlite3.Connection, *, search: str = "", category: str | None = None) -> list[dict]:
    quantities = on_hand_map(conn)
    rows = []
    for product in list_products(conn, search=search, category=category, active_only=False):
        qty = quantities.get(product["id"], 0)
        rows.append(
            {
                **product,
                "on_hand": qty,
                "value": qty * product["cost"],
                "low_stock": product["reorder_level"] > 0 and qty <= product["reorder_level"],
            }
        )
    return rows


def receive_stock(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    qty: int | None = None,
    serials: list[str] | None = None,
    unit_cost: int | None = None,
    reference: str = "",
    note: str = "",
) -> int:
    """Stock-in. Quantity items take a count; tracked items take one IMEI/serial per unit."""
    product = _require_product(conn, product_id)
    if unit_cost is not None and unit_cost < 0:
        raise BusinessError("Unit cost cannot be negative.")

    if product["tracking"] == "none":
        if qty is None or int(qty) < 1:
            raise BusinessError("Quantity must be at least 1.")
        record_move(conn, product_id, int(qty), "STOCK_IN", reference=reference, note=note, unit_cost=unit_cost)
        return int(qty)

    tracking = product["tracking"]
    values = [validate_identifier(normalize_identifier(raw, tracking), tracking) for raw in serials or []]
    if not values:
        raise BusinessError(f"Enter at least one {_label(product)} for {product['name']}.")

    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        raise BusinessError("Duplicate number(s) in this receipt: " + ", ".join(sorted(set(duplicates))))

    existing = []
    for value in values:
        row = conn.execute("SELECT status FROM serials WHERE serial_no = ?", (value,)).fetchone()
        if row is not None:
            existing.append(f"{value} ({row['status'].replace('_', ' ')})")
    if existing:
        raise BusinessError("Already in the system: " + ", ".join(existing))

    for value in values:
        conn.execute(
            "INSERT INTO serials (product_id, serial_no, status, received_at) VALUES (?, ?, 'in_stock', ?)",
            (product_id, value, now_iso()),
        )
        record_move(
            conn, product_id, 1, "STOCK_IN", serial_no=value, reference=reference, note=note, unit_cost=unit_cost
        )
    return len(values)


def stock_out(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    reason: str,
    qty: int | None = None,
    serials: list[str] | None = None,
    reference: str = "",
    note: str = "",
) -> int:
    """Write stock off (damage, loss, internal use). Tracked items are written off unit by unit."""
    product = _require_product(conn, product_id)
    if reason not in STOCK_OUT_REASONS:
        raise BusinessError("Choose a reason for the stock-out.")
    note_text = reason + (f" - {note.strip()}" if note.strip() else "")

    if product["tracking"] == "none":
        if qty is None or int(qty) < 1:
            raise BusinessError("Quantity must be at least 1.")
        available = on_hand(conn, product_id)
        if int(qty) > available:
            raise StockError(f"Only {available} unit(s) of {product['name']} in stock.")
        record_move(conn, product_id, -int(qty), "STOCK_OUT", reference=reference, note=note_text)
        return int(qty)

    values = [normalize_identifier(raw, product["tracking"]) for raw in serials or []]
    values = list(dict.fromkeys(v for v in values if v))
    if not values:
        raise BusinessError("Select at least one unit to write off.")
    for value in values:
        row = conn.execute("SELECT product_id, status FROM serials WHERE serial_no = ?", (value,)).fetchone()
        if row is None or row["product_id"] != product_id:
            raise StockError(f"{value} is not a unit of {product['name']}.")
        if row["status"] != "in_stock":
            raise StockError(f"{value} is not in stock (status: {row['status'].replace('_', ' ')}).")
    for value in values:
        conn.execute("UPDATE serials SET status = 'written_off' WHERE serial_no = ?", (value,))
        record_move(conn, product_id, -1, "STOCK_OUT", serial_no=value, reference=reference, note=note_text)
    return len(values)


def adjust_count(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    counted_qty: int,
    reason: str = "Stock count",
    note: str = "",
) -> int:
    """Set on-hand to a physically counted number. Quantity items only."""
    product = _require_product(conn, product_id)
    if product["tracking"] != "none":
        raise BusinessError("Serial-tracked items cannot be count-adjusted. Stock-out or stock-in the specific units.")
    if counted_qty is None or int(counted_qty) < 0:
        raise BusinessError("Counted quantity cannot be negative.")
    difference = int(counted_qty) - on_hand(conn, product_id)
    if difference == 0:
        raise BusinessError("Counted quantity matches the system. Nothing to adjust.")
    note_text = f"Count: {reason.strip() or 'Stock count'}" + (f" - {note.strip()}" if note.strip() else "")
    record_move(conn, product_id, difference, "ADJUSTMENT", note=note_text)
    return difference


def serial_details(conn: sqlite3.Connection, product_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT serial_no, received_at FROM serials WHERE product_id = ? AND status = 'in_stock' "
        "ORDER BY received_at, id",
        (product_id,),
    )
    return [dict(row) for row in rows]


def movement_history(conn: sqlite3.Connection, *, product_id: int | None = None, limit: int = 300) -> list[dict]:
    rows = conn.execute(
        """SELECT m.id, m.created_at, p.sku, p.name, m.move_type, m.qty,
                  m.serial_no, m.reference, m.note, m.unit_cost
           FROM stock_moves m JOIN products p ON p.id = m.product_id
           WHERE (? IS NULL OR m.product_id = ?)
           ORDER BY m.id DESC LIMIT ?""",
        (product_id, product_id, limit),
    )
    return [dict(row) for row in rows]
