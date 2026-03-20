"""
Fees Invoice + Receipt Models

fee_invoices, fee_invoice_items, fee_payments, fee_receipts
Multi-tenant using tenant_id. Never delete financial records.
"""

from datetime import datetime
import uuid

from backend.core.database import db
from backend.core.models import TenantBaseModel


class FeeInvoice(TenantBaseModel):
    """
    Fee Invoice Model.

    Represents a fee due for a student. Invoice remains until fully paid.
    Status: draft, unpaid, partial, paid, cancelled.
    """

    __tablename__ = "fee_invoices"
    __table_args__ = (
        db.Index("ix_fee_invoices_invoice_number_tenant", "invoice_number", "tenant_id"),
        db.Index("ix_fee_invoices_student_id", "student_id"),
        db.Index("ix_fee_invoices_status", "status"),
        db.Index("ix_fee_invoices_tenant_id", "tenant_id"),
        db.Index("ix_fee_invoices_academic_year", "academic_year"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = db.Column(
        db.String(36),
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invoice_number = db.Column(db.String(50), nullable=False, index=True)
    academic_year = db.Column(db.String(20), nullable=False, index=True)
    issue_date = db.Column(db.Date(), nullable=False)
    due_date = db.Column(db.Date(), nullable=False)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default="0")
    total_discount = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default="0")
    total_fine = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default="0")
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default="draft",
        index=True,
    )  # draft, unpaid, partial, paid, cancelled
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    student = db.relationship("Student", backref=db.backref("fee_invoices", lazy=True))
    items = db.relationship(
        "FeeInvoiceItem",
        backref=db.backref("invoice", lazy=True),
        order_by="FeeInvoiceItem.id",
    )
    payments = db.relationship(
        "FeePayment",
        backref=db.backref("invoice", lazy=True),
        order_by="FeePayment.created_at",
    )
    created_by_user = db.relationship("User", foreign_keys=[created_by])

    def to_dict(self):
        total_paid = sum(
            float(p.amount) for p in self.payments
        )
        remaining = float(self.total_amount) - total_paid
        return {
            "id": self.id,
            "student_id": self.student_id,
            "invoice_number": self.invoice_number,
            "academic_year": self.academic_year,
            "issue_date": self.issue_date.isoformat() if self.issue_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "subtotal": float(self.subtotal) if self.subtotal is not None else 0,
            "total_discount": float(self.total_discount) if self.total_discount is not None else 0,
            "total_fine": float(self.total_fine) if self.total_fine is not None else 0,
            "total_amount": float(self.total_amount) if self.total_amount is not None else 0,
            "status": self.status,
            "notes": self.notes,
            "amount_paid": total_paid,
            "remaining_balance": max(0, remaining),
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class FeeInvoiceItem(TenantBaseModel):
    """
    Fee Invoice Item Model.

    Line item within an invoice: fee_head, period, amount, discount, fine, net_amount.
    """

    __tablename__ = "fee_invoice_items"
    __table_args__ = (db.Index("ix_fee_invoice_items_invoice_id", "invoice_id"),)

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_id = db.Column(
        db.String(36),
        db.ForeignKey("fee_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fee_head = db.Column(db.String(100), nullable=False)
    period = db.Column(db.String(50), nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    discount = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default="0")
    fine = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default="0")
    net_amount = db.Column(db.Numeric(12, 2), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "invoice_id": self.invoice_id,
            "fee_head": self.fee_head,
            "period": self.period,
            "amount": float(self.amount) if self.amount is not None else 0,
            "discount": float(self.discount) if self.discount is not None else 0,
            "fine": float(self.fine) if self.fine is not None else 0,
            "net_amount": float(self.net_amount) if self.net_amount is not None else 0,
        }


class FeePayment(TenantBaseModel):
    """
    Fee Payment Model.

    Records a payment toward a fee invoice. Each payment generates a receipt.
    """

    __tablename__ = "fee_payments"
    __table_args__ = (
        db.Index("ix_fee_payments_invoice_id", "invoice_id"),
        db.Index("ix_fee_payments_student_id", "student_id"),
        db.Index("ix_fee_payments_payment_reference", "payment_reference"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_id = db.Column(
        db.String(36),
        db.ForeignKey("fee_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id = db.Column(
        db.String(36),
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_reference = db.Column(db.String(100), nullable=True, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    payment_method = db.Column(db.String(20), nullable=False, index=True)
    payment_gateway = db.Column(db.String(50), nullable=True)
    transaction_id = db.Column(db.String(100), nullable=True, index=True)
    payment_date = db.Column(db.Date(), nullable=False)
    collected_by = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    student = db.relationship("Student", backref=db.backref("fee_payments", lazy=True))
    receipt = db.relationship(
        "FeeReceipt",
        backref=db.backref("payment", lazy=True),
        uselist=False,
    )
    collected_by_user = db.relationship("User", foreign_keys=[collected_by])

    def to_dict(self):
        return {
            "id": self.id,
            "invoice_id": self.invoice_id,
            "student_id": self.student_id,
            "payment_reference": self.payment_reference,
            "amount": float(self.amount) if self.amount is not None else 0,
            "payment_method": self.payment_method,
            "payment_gateway": self.payment_gateway,
            "transaction_id": self.transaction_id,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "collected_by": self.collected_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "receipt": self.receipt.to_dict() if self.receipt else None,
        }


class FeeReceipt(TenantBaseModel):
    """
    Fee Receipt Model.

    One receipt per payment. Stores receipt_number and optional pdf_url.
    """

    __tablename__ = "fee_receipts"
    __table_args__ = (
        db.Index("ix_fee_receipts_payment_id", "payment_id"),
        db.UniqueConstraint("payment_id", "tenant_id", name="uq_fee_receipts_payment_tenant"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    payment_id = db.Column(
        db.String(36),
        db.ForeignKey("fee_payments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )
    receipt_number = db.Column(db.String(50), nullable=False, index=True)
    generated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    pdf_url = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "payment_id": self.payment_id,
            "receipt_number": self.receipt_number,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "pdf_url": self.pdf_url,
        }
