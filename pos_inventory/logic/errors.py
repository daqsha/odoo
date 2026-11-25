"""Exceptions raised by business rules. Their messages are shown to the cashier as-is."""


class BusinessError(Exception):
    """Invalid input or a rule the user must fix before continuing."""


class StockError(BusinessError):
    """Requested quantity or serial number is not available in stock."""


class PromotionError(BusinessError):
    """A promotion's terms and conditions are not met for the current cart and payment."""
