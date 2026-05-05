"""
Grade Model

Master list of standards / grades offered by a tenant. The label is free
(e.g. "LKG", "UKG", "1", "10") because tenants in different boards label
their grades differently. `sequence` is the canonical ordering used for
sorting, promotion, and rollover.

Tenant-scoped. Unique per tenant by `name`.
"""

from datetime import datetime
import uuid

from sqlalchemy import Index, text

from core.database import db
from core.models import TenantBaseModel


class Grade(TenantBaseModel):
    """A standard / grade offered by a tenant (LKG, UKG, 1..12, …)."""

    __tablename__ = "grades"
    __table_args__ = (
        Index(
            "uq_grades_tenant_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    name = db.Column(db.String(50), nullable=False)
    sequence = db.Column(db.Integer, nullable=False, default=0, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    class_records = db.relationship(
        "Class",
        back_populates="grade",
        lazy=True,
        passive_deletes=True,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "sequence": self.sequence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<Grade {self.name} (seq={self.sequence})>"
