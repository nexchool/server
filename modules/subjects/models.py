"""
Subjects Module - Models

Subject model for School ERP. Represents academic subjects offered by the school.
Scoped by tenant.
"""

from datetime import datetime
import uuid

from sqlalchemy import Index, text

from backend.core.database import db
from backend.core.models import TenantBaseModel
from sqlalchemy.dialects.postgresql import JSONB


class Subject(TenantBaseModel):
    """
    Subject Model

    Represents an academic subject (e.g., Mathematics, Science).
    Scoped by tenant. Unique (name, tenant_id).
    Optional unique (tenant_id, code) when code is set and row is not soft-deleted.
    """
    __tablename__ = "subjects"

    __table_args__ = (
        db.UniqueConstraint("name", "tenant_id", name="uq_subjects_name_tenant"),
        Index(
            "uq_subjects_tenant_code_active",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("code IS NOT NULL AND deleted_at IS NULL"),
        ),
        db.Index("ix_subjects_tenant_active", "tenant_id", "is_active"),
        db.Index("ix_subjects_tenant_type", "tenant_id", "subject_type"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False, index=True)
    code = db.Column(db.String(20), nullable=True, index=True)
    description = db.Column(db.Text, nullable=True)
    subject_type = db.Column(db.String(20), nullable=False, default="core")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    default_grading_scale_id = db.Column(db.String(36), nullable=True)  # future FK to grading_scales
    metadata_json = db.Column(JSONB, nullable=True)
    created_by = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "subject_type": self.subject_type,
            "is_active": self.is_active,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<Subject {self.name}>"
