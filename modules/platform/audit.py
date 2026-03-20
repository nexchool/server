"""
Platform Audit Logging

Helper for logging critical platform actions. Used only in platform routes.
"""

from backend.core.database import db
from backend.core.models import AuditLog


def log_platform_action(
    platform_admin_id: str,
    action: str,
    tenant_id: str = None,
    metadata: dict = None,
) -> None:
    """
    Record a critical platform action in audit_logs.

    Args:
        platform_admin_id: User ID of the platform admin who performed the action.
        action: Action identifier (e.g. 'tenant.created', 'tenant.suspended').
        tenant_id: Optional tenant affected (null for platform-wide actions).
        metadata: Optional JSON-serializable extra data.
    """
    entry = AuditLog(
        platform_admin_id=platform_admin_id,
        action=action,
        tenant_id=tenant_id,
        extra_data=metadata,
    )
    db.session.add(entry)
    db.session.commit()
