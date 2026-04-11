"""Device push token storage (multi-tenant, per user)."""

from __future__ import annotations

import uuid
from datetime import datetime

from core.database import db
from core.models import TenantBaseModel


class DeviceToken(TenantBaseModel):
    """
    One row per device push token. device_token is globally unique; reassigned on login switch.
    """

    __tablename__ = "device_tokens"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_token = db.Column(db.String(512), nullable=False, unique=True, index=True)
    platform = db.Column(db.String(20), nullable=False)
    provider = db.Column(db.String(20), nullable=False, default="expo")
    app_version = db.Column(db.String(40), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    last_used_at = db.Column(db.DateTime(), nullable=True)
    created_at = db.Column(db.DateTime(), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime(),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user = db.relationship("User", backref=db.backref("device_tokens", lazy=True))

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "platform": self.platform,
            "provider": self.provider,
            "app_version": self.app_version,
            "is_active": self.is_active,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
