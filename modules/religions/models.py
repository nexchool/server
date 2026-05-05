"""
Religion Model

Tenant-scoped master list of religions used in admission / demographic
forms. Unique per tenant by `name`.
"""

from datetime import datetime
import uuid

from sqlalchemy import Index, text

from core.database import db
from core.models import TenantBaseModel


class Religion(TenantBaseModel):
    """A religion entry in a tenant's demographic master list."""

    __tablename__ = "religions"
    __table_args__ = (
        Index(
            "uq_religions_tenant_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    name = db.Column(db.String(100), nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<Religion {self.name}>"
