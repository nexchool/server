"""
RBAC Models

Database models for roles, permissions, and their relationships.
"""

from backend.core.database import db
from backend.core.models import TenantBaseModel
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
