"""a closed mark changes by request, never by edit

Migration 117 let a school close a paper for marking, and closing it was the
easy half. The hard half is what happens when the closed register turns out to
be wrong — which it does: a teacher adds a column twice, a re-check moves a
grade, an absence turns out to have been an approved exemption.

Until now there was nothing to do about it. Ordinary entry refuses a locked
paper (correctly), and the alternative would have been an unlock button — which
would put the register back exactly as it was before anyone could see that it
had moved, with no reason, no requester and no approver.

So a change to a closed mark is a *request*. `attendance_corrections`
(migration 101) already settled this shape for the same problem one domain
over, and this follows it deliberately rather than inventing a second one:
state the change, require a reason, name who asked, wait for someone who runs
assessment to decide, and keep the row afterwards whichever way they decided.

Two things here that attendance does not have, both earned by marks being
numbers rather than a status:

`from_marks` / `to_marks` sit beside `from_status` / `to_status`, and the CHECK
constraints hold both ends to the same rule the mark itself obeys — present
means a number, anything else means none. A correction cannot describe a state
a mark could not be in.

The `from_*` pair is what makes a **stale** request refusable. Two teachers can
ask for the same mark to move; approving the first makes the second's "72 → 75"
an instruction computed against a number nobody is looking at any more.
Recording what it was asked *from* is what lets the approval notice.

The composite FK `(tenant_id, exam_mark_id)` follows the examinations
convention (migrations 114/116) rather than attendance's single-column one —
`uq_exam_marks_tenant_id_id` exists, so the stronger guard is available and
costs nothing.

No `deleted_at`: an audit row that can be soft-deleted is not an audit row.

Revision ID: 118_a_closed_mark_changes_by_request
Revises: 117_a_paper_can_be_closed_for_marking
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa

revision = "118_a_closed_mark_changes_by_request"
down_revision = "117_a_paper_can_be_closed_for_marking"
branch_labels = None
depends_on = None

_STATUSES = ("requested", "approved", "rejected")


def upgrade():
    op.create_table(
        "exam_mark_corrections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("exam_mark_id", sa.String(length=36), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=False),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("from_marks", sa.Numeric(6, 2), nullable=True),
        sa.Column("to_marks", sa.Numeric(6, 2), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="requested"
        ),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("decided_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exam_mark_id"],
            ["exam_marks.tenant_id", "exam_marks.id"],
            name="fk_exam_mark_corrections_mark",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _STATUSES) + ")",
            name="ck_exam_mark_corrections_status",
        ),
        sa.CheckConstraint(
            "(from_status = 'present' AND from_marks IS NOT NULL) OR "
            "(from_status <> 'present' AND from_marks IS NULL)",
            name="ck_exam_mark_corrections_from_consistent",
        ),
        sa.CheckConstraint(
            "(to_status = 'present' AND to_marks IS NOT NULL) OR "
            "(to_status <> 'present' AND to_marks IS NULL)",
            name="ck_exam_mark_corrections_to_consistent",
        ),
        sa.CheckConstraint(
            "(from_marks IS NULL OR from_marks >= 0) AND "
            "(to_marks IS NULL OR to_marks >= 0)",
            name="ck_exam_mark_corrections_not_negative",
        ),
    )
    op.create_index(
        "ix_exam_mark_corrections_tenant_id", "exam_mark_corrections", ["tenant_id"]
    )
    # "Every correction on this mark", which is the mark's own history.
    op.create_index(
        "idx_exam_mark_corrections_mark",
        "exam_mark_corrections",
        ["tenant_id", "exam_mark_id"],
    )
    # The queue a reviewer opens. Partial, because a decided correction is
    # never listed there and a school accumulates far more of those.
    op.create_index(
        "idx_exam_mark_corrections_pending",
        "exam_mark_corrections",
        ["tenant_id", "status"],
        postgresql_where=sa.text("status = 'requested'"),
    )


def downgrade():
    op.drop_index(
        "idx_exam_mark_corrections_pending", table_name="exam_mark_corrections"
    )
    op.drop_index("idx_exam_mark_corrections_mark", table_name="exam_mark_corrections")
    op.drop_index(
        "ix_exam_mark_corrections_tenant_id", table_name="exam_mark_corrections"
    )
    op.drop_table("exam_mark_corrections")
