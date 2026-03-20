"""
Backfill Teacher Leave Permissions

Adds the two new permissions that enable the teacher-leave feature:
  - teacher.leave.apply  → assigned to the Teacher role
  - teacher.leave.manage → assigned to the Admin role

Run this once against any tenant that was set up before this fix.
Idempotent — safe to run multiple times.

Usage (from the app/ directory):
    python -m backend.scripts.backfill_teacher_leave_permissions
"""

from backend.app import create_app
from backend.core.models import Tenant, TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED
from backend.modules.rbac.services import create_permission
from backend.modules.rbac.role_seeder import seed_roles_for_tenant

NEW_PERMISSIONS = [
    ("teacher.leave.apply",  "Apply for leave as a teacher"),
    ("teacher.leave.manage", "View and manage all teacher leave requests"),
]


def ensure_permissions() -> int:
    """Create the two new global Permission rows if they don't exist yet."""
    from backend.modules.rbac.models import Permission
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
        print("Backfill Teacher Leave Permissions")
        print("=" * 60)

        # Step 1 — ensure global permission rows exist
        print("\nStep 1 — global permissions")
        ensure_permissions()

        # Step 2 — backfill roles for every active/suspended tenant
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
        print("  Teacher role → teacher.leave.apply")
        print("  Admin role   → teacher.leave.manage")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    backfill()
