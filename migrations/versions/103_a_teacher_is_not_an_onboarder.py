"""A teacher stops holding the school's onboarding permission.

Standing a school up is work the platform operator does from the panel, before
the school admin takes over. `school_setup.read` says "may see how far that
onboarding has got" — an answer a teacher has no business asking for.

It was granted to the Teacher role for an unrelated reason. Reading the mediums
and the subject contexts required `school_setup.read`, `school_setup.manage` or
`class_subject.manage`; a teacher holds `class_subject.read` and no manage key,
so the only way to let them see those lists was to hand them the setup key. The
routes now accept `class_subject.read` — the authority a teacher actually holds
— so the grant has nothing left to buy.

This has to be a migration because `seed_roles_for_tenant` only ever adds: it
backfills missing permissions and never revokes one, so removing the key from
the role definition leaves every existing tenant exactly as it was.

Revision ID: 103_a_teacher_is_not_an_onboarder
Revises: 102_two_sections_become_one
"""

import sqlalchemy as sa
from alembic import op

revision = "103_a_teacher_is_not_an_onboarder"
down_revision = "102_two_sections_become_one"
branch_labels = None
depends_on = None


# Which rows were revoked, so the downgrade can put back exactly those.
#
# Not every tenant holds the grant — a tenant seeded before the key existed, or
# one whose Teacher role was edited by hand, may never have had it. A downgrade
# that re-grants to every Teacher role would hand the permission to tenants that
# never had it, which is the same over-grant this migration exists to remove.
# (Measured on a local database: 4 tenants held it, 5 Teacher roles existed.)
_JOURNAL = "migration_103_revoked_teacher_setup_read"


def upgrade():
    bind = op.get_bind()

    op.create_table(
        _JOURNAL,
        sa.Column("role_id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
    )
    bind.execute(
        sa.text(
            f"""
            INSERT INTO {_JOURNAL} (role_id, tenant_id)
            SELECT r.id, r.tenant_id
            FROM role_permissions rp
            JOIN roles r ON r.id = rp.role_id
            JOIN permissions p ON p.id = rp.permission_id
            WHERE r.name = 'Teacher'
              AND p.name = 'school_setup.read'
            """
        )
    )

    # Scoped to the Teacher role by name. Deliberately not touching any other
    # role, and not touching a role renamed away from "Teacher" — a school that
    # renamed it made a decision this migration should not override.
    bind.execute(
        sa.text(
            """
            DELETE FROM role_permissions rp
            USING roles r, permissions p
            WHERE rp.role_id = r.id
              AND rp.permission_id = p.id
              AND r.name = 'Teacher'
              AND p.name = 'school_setup.read'
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"""
            INSERT INTO role_permissions
                (id, tenant_id, role_id, permission_id, created_at)
            SELECT gen_random_uuid()::text, j.tenant_id, j.role_id, p.id, now()
            FROM {_JOURNAL} j
            CROSS JOIN permissions p
            WHERE p.name = 'school_setup.read'
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions rp
                  WHERE rp.role_id = j.role_id AND rp.permission_id = p.id
              )
            """
        )
    )
    op.drop_table(_JOURNAL)
