"""Promotion repository: stores and loads promotions together with their eligible SKUs and payment requirements."""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from logic.errors import BusinessError
from logic.models import CASHBACK, FIXED_OFF, PERCENT_OFF, Promotion
from logic.utils import iso_date, parse_date

REWARD_LABELS = {
    PERCENT_OFF: "Percent off (%)",
    FIXED_OFF: "Amount off (Rp)",
    CASHBACK: "Cashback (%)",
}


def load_promotions(conn: sqlite3.Connection, *, active_only: bool = True) -> list[Promotion]:
    skus: dict[int, set[str]] = defaultdict(set)
    for row in conn.execute(
        "SELECT pp.promotion_id, p.sku FROM promotion_products pp JOIN products p ON p.id = pp.product_id"
    ):
        skus[row["promotion_id"]].add(row["sku"])

    payments: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for row in conn.execute(
        """SELECT pp.promotion_id, po.code, po.label
           FROM promotion_payments pp JOIN payment_options po ON po.id = pp.payment_option_id
           ORDER BY po.id"""
    ):
        payments[row["promotion_id"]].append((row["code"], row["label"]))

    sql = "SELECT * FROM promotions" + (" WHERE active = 1" if active_only else "") + " ORDER BY id"
    promotions = []
    for row in conn.execute(sql):
        promotions.append(
            Promotion(
                id=row["id"],
                code=row["code"],
                name=row["name"],
                description=row["description"],
                reward_type=row["reward_type"],
                reward_value=float(row["reward_value"]),
                max_reward=row["max_reward"],
                min_spend=row["min_spend"],
                min_qty=row["min_qty"],
                stackable=bool(row["stackable"]),
                start_date=parse_date(row["start_date"]),
                end_date=parse_date(row["end_date"]),
                active=bool(row["active"]),
                eligible_skus=frozenset(skus.get(row["id"], ())),
                required_payments=tuple(payments.get(row["id"], ())),
            )
        )
    return promotions


def create_promotion(
    conn: sqlite3.Connection,
    *,
    code: str,
    name: str,
    reward_type: str,
    reward_value: float,
    skus: list[str] | tuple[str, ...] = (),
    payment_codes: list[str] | tuple[str, ...] = (),
    description: str = "",
    max_reward: int | None = None,
    min_spend: int = 0,
    min_qty: int = 1,
    stackable: bool = False,
    start_date=None,
    end_date=None,
    active: bool = True,
) -> int:
    code = code.strip().upper().replace(" ", "-")
    if not code:
        raise BusinessError("Promotion code is required.")
    if not name.strip():
        raise BusinessError("Promotion name is required.")
    if reward_type not in REWARD_LABELS:
        raise BusinessError("Unknown reward type.")
    if reward_value <= 0:
        raise BusinessError("Reward value must be greater than zero.")
    if reward_type != FIXED_OFF and reward_value > 100:
        raise BusinessError("A percentage cannot exceed 100.")
    if max_reward is not None and max_reward < 0:
        raise BusinessError("Maximum reward cannot be negative.")
    if min_spend < 0:
        raise BusinessError("Minimum spend cannot be negative.")
    if min_qty < 1:
        raise BusinessError("Minimum quantity must be at least 1.")
    start, end = parse_date(start_date), parse_date(end_date)
    if start and end and end < start:
        raise BusinessError("End date must be on or after the start date.")

    sku_ids = []
    for sku in skus:
        row = conn.execute("SELECT id FROM products WHERE sku = ?", (sku.strip().upper(),)).fetchone()
        if row is None:
            raise BusinessError(f"Unknown SKU in eligible list: {sku}")
        sku_ids.append(row["id"])

    payment_ids = []
    for pay_code in payment_codes:
        row = conn.execute("SELECT id FROM payment_options WHERE code = ?", (pay_code.strip().upper(),)).fetchone()
        if row is None:
            raise BusinessError(f"Unknown payment option: {pay_code}")
        payment_ids.append(row["id"])

    try:
        cur = conn.execute(
            """INSERT INTO promotions
               (code, name, description, reward_type, reward_value, max_reward, min_spend,
                min_qty, stackable, start_date, end_date, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                code,
                name.strip(),
                description.strip(),
                reward_type,
                float(reward_value),
                max_reward,
                int(min_spend),
                int(min_qty),
                1 if stackable else 0,
                iso_date(start),
                iso_date(end),
                1 if active else 0,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise BusinessError(f"Promotion code {code} already exists.") from exc
    promo_id = int(cur.lastrowid)

    for product_id in dict.fromkeys(sku_ids):
        conn.execute("INSERT INTO promotion_products (promotion_id, product_id) VALUES (?, ?)", (promo_id, product_id))
    for payment_id in dict.fromkeys(payment_ids):
        conn.execute(
            "INSERT INTO promotion_payments (promotion_id, payment_option_id) VALUES (?, ?)", (promo_id, payment_id)
        )
    return promo_id


def set_promotion_active(conn: sqlite3.Connection, promo_id: int, active: bool) -> None:
    conn.execute("UPDATE promotions SET active = ? WHERE id = ?", (1 if active else 0, promo_id))
