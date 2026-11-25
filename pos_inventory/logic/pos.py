"""Cart handling and the sales workflow: checkout, void and history.

Cart items are plain dicts, so they can live in Streamlit session state:
    {"product_id": 3, "qty": 2, "serial_no": None}      # quantity item
    {"product_id": 9, "qty": 1, "serial_no": "35..."}   # one IMEI / serial unit
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection, Iterable, Mapping
from datetime import date, datetime

from logic import catalog, inventory, payments, pricing, rules
from logic import promotions as promo_store
from logic.errors import BusinessError, PromotionError, StockError
from logic.models import CartLine
from logic.utils import now_iso

Item = dict


def _find_quantity_line(cart: list[Item], product_id: int) -> Item | None:
    return next((i for i in cart if i["product_id"] == product_id and not i["serial_no"]), None)


def merge_quantity(cart: list[Item], product_id: int, qty: int = 1) -> None:
    """Add quantity without a stock check. Used by the Demo Price simulator, which never sells."""
    if qty < 1:
        raise BusinessError("Quantity must be at least 1.")
    existing = _find_quantity_line(cart, product_id)
    if existing:
        existing["qty"] += qty
    else:
        cart.append({"product_id": product_id, "qty": qty, "serial_no": None})


def cart_add(
    cart: list[Item],
    *,
    product: Mapping | None,
    on_hand: int,
    in_stock_serials: Collection[str] = (),
    qty: int = 1,
    serial_no: str | None = None,
) -> None:
    """Add to a POS cart. Every unit must physically exist: quantity items are capped at on-hand,
    tracked items must name a serial that is currently in stock."""
    if product is None:
        raise BusinessError("That product no longer exists.")
    if not product["active"]:
        raise BusinessError(f"{product['name']} is not on sale.")

    if product["tracking"] != "none":
        label = "IMEI" if product["tracking"] == "imei" else "serial number"
        if not serial_no:
            raise BusinessError(f"Pick or scan the {label} for {product['name']}.")
        if serial_no not in in_stock_serials:
            raise StockError(f"{serial_no} is not in stock.")
        if any(item["serial_no"] == serial_no for item in cart):
            raise BusinessError(f"{serial_no} is already in the cart.")
        cart.append({"product_id": product["id"], "qty": 1, "serial_no": serial_no})
        return

    if serial_no:
        raise BusinessError(f"{product['name']} is not tracked by serial number.")
    if qty < 1:
        raise BusinessError("Quantity must be at least 1.")
    existing = _find_quantity_line(cart, product["id"])
    new_qty = qty + (existing["qty"] if existing else 0)
    if new_qty > on_hand:
        raise StockError(f"Only {on_hand} unit(s) of {product['name']} in stock.")
    if existing:
        existing["qty"] = new_qty
    else:
        cart.append({"product_id": product["id"], "qty": qty, "serial_no": None})


def cart_change_qty(cart: list[Item], index: int, delta: int, *, on_hand: int | None = None) -> None:
    item = cart[index]
    if item["serial_no"]:
        raise BusinessError("Serial-tracked units are one per line. Remove the line instead.")
    new_qty = item["qty"] + delta
    if new_qty < 1:
        del cart[index]
        return
    if on_hand is not None and new_qty > on_hand:
        raise StockError(f"Only {on_hand} unit(s) in stock.")
    item["qty"] = new_qty


def cart_remove(cart: list[Item], index: int) -> None:
    del cart[index]


def sanitize_cart(
    cart: Iterable[Item],
    products: Mapping[int, Mapping],
    on_hand: Mapping[int, int],
    serials_by_product: Mapping[int, list[str]],
) -> tuple[list[Item], list[str]]:
    """Drop or cap cart lines that stopped being valid since they were added (sold elsewhere,
    deactivated, stock counted down). Returns the cleaned cart plus messages for the cashier."""
    cleaned: list[Item] = []
    messages: list[str] = []
    for item in cart:
        product = products.get(item["product_id"])
        if product is None or not product["active"]:
            messages.append("An item was removed because it is no longer on sale.")
            continue
        if item["serial_no"]:
            if item["serial_no"] in serials_by_product.get(product["id"], []):
                cleaned.append(item)
            else:
                messages.append(f"{item['serial_no']} ({product['name']}) is no longer in stock and was removed.")
            continue
        available = on_hand.get(product["id"], 0)
        if available <= 0:
            messages.append(f"{product['name']} sold out and was removed from the cart.")
        elif item["qty"] > available:
            messages.append(f"Only {available} × {product['name']} left. Quantity reduced.")
            cleaned.append({**item, "qty": available})
        else:
            cleaned.append(item)
    return cleaned, messages


def build_cart_lines(cart: Iterable[Item], products: Mapping[int, Mapping]) -> list[CartLine]:
    """Price the cart from the catalogue. Prices are never stored in the cart, so they are always current."""
    lines: list[CartLine] = []
    for item in cart:
        product = products.get(item["product_id"])
        if product is None:
            raise BusinessError("A product in the cart is no longer available.")
        lines.append(
            CartLine(
                product_id=product["id"],
                sku=product["sku"],
                name=product["name"],
                unit_price=int(product["price"]),
                qty=int(item["qty"]),
                serial_no=item.get("serial_no"),
            )
        )
    return lines


def check_stock(conn: sqlite3.Connection, lines: Iterable[CartLine]) -> None:
    seen_serials: set[str] = set()
    quantity_needed: dict[int, int] = {}
    names: dict[int, str] = {}
    for line in lines:
        names[line.product_id] = line.name
        if line.serial_no:
            if line.serial_no in seen_serials:
                raise StockError(f"{line.serial_no} is in the cart twice.")
            seen_serials.add(line.serial_no)
            row = conn.execute(
                "SELECT product_id, status FROM serials WHERE serial_no = ?", (line.serial_no,)
            ).fetchone()
            if row is None or row["product_id"] != line.product_id or row["status"] != "in_stock":
                raise StockError(f"{line.serial_no} ({line.name}) is no longer in stock.")
        else:
            quantity_needed[line.product_id] = quantity_needed.get(line.product_id, 0) + line.qty
    for product_id, needed in quantity_needed.items():
        available = inventory.on_hand(conn, product_id)
        if needed > available:
            raise StockError(f"Only {available} × {names[product_id]} left in stock (cart needs {needed}).")


def checkout(
    conn: sqlite3.Connection,
    *,
    items: list[Item],
    payment_code: str | None,
    promotion_ids: Iterable[int] = (),
    customer_name: str = "",
    today: date | None = None,
) -> int:
    """Complete a sale atomically: re-check stock and every promotion T&C, then write the sale,
    its lines, the promotions used and the stock movements. Returns the sale id.

    The caller must run this inside a write transaction (see database.db.transaction).
    """
    today = today or date.today()
    if not items:
        raise BusinessError("The cart is empty.")
    if not payment_code:
        raise BusinessError("Choose a payment method before completing the sale.")

    products = {p["id"]: p for p in catalog.list_products(conn, active_only=False)}
    lines = build_cart_lines(items, products)
    for line in lines:
        if not products[line.product_id]["active"]:
            raise BusinessError(f"{line.name} is no longer on sale.")

    payment = payments.get_payment_by_code(conn, payment_code)
    if payment is None or not payment.active:
        raise BusinessError("The selected payment method is not available.")

    check_stock(conn, lines)

    all_promotions = promo_store.load_promotions(conn, active_only=False)
    kept, removed = rules.prune_applied(all_promotions, lines, payment, today, promotion_ids)
    if removed:
        details = "; ".join(f"{name}: {reasons[0]}" for name, reasons in removed)
        raise PromotionError(f"Promotion terms are no longer met ({details}). Review the promotions and try again.")

    quote = pricing.build_quote(lines, payment, kept)

    stamp = datetime.now()
    cur = conn.execute(
        """INSERT INTO sales
           (created_at, customer_name, payment_code, payment_label, surcharge_pct, subtotal,
            promo_discount, surcharge, total_due, cashback, effective_total, tax_included)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            stamp.isoformat(timespec="seconds"),
            customer_name.strip(),
            payment.code,
            payments.payment_label(payment),
            payment.surcharge_pct,
            quote.subtotal,
            quote.promo_discount,
            quote.surcharge,
            quote.total_due,
            quote.cashback,
            quote.effective_total,
            quote.tax_included,
        ),
    )
    sale_id = int(cur.lastrowid)
    receipt_no = f"R{stamp:%y%m%d}-{sale_id:05d}"
    conn.execute("UPDATE sales SET receipt_no = ? WHERE id = ?", (receipt_no, sale_id))

    for line in quote.lines:
        conn.execute(
            """INSERT INTO sale_lines
               (sale_id, product_id, sku, name, serial_no, qty, unit_price, list_total, discount, net_total)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sale_id,
                line.product_id,
                line.sku,
                line.name,
                line.serial_no,
                line.qty,
                line.unit_price,
                line.list_total,
                line.discount,
                line.net_total,
            ),
        )
    for app in quote.applications:
        conn.execute(
            """INSERT INTO sale_promotions
               (sale_id, promotion_id, code, name, reward_type, discount, cashback)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                sale_id,
                app.promotion.id,
                app.promotion.code,
                app.promotion.name,
                app.promotion.reward_type,
                app.discount,
                app.cashback,
            ),
        )

    quantities: dict[int, int] = {}
    for line in lines:
        if line.serial_no:
            conn.execute(
                "UPDATE serials SET status = 'sold', sale_id = ? WHERE serial_no = ?", (sale_id, line.serial_no)
            )
            inventory.record_move(conn, line.product_id, -1, "SALE", serial_no=line.serial_no, reference=receipt_no)
        else:
            quantities[line.product_id] = quantities.get(line.product_id, 0) + line.qty
    for product_id, qty in quantities.items():
        inventory.record_move(conn, product_id, -qty, "SALE", reference=receipt_no)
    return sale_id


def void_sale(conn: sqlite3.Connection, *, sale_id: int, reason: str) -> None:
    """Cancel a completed sale and put its units back into stock."""
    sale = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if sale is None:
        raise BusinessError("Sale not found.")
    if sale["status"] != "COMPLETED":
        raise BusinessError("This sale has already been voided.")
    reason = reason.strip()
    if not reason:
        raise BusinessError("Enter a reason for voiding the sale.")

    quantities: dict[int, int] = {}
    for line in conn.execute("SELECT * FROM sale_lines WHERE sale_id = ? ORDER BY id", (sale_id,)).fetchall():
        if line["serial_no"]:
            cur = conn.execute(
                "UPDATE serials SET status = 'in_stock', sale_id = NULL WHERE serial_no = ? AND sale_id = ?",
                (line["serial_no"], sale_id),
            )
            if cur.rowcount != 1:
                raise BusinessError(f"{line['serial_no']} cannot be restored to stock.")
            inventory.record_move(
                conn, line["product_id"], 1, "VOID_SALE", serial_no=line["serial_no"],
                reference=sale["receipt_no"], note=reason,
            )
        else:
            quantities[line["product_id"]] = quantities.get(line["product_id"], 0) + line["qty"]
    for product_id, qty in quantities.items():
        inventory.record_move(conn, product_id, qty, "VOID_SALE", reference=sale["receipt_no"], note=reason)

    conn.execute(
        "UPDATE sales SET status = 'VOIDED', void_reason = ?, voided_at = ? WHERE id = ?",
        (reason, now_iso(), sale_id),
    )


def get_sale(conn: sqlite3.Connection, sale_id: int) -> dict:
    header = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if header is None:
        raise BusinessError("Sale not found.")
    sale = dict(header)
    sale["lines"] = [dict(r) for r in conn.execute("SELECT * FROM sale_lines WHERE sale_id = ? ORDER BY id", (sale_id,))]
    sale["promotions"] = [
        dict(r) for r in conn.execute("SELECT * FROM sale_promotions WHERE sale_id = ? ORDER BY id", (sale_id,))
    ]
    return sale


def list_sales(conn: sqlite3.Connection, *, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        """SELECT id, receipt_no, created_at, customer_name, payment_label,
                  total_due, promo_discount, cashback, status
           FROM sales ORDER BY id DESC LIMIT ?""",
        (limit,),
    )
    return [dict(row) for row in rows]
