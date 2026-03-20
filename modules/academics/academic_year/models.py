"""
Academic Year Model

Represents an academic year (e.g., 2025-2026) with date bounds.
Classes and students reference via academic_year_id. Finance fee_structures use FK only.
"""

from datetime import datetime
import uuid

from sqlalchemy import text

from backend.core.database import db
from backend.core.models import TenantBaseModel


class AcademicYear(TenantBaseModel):
    """
    Academic Year Model.

    Represents an academic year (e.g., 2025-2026) with date bounds.
    Scoped by tenant.
    """
    __tablename__ = "academic_years"
    __table_args__ = (
        db.UniqueConstraint("name", "tenant_id", name="uq_academic_years_name_tenant"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(20), nullable=False, index=True)  # e.g. "2025-2026"
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<AcademicYear {self.name}>"
