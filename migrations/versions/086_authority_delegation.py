"""temporary delegation of authority

A principal goes on leave and the vice principal acts in their place until they
return (ADR-006). Deliberately bounded by dates: expiry needs no scheduled job
because nothing reads a delegation outside its window.

Revision ID: 086_authority_delegation
Revises: 085_authority_on_employment
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa

revision = "086_authority_delegation"
down_revision = "085_authority_on_employment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "authority_delegations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("from_staff_id", sa.String(length=36), nullable=False),
        sa.Column("to_staff_id", sa.String(length=36), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_staff_id"], ["staff.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_staff_id"], ["staff.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        # A delegation that ends before it starts is not a delegation.
        sa.CheckConstraint("effective_to >= effective_from", name="ck_authority_delegations_dates"),
        # Lending authority to yourself is a no-op worth refusing outright.
        sa.CheckConstraint("from_staff_id <> to_staff_id", name="ck_authority_delegations_distinct"),
    )
    op.create_index("ix_authority_delegations_tenant_id", "authority_delegations", ["tenant_id"])
    op.create_index("ix_authority_delegations_role_id", "authority_delegations", ["role_id"])
    op.create_index("ix_authority_delegations_from_staff_id", "authority_delegations", ["from_staff_id"])
    # Read on every permission resolution for the person acting.
    op.create_index("ix_authority_delegations_to_staff_id", "authority_delegations", ["to_staff_id"])


def downgrade():
    op.drop_index("ix_authority_delegations_to_staff_id", table_name="authority_delegations")
    op.drop_index("ix_authority_delegations_from_staff_id", table_name="authority_delegations")
    op.drop_index("ix_authority_delegations_role_id", table_name="authority_delegations")
    op.drop_index("ix_authority_delegations_tenant_id", table_name="authority_delegations")
    op.drop_table("authority_delegations")
