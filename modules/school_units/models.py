"""
SchoolUnit Model

A SchoolUnit is a logical sub-school / campus inside a tenant. A tenant can
operate many units (e.g. "Modi Primary School", "Modi Higher Secondary
School") that share the same tenant subscription but have their own DISE
number, recognition, principal, branding and class hierarchy.

Tenant-scoped. Identified per-tenant by a short `code`.
"""

from datetime import datetime
import uuid

from sqlalchemy import CheckConstraint, Index, text

from core.database import db
from core.models import TenantBaseModel


SCHOOL_UNIT_TYPE_NURSERY = "nursery"
SCHOOL_UNIT_TYPE_PRIMARY = "primary"
SCHOOL_UNIT_TYPE_SECONDARY = "secondary"
SCHOOL_UNIT_TYPE_HIGHER_SECONDARY = "higher_secondary"
SCHOOL_UNIT_TYPE_OTHER = "other"

SCHOOL_UNIT_TYPES = (
    SCHOOL_UNIT_TYPE_NURSERY,
    SCHOOL_UNIT_TYPE_PRIMARY,
    SCHOOL_UNIT_TYPE_SECONDARY,
    SCHOOL_UNIT_TYPE_HIGHER_SECONDARY,
    SCHOOL_UNIT_TYPE_OTHER,
)

SCHOOL_UNIT_STATUS_ACTIVE = "active"
SCHOOL_UNIT_STATUS_INACTIVE = "inactive"
SCHOOL_UNIT_STATUSES = (SCHOOL_UNIT_STATUS_ACTIVE, SCHOOL_UNIT_STATUS_INACTIVE)


class SchoolUnit(TenantBaseModel):
    """A sub-school / campus inside a tenant."""

    __tablename__ = "school_units"
    __table_args__ = (
        # Active rows must have a unique code per tenant. Soft-deleted rows
        # are excluded so codes can be reused after archive.
        Index(
            "uq_school_units_tenant_code_active",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            "type IN ('nursery','primary','secondary','higher_secondary','other')",
            name="ck_school_units_type",
        ),
        CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_school_units_status",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    name = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(32), nullable=False, index=True)
    type = db.Column(
        db.String(20),
        nullable=False,
        default=SCHOOL_UNIT_TYPE_OTHER,
    )

    # Government / regulatory identifiers — optional, vary by board/region.
    dise_no = db.Column(db.String(64), nullable=True)
    index_no = db.Column(db.String(64), nullable=True)
    recognition_no = db.Column(db.String(64), nullable=True)
    gr_number_scheme = db.Column(
        db.String(64),
        nullable=True,
        comment="GR number format, e.g. 'MN-{SEQ}'. {SEQ} is replaced with zero-padded auto-increment per unit.",
    )

    phone = db.Column(db.String(32), nullable=True)
    address = db.Column(db.Text, nullable=True)

    logo_url = db.Column(db.String(500), nullable=True)
    principal_signature_url = db.Column(db.String(500), nullable=True)

    status = db.Column(
        db.String(20),
        nullable=False,
        default=SCHOOL_UNIT_STATUS_ACTIVE,
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

    # Classes assigned to this unit. Explicit `class_records` rather than a
    # generic `classes` collection so callers read intentionally.
    class_records = db.relationship(
        "Class",
        back_populates="school_unit",
        lazy=True,
        passive_deletes=True,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "type": self.type,
            "dise_no": self.dise_no,
            "index_no": self.index_no,
            "recognition_no": self.recognition_no,
            "gr_number_scheme": self.gr_number_scheme,
            "phone": self.phone,
            "address": self.address,
            "logo_url": self.logo_url,
            "principal_signature_url": self.principal_signature_url,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<SchoolUnit {self.code} ({self.type})>"
