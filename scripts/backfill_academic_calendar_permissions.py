"""
Backfill Academic Calendar Permissions

The academic calendar shipped its permissions in `scripts/seed_rbac.py` only.
That path grants through `assign_permission_to_role_by_name`, which resolves the
role with `Role.query.filter_by(name=...).first()` — no tenant filter. Roles are
per-tenant, so exactly one arbitrary tenant received the grants and every other
tenant was silently skipped. The calendar menu is gated on
`academic_calendar.read` / `.manage`, so for those tenants it is invisible to
everyone, including Admin.

This backfills every tenant from DEFAULT_ROLES, which now carries the calendar
permissions.

Run once against any tenant set up before this fix. Idempotent — additive only,
never removes a grant.

Usage (from the app/ directory):
    python -m scripts.backfill_academic_calendar_permissions
"""

from app import create_app
from core.models import Tenant, TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED
from modules.rbac.services import create_permission
from modules.rbac.role_seeder import seed_roles_for_tenant

# Mirrors the academic_calendar block in scripts/seed_rbac.py. `manage` is a
# superset of the granular actions; those are handed out per sub-admin and are
# deliberately not part of any default role.
NEW_PERMISSIONS = [
    ("academic_calendar.read", "View the academic calendar (events, exams, summary)"),
    ("academic_calendar.manage", "Configure and publish the academic calendar"),
]


def ensure_permissions() -> int:
    """Create the global Permission rows if they don't exist yet."""
    from modules.rbac.models import Permission

    created = 0
    for name, description in NEW_PERMISSIONS:
        if Permission.query.filter_by(name=name).first():
            print(f"  ✓ already exists: {name}")
            continue
        result = create_permission(name, description)
        if result.get("success"):
            print(f"  + created: {name}")
            created += 1
        else:
            print(f"  ✗ failed:  {name} — {result.get('error')}")
    return created


def backfill():
    app = create_app()
    with app.app_context():
        print("\n" + "=" * 60)
        print("Backfill Academic Calendar Permissions")
        print("=" * 60)

        print("\nStep 1 — global permissions")
        ensure_permissions()

        tenants = Tenant.query.filter(
            Tenant.status.in_([TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED])
        ).all()

        if not tenants:
            print("\nNo tenants found.")
            return

        print(f"\nStep 2 — backfilling {len(tenants)} tenant(s)\n")
        for tenant in tenants:
            seed_roles_for_tenant(tenant.id)
            print(f"  ✓ {tenant.subdomain} ({tenant.name})")

        print("\n" + "=" * 60)
        print("Done.")
        print("  Admin role   → academic_calendar.read, academic_calendar.manage")
        print("  Teacher role → academic_calendar.read")
        print("\nUsers must sign out and back in — permissions are resolved into")
        print("the session at login and cached client-side.")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    backfill()
