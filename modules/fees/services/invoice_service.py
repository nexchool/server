"""
Invoice Service

Creates invoices, lists with filters, gets detail with payments.
Business rules: status derived from total_payments vs total_amount.
"""
from shared.safe_error import safe_error

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import selectinload

from core.database import db
from core.tenant import get_tenant_id
from core.branch_scope import (
    BranchForbidden,
    assert_student_allowed,
    filter_fees_by_branch,
)
from modules.fees.models import FeeInvoice, FeeInvoiceItem, FeePayment
from modules.students.models import Student
from modules.audit.services import log_finance_action
from core.school_time import school_today


def _next_invoice_number(tenant_id: str, academic_year: str) -> str:
    """Generate next invoice number: INV-YYYY-NNN."""
    prefix = f"INV-{academic_year[:4] if academic_year else school_today().year}-"
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

    # Branch scope: a restricted sub-admin may only create invoices for
    # students in their branches. No-op for unrestricted users.
    assert_student_allowed(student_id)

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
        return {"success": False, "error": safe_error(e)}


INVOICE_PAGE_SIZE = 25
INVOICE_MAX_PAGE_SIZE = 100

# Neither of these is a stored status. "Pending" is three at once, and
# "overdue" is derived from the due date — the mobile screen worked both out
# per row in the browser, which stops being possible once the list is paged.
UNSETTLED_STATUSES = ("unpaid", "partial", "draft")
OWING_STATUSES = ("unpaid", "partial")


def _positive_int(value, *, default: int, maximum: Optional[int] = None) -> int:
    """Coerce a query-string number, falling back rather than raising."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    number = max(1, number)
    return min(number, maximum) if maximum else number


def _apply_status(query, status: Optional[str]):
    """Translate the screen's filter into SQL."""
    if not status:
        return query
    if status == "pending":
        return query.filter(FeeInvoice.status.in_(UNSETTLED_STATUSES))
    if status == "overdue":
        return query.filter(
            FeeInvoice.status.in_(OWING_STATUSES),
            FeeInvoice.due_date < school_today(),
        )
    return query.filter(FeeInvoice.status == status)


def _paid_by_invoice_subquery():
    """How much has been received against each invoice.

    Aggregated in its own subquery rather than joined into the main one: a
    plain join to `fee_payments` multiplies an invoice by its payments, which
    would double-count a part-paid invoice in the outstanding total.
    """
    return (
        db.session.query(
            FeePayment.invoice_id.label("invoice_id"),
            func.coalesce(func.sum(FeePayment.amount), 0).label("paid"),
        )
        .group_by(FeePayment.invoice_id)
        .subquery()
    )


def _summarise(query) -> Dict[str, Any]:
    """What is owed across the whole filtered set, and when it is next due.

    This is money on a screen, so it has to describe every matching invoice
    and not the page in hand. Cancelled invoices are not owed, and a fully
    settled one owes nothing.
    """
    paid = _paid_by_invoice_subquery()
    owed = FeeInvoice.total_amount - func.coalesce(paid.c.paid, 0)

    owing = (
        query.outerjoin(paid, paid.c.invoice_id == FeeInvoice.id)
        .filter(FeeInvoice.status != "cancelled")
        .with_entities(
            func.coalesce(func.sum(func.greatest(owed, 0)), 0),
            func.min(
                case((owed > 0, FeeInvoice.due_date), else_=None)
            ),
        )
        .one()
    )
    total_outstanding, next_due = owing
    return {
        "total_outstanding": float(total_outstanding or 0),
        "next_due_date": next_due.isoformat() if next_due else None,
    }


def list_invoices(
    student_id: Optional[str] = None,
    status: Optional[str] = None,
    academic_year: Optional[str] = None,
    page=None,
    per_page=None,
) -> Dict[str, Any]:
    """One page of invoices, plus what is owed across the whole filtered set.

    Returns ``{items, total, page, per_page, total_pages, summary}``.

    The summary is a SQL aggregate over every matching invoice, not over
    `items`: the screen shows an amount outstanding and a next due date, and
    computing those from a page would put a wrong number of rupees in front of
    whoever is looking.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {
            "items": [], "total": 0, "page": 1, "per_page": 0, "total_pages": 1,
            "summary": {"total_outstanding": 0.0, "next_due_date": None},
        }

    # Branch scope: if a specific student is requested, assert access first;
    # then restrict the whole list to the caller's allowed-branch students.
    if student_id:
        assert_student_allowed(student_id)

    query = FeeInvoice.query.filter_by(tenant_id=tenant_id)
    query = filter_fees_by_branch(query, FeeInvoice.student_id)
    if student_id:
        query = query.filter_by(student_id=student_id)
    query = _apply_status(query, status)
    if academic_year:
        query = query.filter_by(academic_year=academic_year)

    total = query.count()
    summary = _summarise(query)

    page = _positive_int(page, default=1)
    per_page = _positive_int(
        per_page, default=INVOICE_PAGE_SIZE, maximum=INVOICE_MAX_PAGE_SIZE
    )

    invoices = (
        # `to_dict` sums `self.payments`; without this that is a query per row.
        query.options(selectinload(FeeInvoice.payments))
        # A batch of invoices is generated in one run, so created_at ties and
        # is not on its own a total order for LIMIT/OFFSET.
        .order_by(FeeInvoice.created_at.desc(), FeeInvoice.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
        .all()
    )

    return {
        "items": [inv.to_dict() for inv in invoices],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "summary": summary,
    }


def get_invoice(invoice_id: str) -> Optional[Dict[str, Any]]:
    """Get invoice with items and payments."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None

    invoice = FeeInvoice.query.filter_by(id=invoice_id, tenant_id=tenant_id).first()
    if not invoice:
        return None

    # Branch scope: a restricted sub-admin may only read invoices of students
    # in their branches. No-op for unrestricted users.
    assert_student_allowed(invoice.student_id)

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

    # Branch scope: a restricted sub-admin may only cancel invoices of students
    # in their branches. No-op for unrestricted users.
    assert_student_allowed(invoice.student_id)

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
        return {"success": False, "error": safe_error(e)}
