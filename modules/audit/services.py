"""
Audit services for school app features.

Writes to backend.core.models.AuditLog for tenant-scoped audit trail.
Used for critical operations like fees management.
"""

from typing import Any, Optional

from backend.core.database import db
from backend.core.models import AuditLog


def log_finance_action(
    action: str,
    tenant_id: str,
    user_id: Optional[str] = None,
    extra_data: Optional[dict] = None,
) -> None:
    """
    Record a finance action in audit_logs.

    Args:
        action: Action identifier (e.g. 'finance.payment.created', 'finance.payment.refunded').
        tenant_id: Tenant where the action occurred.
        user_id: User who performed the action (stored in extra_data for tenant actions).
        extra_data: Optional JSON-serializable extra data.
    """
    metadata = extra_data or {}
    if user_id:
        metadata["user_id"] = user_id

    entry = AuditLog(
        platform_admin_id=None,
        action=action,
        tenant_id=tenant_id,
        extra_data=metadata if metadata else None,
    )
    db.session.add(entry)
