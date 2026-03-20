"""
Backfill Admin Role with Finance Permissions

Adds finance.read, finance.manage, finance.collect, finance.refund to existing
Admin roles across all tenants. Idempotent - safe to run multiple times.

Usage (from project root, e.g. app/ or school-ERP/):
    python -m backend.scripts.backfill_admin_finance_permissions
"""

from backend.app import create_app
from backend.core.models import Tenant, TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED
from backend.scripts.seed_rbac import PERMISSIONS
from backend.modules.rbac.services import create_permission
from backend.modules.rbac.role_seeder import seed_roles_for_tenant


def ensure_permissions():
    """Create global permissions if they don't exist."""
    created = 0
    for name, description in PERMISSIONS:
        from backend.modules.rbac.models import Permission
        if Permission.query.filter_by(name=name).first():
            continue
        result = create_permission(name, description)
        if result.get("success"):
            created += 1
    return created


def backfill_admin_finance_permissions():
    """
    Ensure finance permissions exist, then run seed_roles_for_tenant for each
    tenant. seed_roles_for_tenant now backfills missing permissions on existing roles.
    """
    app = create_app()
    with app.app_context():
        # 1. Ensure global permissions exist
        n = ensure_permissions()
        if n:
            print(f"✓ Created {n} global permission(s)")

        # 2. Get all tenants (active + suspended; exclude deleted)
        tenants = Tenant.query.filter(
            Tenant.status.in_([TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED])
        ).all()

        if not tenants:
            print("No tenants found.")
            return

        print(f"\nBackfilling Admin finance permissions for {len(tenants)} tenant(s)...\n")

        for tenant in tenants:
            seed_roles_for_tenant(tenant.id)
            print(f"  ✓ {tenant.subdomain} ({tenant.name})")

        print("\n✅ Done. All Admin roles now have finance permissions.")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🔧 Backfill Admin Finance Permissions")
    print("=" * 60)
    backfill_admin_finance_permissions()
    print("=" * 60 + "\n")
