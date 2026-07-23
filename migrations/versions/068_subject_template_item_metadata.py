"""add role, medium and elective_group_key to subject_template_items

SubjectTemplateItem has declared these three columns since the school-setup
redesign (6ef586ca739c), but no migration ever created them. Every environment
therefore has 11 of the model's 14 columns, and seed_subject_templates.py --
which writes all three via _row() -- fails on insert. That is why the subject
template tables are empty everywhere.

All three are nullable: existing rows (there are none, but the migration must
not assume that) carry no values, and the template seeder supplies them going
forward.

Revision ID: 068_subject_template_item_metadata
Revises: 067_rename_student_document_storage_columns
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa


revision = "068_subject_template_item_metadata"
down_revision = "067_rename_student_document_storage_columns"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "subject_template_items",
        sa.Column("role", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "subject_template_items",
        sa.Column("medium", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "subject_template_items",
        sa.Column("elective_group_key", sa.String(length=80), nullable=True),
    )


def downgrade():
    op.drop_column("subject_template_items", "elective_group_key")
    op.drop_column("subject_template_items", "medium")
    op.drop_column("subject_template_items", "role")
