"""Subjects module: subjects table.

Revision ID: 012_subjects_module
Revises: 011_fee_structure_multi_class
Create Date: 2025-03-06

- Creates subjects table (tenant-scoped)
- Unique: (name, tenant_id)
"""

from alembic import op
import sqlalchemy as sa

revision = "012_subjects_module"
down_revision = "011_fee_structure_multi_class"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subjects",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.String(20), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_subjects_tenant_id"), "subjects", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_subjects_name"), "subjects", ["name"], unique=False)
    op.create_unique_constraint(
        "uq_subjects_name_tenant",
        "subjects",
        ["name", "tenant_id"],
    )


def downgrade():
    op.drop_constraint("uq_subjects_name_tenant", "subjects", type_="unique")
    op.drop_index(op.f("ix_subjects_name"), table_name="subjects")
    op.drop_index(op.f("ix_subjects_tenant_id"), table_name="subjects")
    op.drop_table("subjects")
