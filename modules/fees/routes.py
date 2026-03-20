"""
Fees API Routes

Invoices, payments, receipts, reminders. Requires tenant_id and RBAC.
"""

from flask import request, g, send_file
import io

from backend.modules.fees import fees_bp
from backend.core.decorators import auth_required, tenant_required, require_plan_feature
from backend.core.decorators.rbac import require_permission, require_any_permission
from backend.shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
)

from .services import invoice_service, fee_payment_service, receipt_service, reminder_service
from .services.pdf_service import generate_invoice_pdf, generate_receipt_pdf

# Permissions
PERM_INVOICE_CREATE = "fees.invoice.create"
PERM_INVOICE_READ = "fees.invoice.read"
PERM_INVOICE_SEND_REMINDER = "fees.invoice.send_reminder"
PERM_PAYMENT_RECORD = "fees.payment.record"
PERM_RECEIPT_DOWNLOAD = "fees.receipt.download"


# ---------- Invoices ----------

@fees_bp.route("/invoices", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_permission(PERM_INVOICE_CREATE)
def create_invoice():
    """POST /api/fees/invoices - Create invoice."""
    data = request.get_json() or {}
    student_id = data.get("student_id")
    academic_year = data.get("academic_year")
    issue_date = data.get("issue_date")
    due_date = data.get("due_date")
    items = data.get("items", [])
    notes = data.get("notes")

    if not all([student_id, academic_year, issue_date, due_date]):
        return validation_error_response({
            "student_id": "Required",
            "academic_year": "Required",
            "issue_date": "Required",
            "due_date": "Required",
        })

    if not items:
        return validation_error_response({"items": "At least one fee item is required"})

    try:
        from datetime import datetime
        issue_d = datetime.strptime(issue_date, "%Y-%m-%d").date()
        due_d = datetime.strptime(due_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return validation_error_response({
            "issue_date": "Use YYYY-MM-DD format",
            "due_date": "Use YYYY-MM-DD format",
        })

    result = invoice_service.create_invoice(
        student_id=student_id,
        academic_year=academic_year,
        issue_date=issue_d,
        due_date=due_d,
        items=items,
        notes=notes,
        created_by=g.current_user.id if g.current_user else None,
    )

    if result["success"]:
        return success_response(data=result, message="Invoice created", status_code=201)
    return error_response("InvoiceError", result["error"], 400)


@fees_bp.route("/invoices", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_any_permission(PERM_INVOICE_READ, "finance.read", "finance.manage")
def list_invoices():
    """GET /api/fees/invoices - List invoices with optional filters."""
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    academic_year = request.args.get("academic_year")

    data = invoice_service.list_invoices(
        student_id=student_id,
        status=status,
        academic_year=academic_year,
    )
    return success_response(data={"invoices": data})


@fees_bp.route("/invoices/<invoice_id>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_any_permission(PERM_INVOICE_READ, "finance.read", "finance.manage")
def get_invoice(invoice_id):
    """GET /api/fees/invoices/<id> - Get invoice detail with payments."""
    data = invoice_service.get_invoice(invoice_id)
    if not data:
        return not_found_response("Invoice")
    return success_response(data=data)


@fees_bp.route("/invoices/<invoice_id>/send-reminder", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_permission(PERM_INVOICE_SEND_REMINDER)
def send_invoice_reminder(invoice_id):
    """POST /api/fees/invoices/<id>/send-reminder - Send invoice reminder."""
    result = reminder_service.send_invoice_reminder(invoice_id)
    if result["success"]:
        return success_response(data=result)
    if "not found" in result.get("error", "").lower():
        return not_found_response("Invoice")
    return error_response("ReminderError", result["error"], 400)


@fees_bp.route("/invoices/<invoice_id>/download", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_any_permission(PERM_INVOICE_READ, PERM_RECEIPT_DOWNLOAD, "finance.read", "finance.manage")
def download_invoice_pdf(invoice_id):
    """GET /api/fees/invoices/<id>/download - Generate and download invoice PDF."""
    from backend.modules.fees.services.invoice_service import get_invoice

    inv = get_invoice(invoice_id)
    if not inv:
        return not_found_response("Invoice")

    pdf_bytes = generate_invoice_pdf(invoice_id)
    if not pdf_bytes:
        return error_response("PDFError", "Failed to generate invoice PDF", 500)

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"invoice_{inv.get('invoice_number', invoice_id)}.pdf",
    )


# ---------- Payments ----------

@fees_bp.route("/payments", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_permission(PERM_PAYMENT_RECORD)
def record_payment():
    """POST /api/fees/payments - Record payment toward invoice."""
    data = request.get_json() or {}
    invoice_id = data.get("invoice_id")
    amount = data.get("amount")
    payment_method = data.get("payment_method", "cash")
    payment_date = data.get("payment_date")
    payment_reference = data.get("payment_reference")
    payment_gateway = data.get("payment_gateway")
    transaction_id = data.get("transaction_id")

    if not invoice_id or amount is None:
        return validation_error_response({"invoice_id": "Required", "amount": "Required"})

    try:
        from decimal import Decimal
        from datetime import datetime
        amt = Decimal(str(amount))
        pay_date = None
        if payment_date:
            pay_date = datetime.strptime(payment_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return validation_error_response({"amount": "Must be a number", "payment_date": "Use YYYY-MM-DD"})

    result = fee_payment_service.record_fee_payment(
        invoice_id=invoice_id,
        amount=amt,
        payment_method=payment_method,
        payment_date=pay_date,
        payment_reference=payment_reference,
        payment_gateway=payment_gateway,
        transaction_id=transaction_id,
        collected_by=g.current_user.id if g.current_user else None,
    )

    if result["success"]:
        return success_response(data=result, message="Payment recorded", status_code=201)
    if "not found" in result.get("error", "").lower():
        return not_found_response("Invoice")
    return error_response("PaymentError", result["error"], 400)


@fees_bp.route("/payments/<payment_id>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_any_permission(PERM_INVOICE_READ, PERM_PAYMENT_RECORD, "finance.read", "finance.manage")
def get_payment(payment_id):
    """GET /api/fees/payments/<id> - Get payment detail."""
    data = fee_payment_service.get_fee_payment(payment_id)
    if not data:
        return not_found_response("Payment")
    return success_response(data=data)


# ---------- Receipts ----------

@fees_bp.route("/receipts/<payment_id>/download", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("fees_management")
@require_any_permission(PERM_RECEIPT_DOWNLOAD, "finance.read", "finance.manage")
def download_receipt_pdf(payment_id):
    """GET /api/fees/receipts/<payment_id>/download - Generate and download receipt PDF."""
    payment = fee_payment_service.get_fee_payment(payment_id)
    if not payment:
        return not_found_response("Payment")

    pdf_bytes = receipt_service.get_receipt_pdf_bytes(payment_id)
    if not pdf_bytes:
        return error_response("PDFError", "Failed to generate receipt PDF", 500)

    receipt_num = payment.get("receipt", {}).get("receipt_number", "receipt")
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"receipt_{receipt_num}.pdf",
    )
