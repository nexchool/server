"""a paper can be closed for marking without waiting for the whole examination

Marks are editable while the examination sits in `marks_entry`. That is the
right outer boundary, and it is not a fine enough one: a teacher finishes
Mathematics on Tuesday while Science is still being marked on Friday, and until
the whole examination publishes there is nothing stopping a finished paper
being edited again.

Attendance solved the same problem at the same grain — a session is finalised
one register at a time, not a term at a time — so a paper closes one paper at
a time.

Two columns, on `exam_papers` rather than on every mark, because the school
closes a *paper*: forty marks do not each get locked individually, and putting
the flag on the mark would let half a register be locked.

`marks_locked_at IS NOT NULL` is the whole rule. Ordinary marks entry refuses a
locked paper; changing a locked mark needs the correction workflow, which is
deliberately not built here (EX-02B) — this migration exists so that when it
is, there is something to correct *from*, and so "we will lock it later" does
not leave finished marks quietly mutable in the meantime.

Revision ID: 117_a_paper_can_be_closed_for_marking
Revises: 116_a_paper_cannot_disagree_with_its_offering
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "117_a_paper_can_be_closed_for_marking"
down_revision = "116_a_paper_cannot_disagree_with_its_offering"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "exam_papers",
        sa.Column("marks_locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "exam_papers",
        sa.Column("marks_locked_by_user_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_exam_papers_marks_locked_by",
        "exam_papers",
        "users",
        ["marks_locked_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # "Which papers are still open" is the question a marks-entry screen asks
    # on every load, per examination.
    op.create_index(
        "idx_exam_papers_marks_locked_at",
        "exam_papers",
        ["tenant_id", "examination_id", "marks_locked_at"],
    )


def downgrade():
    op.drop_index("idx_exam_papers_marks_locked_at", table_name="exam_papers")
    op.drop_constraint(
        "fk_exam_papers_marks_locked_by", "exam_papers", type_="foreignkey"
    )
    op.drop_column("exam_papers", "marks_locked_by_user_id")
    op.drop_column("exam_papers", "marks_locked_at")
