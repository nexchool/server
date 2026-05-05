"""TenantAuditLog — tenant-scoped admin action trail for admin-web.

Separate from core.models.AuditLog which is platform/super-admin scoped.
"""

from datetime import datetime, timezone
import uuid

from core.database import db


class TenantAuditLog(db.Model):
    """Rich audit trail for tenant admin actions (finance, setup, students, users)."""

    __tablename__ = "tenant_audit_logs"
    __tenant_scoped__ = True

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_id = db.Column(
        db.String(36),
        db.ForeignKey("school_units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_name = db.Column(db.Text, nullable=False)
    actor_role = db.Column(db.String(50), nullable=False)
    module = db.Column(db.String(50), nullable=False, index=True)
    action = db.Column(db.String(100), nullable=False)
    resource_type = db.Column(db.String(50), nullable=False)
    resource_id = db.Column(db.String(36), nullable=True)
    description = db.Column(db.Text, nullable=False)
    meta = db.Column(db.JSON, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    def __repr__(self):
        return f"<TenantAuditLog {self.module}.{self.action} tenant={self.tenant_id}>"
