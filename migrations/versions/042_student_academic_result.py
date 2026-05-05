"""Add optional academic_result on students (e.g. pass / fail) for promotion filters."""

from alembic import op
import sqlalchemy as sa


revision = "042_student_academic_result"
down_revision = "041_student_promotion_batches"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "students",
        sa.Column("academic_result", sa.String(length=20), nullable=True),
    )


def downgrade():
    op.drop_column("students", "academic_result")
