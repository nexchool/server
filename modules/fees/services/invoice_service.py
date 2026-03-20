"""
Invoice Service

Creates invoices, lists with filters, gets detail with payments.
Business rules: status derived from total_payments vs total_amount.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.modules.fees.models import FeeInvoice, FeeInvoiceItem, FeePayment
from backend.modules.students.models import Student
from backend.modules.audit.services import log_finance_action


def _next_invoice_number(tenant_id: str, academic_year: str) -> str:
    """Generate next invoice number: INV-YYYY-NNN."""
    prefix = f"INV-{academic_year[:4] if academic_year else date.today().year}-"
    last = (
        FeeInvoice.query.filter(
            FeeInvoice.tenant_id == tenant_id,
            FeeInvoice.invoice_number.like(f"{prefix}%"),
        )
        .order_by(FeeInvoice.created_at.desc())
        .first()
    )
    if not last:
        return f"{prefix}001"
    try:
        num = int(last.invoice_number.split("-")[-1])
        return f"{prefix}{num + 1:03d}"
    except (ValueError, IndexError):
        return f"{prefix}001"


def _recalculate_invoice_status(invoice: FeeInvoice) -> None:
    """Update invoice status based on total payments vs total_amount."""
    if invoice.status == "cancelled":
        return

    total = Decimal(str(invoice.total_amount or 0))
    payments_sum = (
        db.session.query(db.func.coalesce(db.func.sum(FeePayment.amount), 0))
        .filter(FeePayment.invoice_id == invoice.id)
        .scalar()
        or 0
    )
    total_paid = Decimal(str(payments_sum))

    if total_paid >= total and total > 0:
        invoice.status = "paid"
    elif total_paid > 0:
        invoice.status = "partial"
    else:
        invoice.status = "unpaid" if invoice.status != "draft" else "draft"


def create_invoice(
    student_id: str,
    academic_year: str,
    issue_date: date,
    due_date: date,
    items: List[Dict[str, Any]],
    notes: Optional[str] = None,
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a fee invoice with items.

    items: [{"fee_head": str, "period": str, "amount": Decimal, "discount": Decimal, "fine": Decimal}, ...]
    Returns: {"success": bool, "invoice": dict, "error": str}
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context required"}

    student = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
    if not student:
        return {"success": False, "error": "Student not found"}

    if not items:
        return {"success": False, "error": "At least one fee item is required"}

    subtotal = Decimal("0")
    total_discount = Decimal("0")
    total_fine = Decimal("0")
    invoice_items = []
    for it in items:
        amt = Decimal(str(it.get("amount", 0)))
        disc = Decimal(str(it.get("discount", 0)))
        fine = Decimal(str(it.get("fine", 0)))
        net = amt - disc + fine
        subtotal += amt
        total_discount += disc
        total_fine += fine
        invoice_items.append({
            "fee_head": str(it.get("fee_head", "")).strip(),
            "period": str(it.get("period", "")).strip() or None,
            "amount": amt,
            "discount": disc,
            "fine": fine,
            "net_amount": net,
        })

    total_amount = subtotal - total_discount + total_fine
    invoice_number = _next_invoice_number(tenant_id, academic_year)

    invoice = FeeInvoice(
        tenant_id=tenant_id,
        student_id=student_id,
        invoice_number=invoice_number,
        academic_year=academic_year,
        issue_date=issue_date,
        due_date=due_date,
        subtotal=subtotal,
        total_discount=total_discount,
        total_fine=total_fine,
        total_amount=total_amount,
        status="unpaid",
        notes=notes,
        created_by=created_by,
    )
    db.session.add(invoice)
    db.session.flush()

    for it in invoice_items:
        db.session.add(
            FeeInvoiceItem(
                tenant_id=tenant_id,
                invoice_id=invoice.id,
                fee_head=it["fee_head"],
                period=it["period"],
                amount=it["amount"],
                discount=it["discount"],
                fine=it["fine"],
                net_amount=it["net_amount"],
            )
        )

    try:
        db.session.commit()
        log_finance_action(
            action="fees.invoice.created",
            tenant_id=tenant_id,
            user_id=created_by,
            extra_data={"invoice_id": invoice.id, "invoice_number": invoice_number},
        )
        return {"success": True, "invoice": invoice.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def list_invoices(
    student_id: Optional[str] = None,
    status: Optional[str] = None,
    academic_year: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List invoices with optional filters."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []

    query = FeeInvoice.query.filter_by(tenant_id=tenant_id)
    if student_id:
        query = query.filter_by(student_id=student_id)
    if status:
        query = query.filter_by(status=status)
    if academic_year:
        query = query.filter_by(academic_year=academic_year)
    query = query.order_by(FeeInvoice.created_at.desc())

    invoices = query.all()
    return [inv.to_dict() for inv in invoices]


def get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    """Get invoice with items and payments."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None

    invoice = FeeInvoice.query.filter_by(id=invoice_id, tenant_id=tenant_id).first()
    if not invoice:
        return None

    d = invoice.to_dict()
    d["items"] = [it.to_dict() for it in invoice.items]
    d["payments"] = [p.to_dict() for p in invoice.payments]
    return d


def cancel_invoice(invoice_id: str) -> Dict[str, Any]:
    """Cancel invoice if no payments. Audit-safe: no deletion."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context required"}

    invoice = FeeInvoice.query.filter_by(id=invoice_id, tenant_id=tenant_id).first()
    if not invoice:
        return {"success": False, "error": "Invoice not found"}

    if invoice.payments:
        return {"success": False, "error": "Cannot cancel invoice with existing payments"}

    invoice.status = "cancelled"
    try:
        db.session.commit()
        log_finance_action(
            action="fees.invoice.cancelled",
            tenant_id=tenant_id,
            extra_data={"invoice_id": invoice_id},
        )
        return {"success": True, "invoice": invoice.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
