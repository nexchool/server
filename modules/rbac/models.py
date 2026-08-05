"""
RBAC Models

Database models for roles, permissions, and their relationships.
"""

from core.database import db
from core.models import TenantBaseModel
from datetime import datetime
import uuid


class Role(TenantBaseModel):
    """
    Role Model
    
    Represents a role that groups permissions together.
    Roles are assigned to users, and users inherit permissions from their roles.
    Scoped by tenant.
    
    Examples: Admin, Teacher, Student, Parent
    """
    __tablename__ = "roles"
    __table_args__ = (
        db.UniqueConstraint("name", "tenant_id", name="uq_roles_name_tenant"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(50), nullable=False, index=True)
    description = db.Column(db.String(255), nullable=True)
    is_subadmin = db.Column(db.Boolean, nullable=False, default=False)

    # Set when holding a business relationship implies this profile, rather than
    # it being granted. A student's access follows from being a student; nobody
    # assigns it. Marked here rather than matched by name so that renaming the
    # profile cannot silently remove everyone's access.
    implied_by_relationship = db.Column(db.String(30), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    permissions = db.relationship(
        "Permission",
        secondary="role_permissions",
        backref=db.backref("roles", lazy=True)
    )

    def __repr__(self):
        return f"<Role {self.name}>"
    
    def save(self):
        """Save role to database"""
        db.session.add(self)
        db.session.commit()


class Permission(db.Model):
    """
    Permission Model
    
    Represents a specific permission in the system.
    
    Naming Convention: resource.action.scope
    - resource: The resource being accessed (e.g., 'student', 'attendance')
    - action: The action being performed (e.g., 'create', 'read', 'update', 'delete', 'manage')
    - scope: Optional scope (e.g., 'self', 'class', 'school', 'all')
    
    Examples:
    - student.create
    - student.read.self
    - student.read.class
    - attendance.mark
    - attendance.manage
    """
    __tablename__ = "permissions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<Permission {self.name}>"
    
    def save(self):
        """Save permission to database"""
        db.session.add(self)
        db.session.commit()


class RolePermission(TenantBaseModel):
    """
    RolePermission Junction Table
    
    Maps permissions to roles (many-to-many relationship). Scoped by tenant.
    """
    __tablename__ = "role_permissions"

    __table_args__ = (
        db.UniqueConstraint(
            "role_id", "permission_id", "tenant_id",
            name="uq_role_permission_tenant",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    role_id = db.Column(
        db.String(36),
        db.ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    permission_id = db.Column(
        db.String(36),
        db.ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<RolePermission role_id={self.role_id} permission_id={self.permission_id}>"
    
    def save(self):
        """Save role-permission mapping to database"""
        db.session.add(self)
        db.session.commit()


class UserRole(TenantBaseModel):
    """
    UserRole Junction Table
    
    Maps roles to users (many-to-many relationship).
    Users can have multiple roles. Scoped by tenant.
    """
    __tablename__ = "user_roles"

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "role_id", "tenant_id",
            name="uq_user_role_tenant",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    role_id = db.Column(
        db.String(36),
        db.ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<UserRole user_id={self.user_id} role_id={self.role_id}>"
    
    def save(self):
        """Save user-role mapping to database"""
        db.session.add(self)
        db.session.commit()


class StaffAuthority(TenantBaseModel):
    """An Authority Profile held by an employed person (ADR-013).

    Authority belongs to the employment, not to the login. That is what makes
    revocation a consequence rather than a chore: when the employment ends the
    authority ends with it, because it was never anything but an aspect of that
    employment.

    ``Role`` is the Authority Profile — see ADR-013 for the vocabulary mapping.
    """

    __tablename__ = "staff_authorities"
    __table_args__ = (
        db.UniqueConstraint(
            "staff_id", "role_id", name="uq_staff_authorities_staff_role"
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    staff_id = db.Column(
        db.String(36),
        db.ForeignKey("staff.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id = db.Column(
        db.String(36),
        db.ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    granted_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    granted_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<StaffAuthority staff={self.staff_id} role={self.role_id}>"


class AuthorityDelegation(TenantBaseModel):
    """Authority lent from one employment to another for a period (ADR-006).

    Schools do this constantly: a principal goes on leave and the vice
    principal acts in their place until they return. It is deliberately
    temporary — a delegation without an end date is not a delegation, it is a
    grant, and should be made as one.

    Expiry needs no job to run. Nothing reads a delegation outside its dates,
    so it stops applying the day it ends.
    """

    __tablename__ = "authority_delegations"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    role_id = db.Column(
        db.String(36),
        db.ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = db.relationship("Role", foreign_keys=[role_id])

    # Whose authority is being lent.
    from_staff_id = db.Column(
        db.String(36),
        db.ForeignKey("staff.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Who is acting in their place.
    to_staff_id = db.Column(
        db.String(36),
        db.ForeignKey("staff.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text, nullable=True)

    # Set when the school ends a delegation before its date.
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        db.CheckConstraint(
            "effective_to >= effective_from", name="ck_authority_delegations_dates"
        ),
        db.CheckConstraint(
            "from_staff_id <> to_staff_id", name="ck_authority_delegations_distinct"
        ),
    )

    def __repr__(self) -> str:
        return f"<AuthorityDelegation {self.from_staff_id} -> {self.to_staff_id}>"
