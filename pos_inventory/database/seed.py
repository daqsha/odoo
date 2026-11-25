"""Load the sample catalogue from data/seed/*.csv.

Seed rows go through the same logic functions the UI uses, so the sample data is validated
exactly like hand-entered data (IMEI checksums, unique SKUs, promotion rules and so on).

Usage:
    python -m database.seed            # create the database and load demo data if it is empty
    python -m database.seed --reset    # wipe every table and reload the demo data
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import config
from database.db import init_database, transaction
from logic import catalog, inventory, payments, promotions

# Children before parents: serials reference sales, and sales/serials/moves reference products.
CLEAR_ORDER = [
    "sale_promotions",
    "sale_lines",
    "serials",
    "stock_moves",
    "sales",
    "promotion_payments",
    "promotion_products",
    "promotions",
    "payment_options",
    "products",
]


def _read(name: str) -> list[dict]:
    with (config.SEED_DIR / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _text(value: str | None) -> str:
    return (value or "").strip()


def _int(value: str | None, default: int = 0) -> int:
    text = _text(value)
    return int(text) if text else default


def _opt_int(value: str | None) -> int | None:
    text = _text(value)
    return int(text) if text else None


def _float(value: str | None, default: float = 0.0) -> float:
    text = _text(value)
    return float(text) if text else default


def _flag(value: str | None) -> bool:
    return _text(value) in {"1", "true", "TRUE", "yes", "Y"}


def _pipe(value: str | None) -> list[str]:
    return [part.strip() for part in _text(value).split("|") if part.strip()]


def load_seed_data(conn) -> None:
    for row in _read("payment_options.csv"):
        payments.create_payment_option(
            conn,
            code=_text(row["code"]),
            label=_text(row["label"]),
            method=_text(row["method"]),
            issuer=_text(row["issuer"]),
            tenor_months=_int(row["tenor_months"]),
            surcharge_pct=_float(row["surcharge_pct"]),
            active=_flag(row["active"]),
        )

    for row in _read("products.csv"):
        catalog.create_product(
            conn,
            sku=_text(row["sku"]),
            name=_text(row["name"]),
            brand=_text(row["brand"]),
            category=_text(row["category"]),
            tracking=_text(row["tracking"]),
            cost=_int(row["cost"]),
            price=_int(row["price"]),
            reorder_level=_int(row["reorder_level"]),
            active=_flag(row["active"]),
        )

    for row in _read("initial_stock.csv"):
        product = catalog.get_product_by_sku(conn, _text(row["sku"]))
        if product is None:
            raise ValueError(f"initial_stock.csv references unknown SKU {row['sku']}")
        unit_cost = _opt_int(row["unit_cost"])
        if product["tracking"] == "none":
            inventory.receive_stock(
                conn, product_id=product["id"], qty=_int(row["qty"]), unit_cost=unit_cost, reference="OPENING"
            )
        else:
            inventory.receive_stock(
                conn, product_id=product["id"], serials=_pipe(row["serials"]), unit_cost=unit_cost, reference="OPENING"
            )

    for row in _read("promotions.csv"):
        promotions.create_promotion(
            conn,
            code=_text(row["code"]),
            name=_text(row["name"]),
            description=_text(row["description"]),
            reward_type=_text(row["reward_type"]),
            reward_value=_float(row["reward_value"]),
            max_reward=_opt_int(row["max_reward"]),
            min_spend=_int(row["min_spend"]),
            min_qty=_int(row["min_qty"], 1),
            stackable=_flag(row["stackable"]),
            start_date=_text(row["start_date"]) or None,
            end_date=_text(row["end_date"]) or None,
            active=_flag(row["active"]),
            skus=_pipe(row["eligible_skus"]),
            payment_codes=_pipe(row["required_payment_codes"]),
        )


def seed_if_empty(path: str | Path | None = None) -> bool:
    """Load demo data only when the products table is empty. Returns True if data was loaded."""
    with transaction(path, write=True) as conn:
        count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count:
            return False
        load_seed_data(conn)
        return True


def reset_demo_data(path: str | Path | None = None) -> None:
    init_database(path, seed=False)
    with transaction(path, write=True) as conn:
        for table in CLEAR_ORDER:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence")
        load_seed_data(conn)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or reset the POS database.")
    parser.add_argument("--reset", action="store_true", help="wipe all data and reload the demo seed")
    args = parser.parse_args()
    if args.reset:
        reset_demo_data()
        print(f"Demo data reloaded into {config.DB_PATH}")
    else:
        init_database()
        print(f"Database ready at {config.DB_PATH}")


if __name__ == "__main__":
    main()
