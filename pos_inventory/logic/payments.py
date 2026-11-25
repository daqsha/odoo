"""Payment options. A payment option is a method plus issuer plus tenor, for example
'BCA Credit Card, 12-month installment, 1.5% fee'. Promotions can require specific options."""

from __future__ import annotations

import sqlite3

from logic.errors import BusinessError
from logic.models import PaymentOption

METHOD_LABELS = {
    "CASH": "Cash",
    "DEBIT_CARD": "Debit card",
    "CREDIT_CARD": "Credit card",
    "EWALLET": "E-wallet",
    "TRANSFER": "Bank transfer",
}


def _from_row(row: sqlite3.Row) -> PaymentOption:
    return PaymentOption(
        id=row["id"],
        code=row["code"],
        label=row["label"],
        method=row["method"],
        issuer=row["issuer"],
        tenor_months=row["tenor_months"],
        surcharge_pct=float(row["surcharge_pct"]),
        active=bool(row["active"]),
    )


def load_payment_options(conn: sqlite3.Connection, *, active_only: bool = True) -> list[PaymentOption]:
    sql = "SELECT * FROM payment_options" + (" WHERE active = 1" if active_only else "") + " ORDER BY id"
    return [_from_row(row) for row in conn.execute(sql)]


def get_payment_by_code(conn: sqlite3.Connection, code: str) -> PaymentOption | None:
    row = conn.execute("SELECT * FROM payment_options WHERE code = ?", (code,)).fetchone()
    return _from_row(row) if row else None


def create_payment_option(
    conn: sqlite3.Connection,
    *,
    code: str,
    label: str,
    method: str,
    issuer: str = "",
    tenor_months: int = 0,
    surcharge_pct: float = 0.0,
    active: bool = True,
) -> int:
    code = code.strip().upper()
    if not code:
        raise BusinessError("Payment code is required.")
    if not label.strip():
        raise BusinessError("Payment label is required.")
    if method not in METHOD_LABELS:
        raise BusinessError("Unknown payment method.")
    if int(tenor_months) < 0:
        raise BusinessError("Tenor cannot be negative (use 0 for full payment).")
    if not 0 <= float(surcharge_pct) <= 10:
        raise BusinessError("Payment fee must be between 0 and 10 percent.")
    try:
        cur = conn.execute(
            """INSERT INTO payment_options
               (code, label, method, issuer, tenor_months, surcharge_pct, active)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (code, label.strip(), method, issuer.strip(), int(tenor_months), float(surcharge_pct), 1 if active else 0),
        )
    except sqlite3.IntegrityError as exc:
        raise BusinessError(f"Payment code {code} already exists.") from exc
    return int(cur.lastrowid)


def set_payment_active(conn: sqlite3.Connection, code: str, active: bool) -> None:
    conn.execute("UPDATE payment_options SET active = ? WHERE code = ?", (1 if active else 0, code))


def payment_label(option: PaymentOption) -> str:
    fee = f" · fee {option.surcharge_pct:g}%" if option.surcharge_pct else ""
    return f"{option.label}{fee}"
