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
    online = "online"
    bank_transfer = "bank_transfer"
