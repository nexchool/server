"""
Subjects Module - Models

Subject model for School ERP. Represents academic subjects offered by the school.
Scoped by tenant.
"""

from datetime import datetime
import uuid

from backend.core.database import db
from backend.core.models import TenantBaseModel


class Subject(TenantBaseModel):
    """
    Subject Model

    Represents an academic subject (e.g., Mathematics, Science).
    Scoped by tenant. Unique (name, tenant_id).
    """
    __tablename__ = "subjects"

    __table_args__ = (
        db.UniqueConstraint("name", "tenant_id", name="uq_subjects_name_tenant"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False, index=True)
    code = db.Column(db.String(20), nullable=True, index=True)
    description = db.Column(db.Text, nullable=True)

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
            "tenant_id": self.tenant_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<Subject {self.name}>"
