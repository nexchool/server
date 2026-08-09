"""
RBAC Seed Script

Seeds the database with default roles and permissions for School ERP.

Usage:
    python -m scripts.seed_rbac
    
Or from Flask shell:
    >>> from scripts.seed_rbac import seed_rbac
    >>> seed_rbac()
"""

from app import create_app
from core.database import db
from core.models import Tenant, TENANT_STATUS_ACTIVE
from modules.rbac.models import RolePermission
from modules.rbac.role_seeder import seed_roles_for_tenant
from modules.rbac.services import create_permission


def _grant_count(tenant_id: str) -> int:
    return RolePermission.query.filter_by(tenant_id=tenant_id).count()


# ==================== PERMISSIONS DEFINITION ====================

# The definitions live in `modules/rbac/catalog.py` — one copy, imported by
# this script and by `seed_roles_for_tenant`. They used to be two, kept in step
# by a comment, and a tenant's authority depended on which one had made it.
#
# `ROLES` keeps the shape this script has always used. `catalog.DEFAULT_ROLES`
# additionally carries `implied_by_relationship`, which only the tenant seeder
# needs.
from modules.rbac.catalog import DEFAULT_ROLES, PERMISSIONS  # noqa: F401

ROLES = {
    name: {"description": spec["description"], "permissions": spec["permissions"]}
    for name, spec in DEFAULT_ROLES.items()
}


def seed_rbac():
    """
    Seed the database with default roles and permissions.
    
    This function:
    1. Creates all permissions
    2. Creates all roles
    3. Assigns permissions to roles
    
    Returns:
        Dict with success status and statistics
    """
    stats = {
        'permissions_created': 0,
        'permissions_existed': 0,
        'roles_created': 0,
        'roles_existed': 0,
        'assignments_created': 0,
        'assignments_failed': 0,
    }
    
    print("\n" + "="*60)
    print("🌱 Seeding RBAC System")
    print("="*60 + "\n")
    
    # 1. Create permissions
    print("📋 Creating Permissions...")
    for permission_name, description in PERMISSIONS:
        result = create_permission(permission_name, description)
        if result['success']:
            print(f"  ✓ Created: {permission_name}")
            stats['permissions_created'] += 1
        else:
            if 'already exists' in result['error']:
                stats['permissions_existed'] += 1
            else:
                print(f"  ✗ Failed: {permission_name} - {result['error']}")
    
    print(f"\n  Summary: {stats['permissions_created']} created, {stats['permissions_existed']} already existed\n")
    
    # 2 & 3. Roles, and their permissions, per tenant.
    #
    # This used to call `create_role` and `assign_permission_to_role_by_name`,
    # which both resolve the tenant off the request — so from a CLI there is
    # none, and every role failed with "Tenant context is required" while the
    # script exited 0. Roles have therefore only ever come from
    # `seed_roles_for_tenant`, and startup.sh logged four failures on every
    # deploy. That silent half-failure is why each module ended up writing its
    # own backfill script to do the per-tenant grants this was meant to do.
    print("👥 Seeding roles per tenant...")
    for tenant in Tenant.query.filter_by(status=TENANT_STATUS_ACTIVE).all():
        before = _grant_count(tenant.id)
        seed_roles_for_tenant(tenant.id)
        added = _grant_count(tenant.id) - before
        stats['roles_created'] += len(ROLES)
        stats['assignments_created'] += added
        print(f"  ✓ {tenant.subdomain or tenant.id}: {added} grant(s) added")

    print(f"\n  Summary: {stats['assignments_created']} grant(s) added\n")

    print("\n" + "="*60)
    print("📊 Seeding Complete!")
    print("="*60)
    print(f"Permissions: {stats['permissions_created']} created, {stats['permissions_existed']} existed")
    print(f"Grants added: {stats['assignments_created']}")
    print("To take a grant away, see: python -m scripts.reseed_rbac --dry-run")
    print("="*60 + "\n")
    
    return stats


if __name__ == '__main__':
    """Run seeding when script is executed directly"""
    app = create_app()
    
    with app.app_context():
        seed_rbac()
