"""
Sub-Admins Models

Per-sub-admin branch (school-unit) access scoping.

`UserSchoolUnit` associates a user with the school units they are restricted
to. The rule is: **no rows for a user = unrestricted (access to all units)**;
one or more rows present = restricted to exactly those units. This lets a
tenant Admin scope a sub-admin to a subset of branches without changing the
default behaviour for unscoped users.

Tenant-scoped via TenantBaseModel.
"""

from datetime import datetime
import uuid

from core.database import db
from core.models import TenantBaseModel


class UserSchoolUnit(TenantBaseModel):
    """
    UserSchoolUnit Junction Table

    Maps users to the school units they may access (many-to-many). Scoped by
    tenant. Absence of rows for a user means the user is unrestricted.
    """
    __tablename__ = "user_school_units"

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "school_unit_id", "tenant_id",
            name="uq_user_school_unit",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    school_unit_id = db.Column(
        db.String(36),
        db.ForeignKey("school_units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "school_unit_id": self.school_unit_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return (
            f"<UserSchoolUnit user_id={self.user_id} "
            f"school_unit_id={self.school_unit_id}>"
        )

    def save(self):
        """Save user-school-unit mapping to database"""
        db.session.add(self)
        db.session.commit()
