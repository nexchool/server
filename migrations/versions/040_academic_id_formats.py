"""Academic settings: per-tenant student admission and teacher employee ID format patterns.

Revision ID: 040_academic_id_formats
Revises: 039
"""

from alembic import op
import sqlalchemy as sa


revision = "040_academic_id_formats"
down_revision = "039_subject_code_unique"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "academic_settings",
        sa.Column("admission_number_format", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "academic_settings",
        sa.Column("teacher_employee_id_format", sa.String(length=120), nullable=True),
    )


def downgrade():
    op.drop_column("academic_settings", "teacher_employee_id_format")
    op.drop_column("academic_settings", "admission_number_format")
