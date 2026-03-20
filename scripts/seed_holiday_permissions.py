"""
Seed Holiday Permissions — Backfill Script

Run this ONCE on an existing database to add the new holiday.* permissions
to all tenants' default roles without touching any other data.

What it does:
  1. Creates the 5 holiday Permission rows globally (idempotent).
  2. For every tenant, finds their default roles (Admin / Teacher / Student / Parent)
     and grants the correct holiday permissions to each one.
  3. Reports a per-tenant summary so you can verify.

Role → Permissions granted:
  Admin   → holiday.manage  (implies create/read/update/delete)
  Teacher → holiday.read
  Student → holiday.read
  Parent  → holiday.read

Usage (from the app/ directory):
    python -m backend.scripts.seed_holiday_permissions

Or from a Python / Flask shell:
    from backend.scripts.seed_holiday_permissions import run
    run()
"""

from backend.app import create_app
from backend.core.database import db
from backend.core.models import Tenant
from backend.modules.rbac.models import Role, Permission, RolePermission


# ---------------------------------------------------------------------------
# Permission definitions to create / backfill
# ---------------------------------------------------------------------------

HOLIDAY_PERMISSIONS = [
    ('holiday.read',   'View holidays and weekly-off calendar'),
    ('holiday.create', 'Create holidays'),
    ('holiday.update', 'Update holiday details'),
    ('holiday.delete', 'Delete holidays'),
    ('holiday.manage', 'Full holiday management access'),
]

# Maps role name → list of holiday permissions to assign
ROLE_PERMISSION_MAP: dict[str, list[str]] = {
    'Admin':   ['holiday.manage'],
    'Teacher': ['holiday.read'],
    'Student': ['holiday.read'],
    'Parent':  ['holiday.read'],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_permissions() -> dict[str, Permission]:
    """
    Create missing holiday Permission rows (global, not tenant-scoped).
    Returns a dict of  name → Permission  for all holiday permissions.
    """
    perm_map: dict[str, Permission] = {}
    created = 0

    for name, description in HOLIDAY_PERMISSIONS:
        perm = Permission.query.filter_by(name=name).first()
        if not perm:
            perm = Permission(name=name, description=description)
            db.session.add(perm)
            db.session.flush()
            created += 1
            print(f"  [+] Permission created : {name}")
        else:
            print(f"  [=] Permission exists  : {name}")
        perm_map[name] = perm

    if created:
        db.session.commit()
    return perm_map


def _backfill_tenant(tenant: Tenant, perm_map: dict[str, Permission]) -> dict:
    """
    Assign holiday permissions to each default role for one tenant.
    Returns stats dict.
    """
    stats = {'assigned': 0, 'already_had': 0, 'role_missing': 0}

    for role_name, perm_names in ROLE_PERMISSION_MAP.items():
        role = Role.query.filter_by(name=role_name, tenant_id=tenant.id).first()
        if not role:
            print(f"    [!] Role '{role_name}' not found — skipped")
            stats['role_missing'] += 1
            continue

        for perm_name in perm_names:
            perm = perm_map.get(perm_name)
            if not perm:
                continue

            already = RolePermission.query.filter_by(
                role_id=role.id, permission_id=perm.id, tenant_id=tenant.id
            ).first()

            if already:
                stats['already_had'] += 1
            else:
                db.session.add(RolePermission(
                    role_id=role.id,
                    permission_id=perm.id,
                    tenant_id=tenant.id,
                ))
                stats['assigned'] += 1
                print(f"    [+] {role_name:<10} ← {perm_name}")

    db.session.commit()
    return stats


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run():
    print("\n" + "=" * 60)
    print("  Holiday Permission Backfill")
    print("=" * 60)

    # Step 1 — ensure global permission rows exist
    print("\n[Step 1] Ensuring holiday.* permissions exist globally…")
    perm_map = _ensure_permissions()

    # Step 2 — iterate every tenant
    tenants = Tenant.query.all()
    print(f"\n[Step 2] Backfilling {len(tenants)} active tenant(s)…")

    total_assigned = 0
    total_already  = 0
    total_missing  = 0

    for tenant in tenants:
        print(f"\n  Tenant: {tenant.name} ({tenant.id})")
        stats = _backfill_tenant(tenant, perm_map)
        total_assigned += stats['assigned']
        total_already  += stats['already_had']
        total_missing  += stats['role_missing']

    print("\n" + "=" * 60)
    print("  Done!")
    print("=" * 60)
    print(f"  Permissions newly assigned : {total_assigned}")
    print(f"  Already had permission     : {total_already}")
    print(f"  Roles not found (skipped)  : {total_missing}")
    print("=" * 60 + "\n")


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        run()
