"""Department model — a tenant's customizable academic department catalogue.

Deliberately flat: a school may put grade bands (Primary, Higher Secondary),
streams (Science, Commerce) and subject divisions (Mathematics) in the same
list. `type` exists so administrative departments (Accounts, HR, Library) can
join the same table later without a migration; it is not exposed in the UI and
always takes its default in this version.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Index, text

from core.database import db
from core.models import TenantBaseModel

DEPARTMENT_STATUS_ACTIVE = "active"
DEPARTMENT_STATUS_INACTIVE = "inactive"
DEPARTMENT_STATUSES = (DEPARTMENT_STATUS_ACTIVE, DEPARTMENT_STATUS_INACTIVE)

DEPARTMENT_TYPE_ACADEMIC = "academic_division"


class Department(TenantBaseModel):
    """An academic department scoped to one tenant."""

    __tablename__ = "departments"
    __table_args__ = (
        # Partial unique indexes: soft-deleted rows are excluded so a name or
        # code can be reused after archiving. Lowercased so "Science" and
        # "science" cannot both exist — the whole point is one canonical name.
        Index(
            "uq_departments_tenant_name_active",
            "tenant_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_departments_tenant_code_active",
            "tenant_id",
            text("lower(code)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND code IS NOT NULL"),
        ),
        Index(
            "idx_departments_tenant_display_order",
            "tenant_id",
            "display_order",
            "name",
        ),
        CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_departments_status",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), nullable=True)
    description = db.Column(db.Text, nullable=True)
    display_order = db.Column(
        db.SmallInteger, nullable=False, server_default=text("0")
    )
    type = db.Column(
        db.String(32),
        nullable=False,
        server_default=text(f"'{DEPARTMENT_TYPE_ACADEMIC}'"),
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        server_default=text(f"'{DEPARTMENT_STATUS_ACTIVE}'"),
    )

    created_by = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def to_dict(self, teacher_count: int = 0, class_count: int = 0) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "display_order": self.display_order,
            "type": self.type,
            "status": self.status,
            "teacher_count": teacher_count,
            "class_count": class_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
