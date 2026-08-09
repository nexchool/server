"""A section merge records who decided it, and why.

Migration 102 gave a merged section `merged_into_class_id` and `merged_on` —
where its future went, and when. That answers the reader who is looking at last
term's attendance and wondering why the section takes no students.

It does not answer the two questions a school actually asks a term later: who
decided, and what for. `merge_sections` already accepts `recorded_by_user_id`
and `reason` and passes them to each student transfer, so every child carries
the reason in their timeline — but the section itself, the thing that was
retired, records neither.

`person_merges` has recorded both since it was built. This brings the section
merge to the same standard.

Both nullable: a section merged before this migration has no answer, and
back-filling an actor we do not know would be worse than an empty column.

Revision ID: 104_a_merge_records_who_and_why
Revises: 103_a_teacher_is_not_an_onboarder
"""

import sqlalchemy as sa
from alembic import op

revision = "104_a_merge_records_who_and_why"
down_revision = "103_a_teacher_is_not_an_onboarder"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "classes",
        sa.Column("merged_by_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column("classes", sa.Column("merge_reason", sa.Text(), nullable=True))

    # SET NULL rather than CASCADE, for the same reason migration 102 gave the
    # merge itself: if the account that performed the merge is ever removed,
    # the merge still happened and the section must not lose the record of it.
    op.create_foreign_key(
        "fk_classes_merged_by_user",
        "classes",
        "users",
        ["merged_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_classes_merged_by_user", "classes", type_="foreignkey")
    op.drop_column("classes", "merge_reason")
    op.drop_column("classes", "merged_by_user_id")
