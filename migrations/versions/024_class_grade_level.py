"""Add grade_level to classes for standard-based grouping (shared subjects across sections).

Revision ID: 024_class_grade_level
Revises: 023_academic_backbone
"""

from alembic import op
import sqlalchemy as sa

revision = "024_class_grade_level"
down_revision = "023_academic_backbone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "classes",
        sa.Column("grade_level", sa.SmallInteger(), nullable=True),
    )
    op.create_index("ix_classes_tenant_academic_year_grade", "classes", ["tenant_id", "academic_year_id", "grade_level"])


def downgrade() -> None:
    op.drop_index("ix_classes_tenant_academic_year_grade", table_name="classes")
    op.drop_column("classes", "grade_level")
