"""
Finance module Enums.

Defines status and type enumerations for fees and payments.
"""

import enum


class StudentFeeStatus(str, enum.Enum):
    unpaid = "unpaid"
    partial = "partial"
    paid = "paid"
    overdue = "overdue"


class PaymentStatus(str, enum.Enum):
    success = "success"
    failed = "failed"
    refunded = "refunded"


class PaymentMethod(str, enum.Enum):
    cash = "cash"
    upi = "upi"
    bank_transfer = "bank_transfer"
    cheque = "cheque"
    other = "other"


# Incoming API aliases → canonical stored `method` value
_PAYMENT_METHOD_ALIASES: dict[str, str] = {
    "bank": PaymentMethod.bank_transfer.value,
    "online": PaymentMethod.upi.value,
}


def normalize_payment_method(method: str | None) -> str | None:
    """Lowercase and map legacy aliases (e.g. bank → bank_transfer)."""
    if method is None:
        return None
    m = method.strip().lower()
    if not m:
        return None
    return _PAYMENT_METHOD_ALIASES.get(m, m)
