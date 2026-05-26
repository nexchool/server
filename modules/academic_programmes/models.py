"""
AcademicProgramme Model

A programme is a board (and optional medium of instruction) offered by a
tenant (e.g. "CBSE", "GSEB Gujarati"). Classes reference a programme so the
same grade name can exist under multiple programmes without collision.

Board and medium are kept as free strings for now; medium may be omitted when
not meaningful (e.g. default single-medium boards). They can be normalized into
their own master tables later without changing the public shape.

Tenant-scoped. Identified per-tenant by a short `code`.
"""

from datetime import datetime
import uuid

from sqlalchemy import CheckConstraint, Index, text

from core.database import db
from core.models import TenantBaseModel


PROGRAMME_STATUS_ACTIVE = "active"
PROGRAMME_STATUS_INACTIVE = "inactive"
PROGRAMME_STATUSES = (PROGRAMME_STATUS_ACTIVE, PROGRAMME_STATUS_INACTIVE)


class AcademicProgramme(TenantBaseModel):
    """Board (+ optional medium) combination offered by a tenant."""

    __tablename__ = "academic_programmes"
    __table_args__ = (
        Index(
            "uq_academic_programmes_tenant_code_active",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_academic_programmes_status",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    name = db.Column(db.String(255), nullable=False)  # Human readable, e.g. "CBSE" or "GSEB Gujarati"
    board = db.Column(db.String(64), nullable=False)  # e.g. "CBSE", "GSEB", "ICSE", "IB"
    medium = db.Column(db.String(64), nullable=True)  # legacy free-text mirror; prefer medium_id
    medium_id = db.Column(
        db.String(36),
        db.ForeignKey("mediums.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    code = db.Column(db.String(32), nullable=False, index=True)

    status = db.Column(
        db.String(20),
        nullable=False,
        default=PROGRAMME_STATUS_ACTIVE,
        index=True,
    )

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
        back_populates="programme",
        lazy=True,
        passive_deletes=True,
    )

    medium_ref = db.relationship(
        "Medium",
        foreign_keys=[medium_id],
        lazy=True,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "board": self.board,
            "medium": self.medium_ref.name if self.medium_ref else self.medium,
            "medium_id": self.medium_id,
            "code": self.code,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        med = self.medium or "—"
        return f"<AcademicProgramme {self.code} ({self.board}/{med})>"
