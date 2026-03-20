"""
Reminder Service

Sends invoice reminders via push notification, email, and in-app notification.
"""

from typing import Any, Dict, Optional

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.modules.fees.models import FeeInvoice
from backend.modules.notifications.models import Notification
from backend.modules.students.models import Student


def send_invoice_reminder(invoice_id: str) -> Dict[str, Any]:
    """
    Send reminder for unpaid/partial invoice to parent/student.

    Channels: in-app notification (always), push (if configured), email (if configured).
    Message: "Your school fee invoice #INV-2026-001 amount ₹25,000 is due on 15 Apr 2026."

    Returns:
        {"success": bool, "channels_sent": [...], "error": str}
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context required"}

    invoice = FeeInvoice.query.filter_by(id=invoice_id, tenant_id=tenant_id).first()
    if not invoice:
        return {"success": False, "error": "Invoice not found"}

    if invoice.status == "paid":
        return {"success": False, "error": "Invoice is already fully paid"}

    if invoice.status == "cancelled":
        return {"success": False, "error": "Cannot send reminder for cancelled invoice"}

    # Get student and their user (for notification)
    student = Student.query.filter_by(id=invoice.student_id, tenant_id=tenant_id).first()
    if not student or not student.user_id:
        return {"success": False, "error": "Student or linked user not found"}

    user_id = student.user_id
    amount = float(invoice.total_amount or 0)
    due_str = invoice.due_date.strftime("%d %b %Y") if invoice.due_date else "N/A"
    inv_num = invoice.invoice_number or invoice.id[:8]

    message = f"Your school fee invoice #{inv_num} amount ₹{amount:,.0f} is due on {due_str}."
    title = "Fee Invoice Reminder"

    channels_sent = []

    # 1. In-app notification (always)
    try:
        notif = Notification(
            tenant_id=tenant_id,
            user_id=user_id,
            type="FEE_INVOICE_REMINDER",
            channel="in_app",
            title=title,
            body=message,
            extra_data={
                "invoice_id": invoice_id,
                "invoice_number": inv_num,
                "amount": amount,
                "due_date": due_str,
            },
        )
        db.session.add(notif)
        db.session.flush()
        channels_sent.append("in_app")
    except Exception:
        pass

    # 2. Push notification (if FCM/Expo configured - stub for future)
    # channels_sent.append("push")

    # 3. Email (if mailer configured - stub for future)
    # channels_sent.append("email")

    try:
        db.session.commit()
        return {
            "success": True,
            "channels_sent": channels_sent,
            "message": message,
        }
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
