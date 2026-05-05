"""Student promotion batch audit table.

Revision ID: 041_student_promotion_batches
Revises: 040_academic_id_formats
"""

from alembic import op
import sqlalchemy as sa


revision = "041_student_promotion_batches"
down_revision = "040_academic_id_formats"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "student_promotion_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("from_academic_year_id", sa.String(length=36), nullable=False),
        sa.Column("to_academic_year_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("class_mapping_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["from_academic_year_id"],
            ["academic_years.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_academic_year_id"],
            ["academic_years.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_spb_tenant_created",
        "student_promotion_batches",
        ["tenant_id", "created_at"],
    )


def downgrade():
    op.drop_index("ix_spb_tenant_created", table_name="student_promotion_batches")
    op.drop_table("student_promotion_batches")
