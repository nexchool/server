"""record of merged people

ADR-010 promises that a merge is recoverable. This is where that promise lives:
the absorbed person's details are kept in full, so a merge made in error can be
understood and undone.

Revision ID: 083_person_merges
Revises: 082_account_requires_person
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa

revision = "083_person_merges"
down_revision = "082_account_requires_person"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "person_merges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("kept_person_id", sa.String(length=36), nullable=False),
        sa.Column("absorbed_person_id", sa.String(length=36), nullable=False),
        sa.Column("absorbed_person_details", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("merged_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        # RESTRICT on both: a merge record is worthless if either person it
        # describes can quietly disappear.
        sa.ForeignKeyConstraint(["kept_person_id"], ["persons.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["absorbed_person_id"], ["persons.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["merged_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_person_merges_tenant_id", "person_merges", ["tenant_id"])
    op.create_index("ix_person_merges_kept_person_id", "person_merges", ["kept_person_id"])
    op.create_index("ix_person_merges_absorbed_person_id", "person_merges", ["absorbed_person_id"])


def downgrade():
    op.drop_index("ix_person_merges_absorbed_person_id", table_name="person_merges")
    op.drop_index("ix_person_merges_kept_person_id", table_name="person_merges")
    op.drop_index("ix_person_merges_tenant_id", table_name="person_merges")
    op.drop_table("person_merges")
