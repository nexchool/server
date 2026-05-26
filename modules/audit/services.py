"""
Audit services for school app features.

Writes to core.models.AuditLog for tenant-scoped audit trail.
Used for critical operations like fees management.
"""

from typing import Any, Optional

from core.database import db
from core.models import AuditLog
from modules.audit.models import TenantAuditLog


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


def log_tenant_action(
    module: str,
    action: str,
    resource_type: str,
    description: str,
    tenant_id: str,
    actor_user_id: Optional[str] = None,
    actor_name: str = "System",
    actor_role: str = "system",
    resource_id: Optional[str] = None,
    unit_id: Optional[str] = None,
    meta: Optional[dict] = None,
) -> None:
    """
    Append a tenant-scoped audit entry to the current DB session.

    IMPORTANT: Does NOT commit. The caller owns the transaction.
    Call db.session.commit() after all writes in the same request/task.

    Args:
        module:        Feature area — 'finance', 'students', 'school_setup', 'users'
        action:        Machine-readable event — 'fee_payment_recorded', 'student_enrolled'
        resource_type: Model name — 'fee_invoice', 'student', 'class'
        description:   Human-readable sentence shown in audit log UI
        tenant_id:     Tenant context (required)
        actor_user_id: User who triggered the action (None for system/Celery jobs)
        actor_name:    Snapshot of user's display name at time of action
        actor_role:    Snapshot of user's primary role at time of action
        resource_id:   PK of the affected resource (string UUID)
        unit_id:       School unit the action was scoped to (optional)
        meta:          JSON-serializable extra context (before/after values, amounts, etc.)
    """
    entry = TenantAuditLog(
        tenant_id=tenant_id,
        unit_id=unit_id,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        actor_role=actor_role,
        module=module,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        description=description,
        meta=meta,
    )
    db.session.add(entry)
