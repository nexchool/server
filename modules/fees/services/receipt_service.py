"""
Receipt Service

Generates fee receipts (one per payment). Receipt record is created when
payment is recorded. PDF is generated on-the-fly for download.
"""

from typing import Optional

from core.tenant import get_tenant_id
from core.branch_scope import assert_student_allowed
from modules.fees.models import FeePayment, FeeReceipt
from modules.fees.services.pdf_service import generate_receipt_pdf


def get_receipt_pdf_bytes(payment_id: str) -> Optional[bytes]:
    """
    Get receipt PDF bytes for download. Generates on-the-fly from payment data.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None

    payment = FeePayment.query.filter_by(
        id=payment_id,
        tenant_id=tenant_id,
    ).first()

    if not payment:
        return None

    # Branch scope: only students in the caller's branches. No-op when
    # unrestricted.
    assert_student_allowed(payment.student_id)

    return generate_receipt_pdf(payment_id)
