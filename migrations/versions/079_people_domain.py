"""people domain: persons, families, family members

First step of the v2 People model (ADR-001, ADR-002). Additive only, per
ADR-010: `users.person_id` is nullable here so the migration is safe to apply
before the backfill runs. A later migration makes it mandatory once every user
has a Person.

Revision ID: 079_people_domain
Revises: 078_department_permissions
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa

revision = "079_people_domain"
down_revision = "078_department_permissions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "persons",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(length=20), nullable=True),
        sa.Column("phone_number", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=120), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("occupation", sa.Text(), nullable=True),
        sa.Column("aadhaar_number", sa.String(length=20), nullable=True),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_persons_tenant_id", "persons", ["tenant_id"])
    # Duplicate detection looks people up by contact detail within one tenant.
    op.create_index("idx_persons_tenant_id_phone_number", "persons", ["tenant_id", "phone_number"])
    op.create_index("idx_persons_tenant_id_email", "persons", ["tenant_id", "email"])

    op.create_table(
        "families",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_families_tenant_id", "families", ["tenant_id"])

    op.create_table(
        "family_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False),
        sa.Column("person_id", sa.String(length=36), nullable=False),
        # Deliberately unconstrained: family relationships are data, so a new
        # one must not require a migration (ADR-002).
        sa.Column("relationship", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("family_id", "person_id", name="uq_family_members_family_person"),
    )
    op.create_index("ix_family_members_tenant_id", "family_members", ["tenant_id"])
    op.create_index("ix_family_members_family_id", "family_members", ["family_id"])
    op.create_index("ix_family_members_person_id", "family_members", ["person_id"])

    # Nullable until the backfill has given every user a Person.
    op.add_column("users", sa.Column("person_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_users_person_id", "users", "persons", ["person_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_users_person_id", "users", ["person_id"])


def downgrade():
    op.drop_index("ix_users_person_id", table_name="users")
    op.drop_constraint("fk_users_person_id", "users", type_="foreignkey")
    op.drop_column("users", "person_id")

    op.drop_index("ix_family_members_person_id", table_name="family_members")
    op.drop_index("ix_family_members_family_id", table_name="family_members")
    op.drop_index("ix_family_members_tenant_id", table_name="family_members")
    op.drop_table("family_members")

    op.drop_index("ix_families_tenant_id", table_name="families")
    op.drop_table("families")

    op.drop_index("idx_persons_tenant_id_email", table_name="persons")
    op.drop_index("idx_persons_tenant_id_phone_number", table_name="persons")
    op.drop_index("ix_persons_tenant_id", table_name="persons")
    op.drop_table("persons")
