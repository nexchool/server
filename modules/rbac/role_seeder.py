"""
RBAC Role Seeder

Single source of truth for default role definitions and the idempotent
seed_roles_for_tenant() helper.

Kept as a standalone leaf module (no imports from teachers / students / platform)
so it can be safely imported from any service without circular-import issues.
"""

from typing import Dict

from backend.core.database import db
from backend.modules.rbac.models import Role, Permission, RolePermission


# ---------------------------------------------------------------------------
# Default role definitions
# ---------------------------------------------------------------------------

DEFAULT_ROLES: Dict[str, dict] = {
    "Admin": {
        "description": "System administrator with full access",
        "permissions": [
            "user.manage", "role.manage", "permission.manage",
            "student.manage", "teacher.manage", "attendance.manage",
            "grades.manage", "course.manage", "class.manage",
            "subject.manage", "timetable.manage",
            "finance.read", "finance.manage", "finance.collect", "finance.refund",
            "fees.invoice.create", "fees.invoice.read", "fees.invoice.send_reminder",
            "fees.payment.record", "fees.receipt.download",
            "teacher.leave.manage",
            "holiday.manage",
        ],
    },
    "Teacher": {
        "description": "School teacher with class management access",
        "permissions": [
            "student.read.class", "attendance.mark", "attendance.read.class",
            "grades.create", "grades.update", "grades.read.class",
            "course.read", "class.read", "subject.read", "timetable.read",
            "teacher.leave.apply",
            "holiday.read",
        ],
    },
    "Student": {
        "description": "Student with limited access to own data",
        "permissions": [
            "student.read.self", "attendance.read.self", "grades.read.self",
            "course.read", "timetable.read",
            "holiday.read",
        ],
    },
    "Parent": {
        "description": "Parent with access to their children's data",
        "permissions": [
            "student.read.self", "attendance.read.self", "grades.read.self",
            "course.read", "timetable.read",
            "holiday.read",
        ],
    },
}


# ---------------------------------------------------------------------------
# Seeding helper
# ---------------------------------------------------------------------------

def seed_roles_for_tenant(tenant_id: str) -> Dict[str, str]:
    """
    Create default roles (Admin, Teacher, Student, Parent) and assign their
    permissions for the given tenant.  Idempotent — safe to call multiple times.

    - If a role already exists, any *missing* permissions are backfilled.
    - If a global Permission row does not exist yet, it is silently skipped
      (run seed_rbac first to create global permissions).

    Returns:
        dict mapping role_name -> role_id for the tenant.
    """
    role_ids: Dict[str, str] = {}

    for role_name, role_data in DEFAULT_ROLES.items():
        existing = Role.query.filter_by(name=role_name, tenant_id=tenant_id).first()

        if existing:
            role = existing
            role_ids[role_name] = role.id
            # Backfill any missing permissions
            existing_perm_ids = {p.id for p in role.permissions}
            for perm_name in role_data["permissions"]:
                perm = Permission.query.filter_by(name=perm_name).first()
                if not perm or perm.id in existing_perm_ids:
                    continue
                db.session.add(
                    RolePermission(
                        tenant_id=tenant_id,
                        role_id=role.id,
                        permission_id=perm.id,
                    )
                )
        else:
            role = Role(
                tenant_id=tenant_id,
                name=role_name,
                description=role_data["description"],
            )
            db.session.add(role)
            db.session.flush()
            role_ids[role_name] = role.id
            for perm_name in role_data["permissions"]:
                perm = Permission.query.filter_by(name=perm_name).first()
                if not perm:
                    continue
                db.session.add(
                    RolePermission(
                        tenant_id=tenant_id,
                        role_id=role.id,
                        permission_id=perm.id,
                    )
                )

    db.session.commit()
    return role_ids
