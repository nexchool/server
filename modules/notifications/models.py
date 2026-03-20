"""
Notification Module Models

Tenant-scoped notification model for in-app and outbound notifications.
NotificationTemplate for unified email/notification template management.
"""

from datetime import datetime
import uuid

from backend.core.database import db
from backend.core.models import TenantBaseModel


class Notification(TenantBaseModel):
    """
    Notification Model.

    In-app and outbound notifications (FEE_DUE, FEE_OVERDUE, PAYMENT_RECEIVED, etc.).
    Scoped by tenant.
    """
    __tablename__ = "notifications"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = db.Column(db.String(50), nullable=False, index=True)
    channel = db.Column(db.String(20), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text(), nullable=True)
    read_at = db.Column(db.DateTime(), nullable=True)
    extra_data = db.Column(db.JSON(), nullable=True)
    created_at = db.Column(db.DateTime(), nullable=False, default=datetime.utcnow, index=True)

    user = db.relationship("User", backref=db.backref("notifications", lazy=True))

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "type": self.type,
            "channel": self.channel,
            "title": self.title,
            "body": self.body,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "extra_data": self.extra_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Notification {self.type} user={self.user_id}>"


class NotificationTemplate(db.Model):
    """
    Notification Template Model.

    Stores subject and body templates for notifications (email, SMS, etc.).
    tenant_id NULL = global default; tenant_id NOT NULL = tenant override.
    """
    __tablename__ = "notification_templates"
    __tenant_scoped__ = False

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    type = db.Column(db.String(50), nullable=False, index=True)
    channel = db.Column(db.String(20), nullable=False, index=True)
    category = db.Column(db.String(20), nullable=False, index=True)
    is_system = db.Column(db.Boolean(), nullable=False, default=False)
    subject_template = db.Column(db.String(500), nullable=False)
    body_template = db.Column(db.Text(), nullable=False)
    created_at = db.Column(db.DateTime(), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "type": self.type,
            "channel": self.channel,
            "category": self.category,
            "is_system": self.is_system,
            "subject_template": self.subject_template,
            "body_template": self.body_template,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<NotificationTemplate {self.type}/{self.channel} tenant={self.tenant_id}>"
