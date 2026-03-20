"""
Fee Payment Service

Records payments toward fee invoices. Handles partial payments, overpayment,
duplicate detection (payment_reference), and always creates a receipt.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.modules.fees.models import FeeInvoice, FeeInvoiceItem, FeePayment, FeeReceipt
from backend.modules.students.models import Student
from backend.modules.audit.services import log_finance_action
from .invoice_service import _recalculate_invoice_status


VALID_PAYMENT_METHODS = ("cash", "bank", "upi", "online")


def _next_receipt_number(tenant_id: str) -> str:
    """Generate receipt number: RCP-YYYY-NNN."""
    year = str(datetime.utcnow().year)
    prefix = f"RCP-{year}-"
    last = (
        FeeReceipt.query.filter(
            FeeReceipt.tenant_id == tenant_id,
            FeeReceipt.receipt_number.like(f"{prefix}%"),
        )
        .order_by(FeeReceipt.generated_at.desc())
        .first()
    )
    if not last:
        return f"{prefix}001"
    try:
        num = int(last.receipt_number.split("-")[-1])
        return f"{prefix}{num + 1:03d}"
    except (ValueError, IndexError):
        return f"{prefix}001"


def record_fee_payment(
    invoice_id: str,
    amount: Decimal,
    payment_method: str,
    payment_date: Optional[date] = None,
    payment_reference: Optional[str] = None,
    payment_gateway: Optional[str] = None,
    transaction_id: Optional[str] = None,
    collected_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Record a payment toward an invoice. Creates receipt. Idempotent on payment_reference.

    Handles:
    - Partial payment: allowed
    - Overpayment: allowed (invoice marked paid; no rollback)
    - Duplicate: if payment_reference already exists for this invoice, return existing
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context required"}

    invoice = FeeInvoice.query.filter_by(id=invoice_id, tenant_id=tenant_id).first()
    if not invoice:
        return {"success": False, "error": "Invoice not found"}

    if invoice.status == "cancelled":
        return {"success": False, "error": "Cannot record payment for cancelled invoice"}

    amt = Decimal(str(amount))
    if amt <= 0:
        return {"success": False, "error": "Amount must be positive"}

    method = (payment_method or "cash").lower()
    if method not in VALID_PAYMENT_METHODS:
        return {"success": False, "error": f"Invalid payment method. Use: {VALID_PAYMENT_METHODS}"}

    # Duplicate check: payment_reference unique per invoice
    if payment_reference:
        existing = FeePayment.query.filter_by(
            invoice_id=invoice_id,
            payment_reference=payment_reference,
            tenant_id=tenant_id,
        ).first()
        if existing:
            return {
                "success": True,
                "payment": existing.to_dict(),
                "receipt": existing.receipt.to_dict() if existing.receipt else None,
                "message": "Duplicate payment_reference; existing payment returned",
            }

    pay_date = payment_date or date.today()
    student_id = invoice.student_id

    payment = FeePayment(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        student_id=student_id,
        payment_reference=payment_reference,
        amount=amt,
        payment_method=method,
        payment_gateway=payment_gateway,
        transaction_id=transaction_id,
        payment_date=pay_date,
        collected_by=collected_by,
    )
    db.session.add(payment)
    db.session.flush()

    receipt_number = _next_receipt_number(tenant_id)
    receipt = FeeReceipt(
        tenant_id=tenant_id,
        payment_id=payment.id,
        receipt_number=receipt_number,
        generated_at=datetime.utcnow(),
        pdf_url=None,  # Generated on download
    )
    db.session.add(receipt)
    db.session.flush()

    _recalculate_invoice_status(invoice)

    try:
        db.session.commit()
        log_finance_action(
            action="fees.payment.recorded",
            tenant_id=tenant_id,
            user_id=collected_by,
            extra_data={
                "payment_id": payment.id,
                "invoice_id": invoice_id,
                "amount": float(amt),
                "receipt_number": receipt_number,
            },
        )
        return {
            "success": True,
            "payment": payment.to_dict(),
            "receipt": receipt.to_dict(),
            "invoice": invoice.to_dict(),
        }
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def get_fee_payment(payment_id: str) -> Optional[Dict[str, Any]]:
    """Get payment with receipt and invoice info."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None

    payment = FeePayment.query.filter_by(id=payment_id, tenant_id=tenant_id).first()
    if not payment:
        return None

    d = payment.to_dict()
    if payment.invoice:
        inv_dict = payment.invoice.to_dict()
        inv_dict["items"] = [it.to_dict() for it in payment.invoice.items]
        d["invoice"] = inv_dict
    return d
