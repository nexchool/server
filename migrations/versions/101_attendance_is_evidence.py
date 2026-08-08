"""Attendance is evidence, so changing it leaves a record.

A settled register could be rewritten by anyone holding `attendance.manage`
and nothing was kept: not what it said before, not who changed it, not why.
For a record a school may be asked to produce — why a child was marked
absent on the day of an incident — that is the wrong shape.

`attendance_corrections` states the change, carries a required reason, names
who asked, and where the school requires it, waits for somebody to agree.

The two settings are the configurability the canon asks for and the product
did not have: whether corrections need approval, and the hour after which a
register stops accepting ordinary marks. Both default to today's behaviour —
no approval, no clock — so no school's process changes until it chooses to.

Revision ID: 101_attendance_is_evidence
Revises: 100_employment_says_how_it_ended
"""

import sqlalchemy as sa
from alembic import op

revision = "101_attendance_is_evidence"
down_revision = "100_employment_says_how_it_ended"
branch_labels = None
depends_on = None

_STATUSES = ("requested", "approved", "rejected")


def upgrade():
    op.add_column(
        "academic_settings",
        sa.Column(
            "attendance_corrections_require_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "academic_settings",
        sa.Column("attendance_lock_after_hours", sa.Integer(), nullable=True),
    )

    op.create_table(
        "attendance_corrections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("attendance_record_id", sa.String(length=36), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=False),
        sa.Column("to_status", sa.String(length=20), nullable=False),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attendance_record_id"], ["attendance_records.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _STATUSES) + ")",
            name="ck_attendance_corrections_status",
        ),
    )
    op.create_index(
        "ix_attendance_corrections_tenant_id", "attendance_corrections", ["tenant_id"]
    )
    op.create_index(
        "ix_attendance_corrections_record",
        "attendance_corrections",
        ["attendance_record_id"],
    )
    # The queue a reviewer opens.
    op.create_index(
        "ix_attendance_corrections_status", "attendance_corrections", ["status"]
    )


def downgrade():
    op.drop_index("ix_attendance_corrections_status", table_name="attendance_corrections")
    op.drop_index("ix_attendance_corrections_record", table_name="attendance_corrections")
    op.drop_index("ix_attendance_corrections_tenant_id", table_name="attendance_corrections")
    op.drop_table("attendance_corrections")
    op.drop_column("academic_settings", "attendance_lock_after_hours")
    op.drop_column("academic_settings", "attendance_corrections_require_approval")
