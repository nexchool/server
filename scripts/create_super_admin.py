"""
Create Super Admin User (Platform Admin)

Creates the first user with is_platform_admin=True in the default tenant.
Use this when the DB is empty and you need one user to log into the Super Admin panel.

- Ensures default tenant exists (from migrations)
- Ensures global permissions exist (creates if missing)
- Seeds roles for the default tenant (Admin, Teacher, Student, Parent)
- Creates one user with is_platform_admin=True and assigns Admin role

Usage (from project root, e.g. app/ or school-ERP/):
    python -m backend.scripts.create_super_admin

Or with env vars (non-interactive):
    SUPER_ADMIN_EMAIL=admin@example.com SUPER_ADMIN_PASSWORD=secret python -m backend.scripts.create_super_admin
"""

import getpass
import os

from backend.app import create_app
from backend.core.database import db
from backend.core.models import Tenant
from backend.modules.auth.models import User
from backend.modules.rbac.models import Role, UserRole
from backend.modules.rbac.services import create_permission
from backend.scripts.seed_rbac import PERMISSIONS


def ensure_permissions():
    """Create global permissions if they don't exist."""
    from backend.modules.rbac.models import Permission
    created = 0
    for name, description in PERMISSIONS:
        if Permission.query.filter_by(name=name).first():
            continue
        result = create_permission(name, description)
        if result.get("success"):
            created += 1
    return created


def create_super_admin_user(email: str, password: str, name: str = None) -> bool:
    """
    Create a platform admin user in the default tenant.
    Seeds roles for default tenant if needed, then creates user and assigns Admin role.
    """
    app = create_app()
    with app.app_context():
        # 1. Default tenant must exist (from migration 002)
        default_tenant = Tenant.query.filter_by(subdomain="default").first()
        if not default_tenant:
            print("✗ No default tenant found. Run migrations first:")
            print("  flask db upgrade")
            return False

        tenant_id = default_tenant.id

        # 2. Ensure global permissions exist (needed for roles)
        from backend.modules.rbac.role_seeder import seed_roles_for_tenant
        n = ensure_permissions()
        if n:
            print(f"✓ Created {n} global permission(s)")

        # 3. Ensure default tenant has roles (Admin, Teacher, etc.)
        seed_roles_for_tenant(tenant_id)
        print("✓ Default tenant roles ready")

        # 4. Check user doesn't already exist in this tenant
        existing = User.query.filter_by(email=email, tenant_id=tenant_id).first()
        if existing:
            if existing.is_platform_admin:
                print(f"✓ User {email} is already a super admin.")
            else:
                existing.is_platform_admin = True
                db.session.commit()
                print(f"✓ Updated existing user {email} to super admin.")
            return True

        # 5. Create user
        user = User(
            tenant_id=tenant_id,
            email=email,
            name=name or email.split("@")[0],
        )
        user.set_password(password)
        user.email_verified = True
        user.is_platform_admin = True
        db.session.add(user)
        db.session.flush()

        # 6. Assign Admin role (for this tenant)
        admin_role = Role.query.filter_by(name="Admin", tenant_id=tenant_id).first()
        if not admin_role:
            print("✗ Admin role not found for default tenant.")
            db.session.rollback()
            return False

        user_role = UserRole(tenant_id=tenant_id, user_id=user.id, role_id=admin_role.id)
        db.session.add(user_role)
        db.session.commit()

        print(f"✓ Super admin user created: {email}")
        print(f"  Tenant: {default_tenant.name} (subdomain: default)")
        print(f"  is_platform_admin: True")
        return True


def main():
    print("\n" + "=" * 60)
    print("🔐 Create Super Admin User (Platform Admin)")
    print("=" * 60 + "\n")

    email = os.environ.get("SUPER_ADMIN_EMAIL") or input("Email: ").strip()
    if not email:
        print("✗ Email is required")
        return

    password = os.environ.get("SUPER_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if not password:
        print("✗ Password is required")
        return

    if not os.environ.get("SUPER_ADMIN_PASSWORD"):
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("✗ Passwords do not match")
            return

    name = os.environ.get("SUPER_ADMIN_NAME") or input("Name (optional, default=email prefix): ").strip() or None

    success = create_super_admin_user(email, password, name)
    if success:
        print("\n" + "=" * 60)
        print("✅ Done. You can now log in with this user.")
        print("   For Super Admin panel: use the same login; platform APIs require is_platform_admin.")
        print("=" * 60 + "\n")
    else:
        print("\n✗ Failed to create super admin.\n")


if __name__ == "__main__":
    main()
