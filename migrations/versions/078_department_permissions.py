"""grant department.read / department.manage to existing tenants

The departments module declares its permissions in `scripts/seed_rbac.py`
(global list + role grants) and `modules/rbac/role_seeder.py` (DEFAULT_ROLES).
Neither reaches an existing tenant on deploy:

- `seed_rbac.py` grants through `assign_permission_to_role_by_name`, which
  resolves the role with `Role.query.filter_by(name=...).first()` — no tenant
  filter. Roles are per-tenant, so exactly one arbitrary tenant receives the
  grant and every other tenant is silently skipped. (Same defect that required
  scripts/backfill_academic_calendar_permissions.py.)
- `seed_roles_for_tenant` is tenant-scoped and does backfill missing grants,
  but only runs when that tenant next logs in.

The department routes are gated on these permissions, so until a tenant is
granted them the entire module 403s for everyone — including the department
pickers embedded in the teacher and class forms.

This data migration closes that: it creates the two permission rows if absent,
then grants them per tenant across every existing Admin and Teacher role,
mirroring DEFAULT_ROLES exactly. `INSERT ... SELECT` with `NOT EXISTS` makes it
idempotent and safe to re-run. Follows the pattern of
`064_remove_school_setup_from_admin`.

Revision ID: 078_department_permissions
Revises: 077_department_references
Create Date: 2026-07-29
"""

from alembic import op

revision = "078_department_permissions"
down_revision = "077_department_references"
branch_labels = None
depends_on = None


# (permission name, description, role that receives it) — mirrors DEFAULT_ROLES
# in modules/rbac/role_seeder.py and the ROLES block in scripts/seed_rbac.py.
GRANTS = (
    ("department.manage", "Full department management access", "Admin"),
    ("department.read", "View department information", "Teacher"),
)


def upgrade():
    # 1. Global permission rows. `permissions` is not tenant-scoped; the
    #    NOT EXISTS guard keeps this idempotent whether or not seed_rbac.py
    #    has already been run against this database.
    for name, description, _role in GRANTS:
        op.execute(
            f"""
            INSERT INTO permissions (id, name, description, created_at)
            SELECT gen_random_uuid()::text, '{name}', '{description}', now()
            WHERE NOT EXISTS (
                SELECT 1 FROM permissions WHERE name = '{name}'
            )
            """
        )

    # 2. Per-tenant grants. Joining roles to permissions by name gives every
    #    tenant's copy of the role, which is exactly what the by-name helper in
    #    seed_rbac.py fails to do.
    for name, _description, role in GRANTS:
        op.execute(
            f"""
            INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at)
            SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, now()
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.name = '{role}'
              AND p.name = '{name}'
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp
                  WHERE rp.role_id = r.id
                    AND rp.permission_id = p.id
                    AND rp.tenant_id = r.tenant_id
              )
            """
        )


def downgrade():
    # Remove the grants, scoped to the roles this migration targeted so any
    # other role that legitimately holds them is untouched. The `permissions`
    # rows are left intact: the routes still reference the strings, and
    # dropping them would cascade into grants this migration never created.
    for name, _description, role in GRANTS:
        op.execute(
            f"""
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions WHERE name = '{name}'
            )
            AND role_id IN (SELECT id FROM roles WHERE name = '{role}')
            """
        )
