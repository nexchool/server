"""Two sections become one, and the other keeps its history.

Schools merge sections mid-year when a grade loses students or a teacher
leaves. Nothing in the schema could express it: `classes` had no status, no
deleted_at, nothing — a section, once created, was live forever.

Deleting the absorbed one was never an option. Its attendance, its marks and
its reports happened there and stay there, which is what the canon requires:
"Historical records remain associated with their original Sections. Only
future activities use the merged Section."

So the section is marked with where its future went. One column carries both
the fact a reader needs — 8B merged into 8A — and the flag that stops
anything new being placed into it.

Revision ID: 102_two_sections_become_one
Revises: 101_attendance_is_evidence
"""

import sqlalchemy as sa
from alembic import op

revision = "102_two_sections_become_one"
down_revision = "101_attendance_is_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "classes",
        sa.Column("merged_into_class_id", sa.String(length=36), nullable=True),
    )
    op.add_column("classes", sa.Column("merged_on", sa.Date(), nullable=True))
    # SET NULL rather than CASCADE: if the surviving section were ever
    # removed, the merged one must not vanish with it — it still holds the
    # history of everything that happened before the merge.
    op.create_foreign_key(
        "fk_classes_merged_into_class",
        "classes",
        "classes",
        ["merged_into_class_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_classes_merged_into_class", "classes", type_="foreignkey")
    op.drop_column("classes", "merged_on")
    op.drop_column("classes", "merged_into_class_id")
