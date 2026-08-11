"""Seeding a tenant's default roles.

The role definitions live in `catalog.py`; this module only applies them. That
split is the point: `scripts/seed_rbac.py` used to carry its own copy of the four
roles and this file carried another, kept in step by a comment. Whichever seeder
had made a tenant decided what its roles held.

Kept as a leaf module (no imports from teachers / students / platform) so it can
be imported from any service without a circular import.
"""

from typing import Dict

from core.database import db
from modules.rbac.models import Role, Permission, RolePermission

# Re-exported: `platform/services.py` and the tests import DEFAULT_ROLES from
# here, and the definition moving is not a reason to make them all move too.
from modules.rbac.catalog import DEFAULT_ROLES  # noqa: F401


def seed_roles_for_tenant(
    tenant_id: str, *, reconcile: bool = False
) -> Dict[str, str]:
    """
    Create default roles (Admin, Teacher, Student, Parent) and assign their
    permissions for the given tenant.  Idempotent — safe to call multiple times.

    - If a role already exists, any *missing* permissions are backfilled.
    - If a global Permission row does not exist yet, it is silently skipped
      (run seed_rbac first to create global permissions).

    `reconcile` also takes away what the catalogue no longer grants. It is off
    here because this runs on every login, and an operator who granted a key by
    hand should not have it removed under them by signing in. It is on for the
    deliberate reseed (`scripts/reseed_rbac.py`), which is where a school is
    being brought back in line with the catalogue on purpose.

    Without it, removing a key from the catalogue changes nothing anywhere: the
    seeder only adds, so every tenant keeps what it was once given. That is why
    taking `school_setup.read` off the Teacher role needed migration 103 rather
    than an edit.

    Only the four default roles are touched. A role a school created itself is
    not in the catalogue and is left alone.

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

            if reconcile:
                _revoke_beyond_catalogue(tenant_id, role, role_data["permissions"])
        else:
            role = Role(
                tenant_id=tenant_id,
                name=role_name,
                description=role_data["description"],
                # A student's access follows from being a student rather than
                # being granted to their account (ADR-013).
                implied_by_relationship=role_data.get("implied_by_relationship"),
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


def _revoke_beyond_catalogue(tenant_id: str, role, granted: list) -> int:
    """Take away what this role holds and the catalogue does not grant.

    Compared by permission *name*, not id: the catalogue is a list of names, and
    matching on anything else would silently keep a grant whose row happens to
    differ.

    Deliberately literal — a role holding `student.manage` and not
    `student.update` is correct, because manage implies it, so nothing here
    expands implications. The catalogue lists exactly what each role is granted,
    and this removes exactly what it does not.
    """
    keep = set(granted)
    doomed = [
        rp
        for rp, perm in (
            db.session.query(RolePermission, Permission)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .filter(
                RolePermission.role_id == role.id,
                RolePermission.tenant_id == tenant_id,
            )
            .all()
        )
        if perm.name not in keep
    ]
    for row in doomed:
        db.session.delete(row)
    return len(doomed)
