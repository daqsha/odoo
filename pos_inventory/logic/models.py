"""Plain data objects shared by the rule engine, pricing and the UI. No database access here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

PERCENT_OFF = "PERCENT_OFF"
FIXED_OFF = "FIXED_OFF"
CASHBACK = "CASHBACK"
DISCOUNT_TYPES = frozenset({PERCENT_OFF, FIXED_OFF})


@dataclass(frozen=True)
class CartLine:
    product_id: int
    sku: str
    name: str
    unit_price: int
    qty: int = 1
    serial_no: str | None = None

    @property
    def line_total(self) -> int:
        return self.unit_price * self.qty


@dataclass(frozen=True)
class PaymentOption:
    id: int
    code: str
    label: str
    method: str
    issuer: str
    tenor_months: int
    surcharge_pct: float
    active: bool


@dataclass(frozen=True)
class Promotion:
    id: int
    code: str
    name: str
    description: str
    reward_type: str
    reward_value: float
    max_reward: int | None
    min_spend: int
    min_qty: int
    stackable: bool
    start_date: date | None
    end_date: date | None
    active: bool
    eligible_skus: frozenset[str] = frozenset()
    required_payments: tuple[tuple[str, str], ...] = ()  # (payment code, label)

    @property
    def allowed_payment_codes(self) -> frozenset[str]:
        return frozenset(code for code, _ in self.required_payments)

    def covers(self, line: CartLine) -> bool:
        """True when the line is an eligible item for this promotion."""
        return not self.eligible_skus or line.sku in self.eligible_skus


@dataclass(frozen=True)
class Evaluation:
    """Result of checking one promotion against the cart and payment method."""

    promotion: Promotion
    eligible: bool
    reasons: tuple[str, ...]
    eligible_subtotal: int
    eligible_qty: int


@dataclass(frozen=True)
class LineQuote:
    index: int
    product_id: int
    sku: str
    name: str
    serial_no: str | None
    qty: int
    unit_price: int
    list_total: int
    discount: int
    net_total: int


@dataclass(frozen=True)
class PromoApplication:
    promotion: Promotion
    discount: int = 0
    cashback: int = 0


@dataclass(frozen=True)
class Quote:
    lines: tuple[LineQuote, ...]
    payment: PaymentOption | None
    applications: tuple[PromoApplication, ...]
    subtotal: int
    promo_discount: int
    items_net: int
    surcharge: int
    total_due: int
    cashback: int
    effective_total: int
    tax_included: int
