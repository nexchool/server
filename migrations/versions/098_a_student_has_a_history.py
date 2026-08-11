"""A student has a history, and a status that means something.

Two gaps, one cause: a student's status was a column anyone could set, so
nothing recorded *why* it changed or *when*, and the workflows that should
have owned it did not exist.

`student_lifecycle_events` is the record the enrollments cannot keep.
Enrollments say where a student sat and when it ended; they cannot say
whether the year ended in a graduation, a withdrawal or a family moving
town. The alternative — withdrawn_on, withdrawal_reason, graduated_on
columns on `students` — is how a table stops describing a student and
starts describing a workflow.

The CHECK constraint closes the other half. `students.student_status` was a
30-character free-text column with the vocabulary enforced only by a request
validator, which is why the billing code has spent its life excluding
`'withdrawn'` — a value nothing could write. Every existing row already
satisfies this list; NULL stays legal because most rows have never had a
status set and NULL reads as active.

Revision ID: 098_a_student_has_a_history
Revises: 097_authority_stays_part_two
"""

import sqlalchemy as sa
from alembic import op

revision = "098_a_student_has_a_history"
down_revision = "097_authority_stays_part_two"
branch_labels = None
depends_on = None

_STATUSES = (
    "active",
    "inactive",
    "transferred",
    "graduated",
    "leaving",
    "suspended",
    "dropped_out",
    "withdrawn",
)


def upgrade():
    op.create_table(
        "student_lifecycle_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("student_id", sa.String(length=36), nullable=False),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("academic_year_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("recorded_by_user_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_student_lifecycle_events_tenant_id",
        "student_lifecycle_events",
        ["tenant_id"],
    )
    # The timeline is always read for one student, newest first.
    op.create_index(
        "ix_sle_student_occurred",
        "student_lifecycle_events",
        ["student_id", "occurred_on"],
    )
    op.create_index(
        "ix_student_lifecycle_events_academic_year_id",
        "student_lifecycle_events",
        ["academic_year_id"],
    )

    allowed = ", ".join(f"'{status}'" for status in _STATUSES)
    op.create_check_constraint(
        "ck_students_student_status",
        "students",
        f"student_status IS NULL OR student_status IN ({allowed})",
    )


def downgrade():
    op.drop_constraint("ck_students_student_status", "students", type_="check")
    op.drop_index("ix_student_lifecycle_events_academic_year_id", table_name="student_lifecycle_events")
    op.drop_index("ix_sle_student_occurred", table_name="student_lifecycle_events")
    op.drop_index("ix_student_lifecycle_events_tenant_id", table_name="student_lifecycle_events")
    op.drop_table("student_lifecycle_events")
