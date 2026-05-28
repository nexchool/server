"""remove school_setup.read / school_setup.manage grants from all roles

School-setup is now restricted to the platform super-admin (god-mode), so the
tenant-scoped Admin role must no longer hold these permissions. seed_roles_for_tenant
only backfills missing perms (never removes), so existing tenants need this data
migration to drop the stale grants. The permission rows themselves are kept — the
setup endpoints still reference the strings and god-mode bypasses the grant check.

Revision ID: 064_remove_school_setup_from_admin
Revises: 063_subadmin_user_flags
Create Date: 2026-05-29
"""

from alembic import op


revision = "064_remove_school_setup_from_admin"
down_revision = "063_subadmin_user_flags"
branch_labels = None
depends_on = None


def upgrade():
    # Drop every role_permissions grant pointing at school_setup.* across all
    # tenants/roles. Permission definitions in `permissions` are left intact.
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions
            WHERE name IN ('school_setup.read', 'school_setup.manage')
        )
        """
    )


def downgrade():
    # Best-effort restore: re-grant school_setup.read / school_setup.manage to
    # every role named 'Admin', per tenant. INSERT...SELECT skips pairs that
    # already exist so the migration is safe to re-run.
    op.execute(
        """
        INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at)
        SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, now()
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.name = 'Admin'
          AND p.name IN ('school_setup.read', 'school_setup.manage')
          AND NOT EXISTS (
              SELECT 1 FROM role_permissions rp
              WHERE rp.role_id = r.id
                AND rp.permission_id = p.id
                AND rp.tenant_id = r.tenant_id
          )
        """
    )
