"""Bring every tenant's roles back in line with the catalogue.

This replaces seven one-off scripts — `backfill_academic_calendar_permissions`,
`backfill_admin_finance_permissions`, `backfill_teacher_leave_permissions`,
`backfill_timetable_subject_permissions`, `fix_teacher_permissions`,
`grant_hostel_permissions`, `seed_holiday_permissions` — each written when a
module added its keys, each doing the same two things: create the Permission
rows the catalogue names, then reseed the roles. Two of them were already
exactly this, generic, under module-specific names.

That pattern is what made a tenant's authority depend on which backfills had
been run against it, which is how the Teacher role ended up holding
`school_setup.read` in some tenants and not others.

    python -m scripts.reseed_rbac                  # add what is missing
    python -m scripts.reseed_rbac --reconcile      # also take away what the
                                                   # catalogue no longer grants
    python -m scripts.reseed_rbac --tenant <id>    # one tenant
    python -m scripts.reseed_rbac --dry-run        # report, change nothing

`--reconcile` is the half that did not exist before: the seeder only ever added,
so removing a key from the catalogue changed nothing anywhere and revoking one
took a hand-written migration (103). Read the dry run before using it — it
removes every grant on a default role that the catalogue does not name,
including one an operator added by hand through the API.
"""

from __future__ import annotations

import argparse
import sys

from app import create_app
from core.database import db
from core.models import Tenant, TENANT_STATUS_ACTIVE
from modules.rbac.catalog import DEFAULT_ROLES, PERMISSIONS
from modules.rbac.models import Permission, Role, RolePermission
from modules.rbac.role_seeder import seed_roles_for_tenant


def ensure_permission_rows() -> int:
    """Create the Permission rows the catalogue names. Global, not per tenant."""
    created = 0
    for name, description in PERMISSIONS:
        if Permission.query.filter_by(name=name).first():
            continue
        db.session.add(Permission(name=name, description=description))
        created += 1
    if created:
        db.session.commit()
    return created


def _surplus(tenant_id: str) -> dict:
    """Per default role, the grants the catalogue does not name."""
    out = {}
    for role_name, spec in DEFAULT_ROLES.items():
        role = Role.query.filter_by(name=role_name, tenant_id=tenant_id).first()
        if role is None:
            continue
        keep = set(spec["permissions"])
        held = (
            db.session.query(Permission.name)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .filter(
                RolePermission.role_id == role.id,
                RolePermission.tenant_id == tenant_id,
            )
            .all()
        )
        extra = sorted({name for (name,) in held} - keep)
        if extra:
            out[role_name] = extra
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", help="Reseed only this tenant id.")
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Also revoke grants the catalogue no longer names.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without changing it.",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        tenants = (
            Tenant.query.filter_by(id=args.tenant).all()
            if args.tenant
            else Tenant.query.filter_by(status=TENANT_STATUS_ACTIVE).all()
        )
        if not tenants:
            print("No matching tenants.")
            return 1

        if args.dry_run:
            print(f"Dry run over {len(tenants)} tenant(s).\n")
            missing = [n for n, _ in PERMISSIONS if not Permission.query.filter_by(name=n).first()]
            print(f"Permission rows to create: {len(missing)}")
            for name in missing:
                print(f"    + {name}")
            for tenant in tenants:
                extra = _surplus(tenant.id)
                label = "would be revoked with --reconcile" if extra else "in line"
                print(f"\n  {tenant.subdomain or tenant.id}: {label}")
                for role_name, keys in extra.items():
                    for key in keys:
                        print(f"    - {role_name}: {key}")
            return 0

        created = ensure_permission_rows()
        print(f"Permission rows created: {created}")

        for tenant in tenants:
            seed_roles_for_tenant(tenant.id, reconcile=args.reconcile)
            print(f"  seeded {tenant.subdomain or tenant.id}")

        print(
            f"\nDone: {len(tenants)} tenant(s)"
            f"{', reconciled' if args.reconcile else ', additions only'}."
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
