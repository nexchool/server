"""Add subject_id to class_teachers for real subject FK.

Revision ID: 013_class_teachers_subject_id
Revises: 012_subjects_module
Create Date: 2025-03-06

- Adds subject_id (UUID FK -> subjects.id) to class_teachers
- Keeps subject (string) for backward compatibility
"""

from alembic import op
import sqlalchemy as sa

revision = "013_class_teachers_subject_id"
down_revision = "012_subjects_module"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "class_teachers",
        sa.Column("subject_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_class_teachers_subject_id",
        "class_teachers",
        "subjects",
        ["subject_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_class_teachers_subject_id"),
        "class_teachers",
        ["subject_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_class_teachers_subject_id"), table_name="class_teachers")
    op.drop_constraint("fk_class_teachers_subject_id", "class_teachers", type_="foreignkey")
    op.drop_column("class_teachers", "subject_id")
