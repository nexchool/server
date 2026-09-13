"""Subscription payments: the operator's record of what a school has paid.

Nexchool has no invoices and no payment gateway. A school pays by bank
transfer, UPI, cheque or cash, and the operator writes it down here so both
sides can see the trail. A record is never edited or deleted: a mistake is
voided with a reason and stays on the list, struck through.
"""

from __future__ import annotations

import uuid

from core.database import db
from core.models import TenantBaseModel
from core.school_time import utc_now

PAYMENT_METHOD_BANK_TRANSFER = "bank_transfer"
PAYMENT_METHOD_UPI = "upi"
PAYMENT_METHOD_CHEQUE = "cheque"
PAYMENT_METHOD_CASH = "cash"
PAYMENT_METHOD_OTHER = "other"
PAYMENT_METHODS = (
    PAYMENT_METHOD_BANK_TRANSFER,
    PAYMENT_METHOD_UPI,
    PAYMENT_METHOD_CHEQUE,
    PAYMENT_METHOD_CASH,
    PAYMENT_METHOD_OTHER,
)


class SubscriptionPayment(TenantBaseModel):
    __tablename__ = "subscription_payments"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="INR", server_default="INR")
    paid_on = db.Column(db.Date, nullable=False)
    method = db.Column(db.String(30), nullable=False)
    #: Transaction number, cheque number, UPI reference — whatever the school quotes.
    reference = db.Column(db.String(120), nullable=True)
    #: The period this payment is for, when the operator states it.
    covers_from = db.Column(db.Date, nullable=True)
    covers_to = db.Column(db.Date, nullable=True)
    note = db.Column(db.Text, nullable=True)
    recorded_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    voided_at = db.Column(db.DateTime(timezone=True), nullable=True)
    void_reason = db.Column(db.Text, nullable=True)
    voided_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    recorded_by = db.relationship("User", foreign_keys=[recorded_by_user_id])

    __table_args__ = (
        db.CheckConstraint("amount > 0", name="ck_subscription_payments_amount_positive"),
        db.CheckConstraint(
            "method IN ('bank_transfer', 'upi', 'cheque', 'cash', 'other')",
            name="ck_subscription_payments_method",
        ),
        db.Index("idx_subscription_payments_tenant_paid_on", "tenant_id", "paid_on"),
    )

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "amount": float(self.amount),
            "currency": self.currency,
            "paid_on": self.paid_on.isoformat(),
            "method": self.method,
            "reference": self.reference,
            "covers_from": self.covers_from.isoformat() if self.covers_from else None,
            "covers_to": self.covers_to.isoformat() if self.covers_to else None,
            "note": self.note,
            "recorded_by": self.recorded_by.name if self.recorded_by else None,
            "voided_at": self.voided_at.isoformat() if self.voided_at else None,
            "void_reason": self.void_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
