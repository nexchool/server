"""authority cannot cross organizations

Repairs assignments pointing at another organization's Authority Profile, then
makes the state unrepresentable: the composite foreign keys below require the
assignment and the profile to agree on the tenant, so the database refuses a
cross-tenant assignment regardless of what any code path asks for.

Found by the equivalence gate in scripts/backfill_authority.py while clearing
the way to retire user_roles: rows in one tenant pointed at Student profiles
owned by two others.

Revision ID: 088_authority_stays_in_its_organization
Revises: 087_relationship_implied_authority
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa

revision = "088_authority_stays_in_its_organization"
down_revision = "087_relationship_implied_authority"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()

    # A user assigned another school's "Student" profile plainly meant their own
    # school's, so grant them that — then remove every foreign assignment below.
    #
    # Written as insert-then-delete rather than repointing in place: a holder can
    # carry several foreign rows naming the same profile, and repointing them
    # would collide with the rule that a profile is held once. Conflicts are
    # simply skipped, which is exactly the intent.
    connection.execute(
        sa.text(
            """
            INSERT INTO user_roles (id, tenant_id, user_id, role_id, created_at)
            SELECT gen_random_uuid()::text, a.tenant_id, a.user_id, mine.id, now()
            FROM user_roles AS a
            JOIN roles AS theirs ON theirs.id = a.role_id
            JOIN roles AS mine ON mine.tenant_id = a.tenant_id AND mine.name = theirs.name
            WHERE theirs.tenant_id <> a.tenant_id
            ON CONFLICT DO NOTHING
            """
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO staff_authorities (id, tenant_id, staff_id, role_id, granted_at)
            SELECT gen_random_uuid()::text, a.tenant_id, a.staff_id, mine.id, now()
            FROM staff_authorities AS a
            JOIN roles AS theirs ON theirs.id = a.role_id
            JOIN roles AS mine ON mine.tenant_id = a.tenant_id AND mine.name = theirs.name
            WHERE theirs.tenant_id <> a.tenant_id
            ON CONFLICT DO NOTHING
            """
        )
    )

    # Every foreign assignment goes: the equivalent has just been granted where
    # one existed, and authority in another organization is not authority to keep.
    for table in ("user_roles", "staff_authorities", "role_permissions"):
        connection.execute(
            sa.text(
                f"""
                DELETE FROM {table} AS a
                USING roles AS r
                WHERE a.role_id = r.id AND r.tenant_id <> a.tenant_id
                """
            )
        )

    # Lets a foreign key reference (tenant_id, id) together.
    op.create_unique_constraint("uq_roles_tenant_id_id", "roles", ["tenant_id", "id"])

    for table, name in (
        ("user_roles", "fk_user_roles_role_within_tenant"),
        ("staff_authorities", "fk_staff_authorities_role_within_tenant"),
        ("role_permissions", "fk_role_permissions_role_within_tenant"),
    ):
        op.create_foreign_key(
            name,
            table,
            "roles",
            ["tenant_id", "role_id"],
            ["tenant_id", "id"],
            ondelete="CASCADE",
        )


def downgrade():
    for table, name in (
        ("role_permissions", "fk_role_permissions_role_within_tenant"),
        ("staff_authorities", "fk_staff_authorities_role_within_tenant"),
        ("user_roles", "fk_user_roles_role_within_tenant"),
    ):
        op.drop_constraint(name, table, type_="foreignkey")

    op.drop_constraint("uq_roles_tenant_id_id", "roles", type_="unique")
