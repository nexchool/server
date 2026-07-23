"""add exam_code to subject_template_items and subject_contexts

A subject `code` is the tenant-wide natural key and must be board-agnostic. The
board's exam paper number is not: CBSE 054 is Business Studies while GSEB 054 is
Physics, and within GSEB the same subject changes number by standard (Gujarati is
01 at Std 10 and 001 at Std 12). It is therefore metadata on the offering, not
identity on the subject.

Revision ID: 069_subject_exam_codes
Revises: 068_subject_template_item_metadata
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa


revision = "069_subject_exam_codes"
down_revision = "068_subject_template_item_metadata"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "subject_template_items",
        sa.Column("exam_code", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "subject_contexts",
        sa.Column("exam_code", sa.String(length=20), nullable=True),
    )


def downgrade():
    op.drop_column("subject_contexts", "exam_code")
    op.drop_column("subject_template_items", "exam_code")
