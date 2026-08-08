"""An employment record says how it ended, not just that it did.

`staff_employment_periods` already holds when somebody worked here, and
`end_reason` holds a single word for why a period closed. That is not enough
to write a service letter from: it cannot say who decided, what notice was
given, what reason was recorded, or that somebody came back three years
later and did it all again.

`staff_lifecycle_events` is that record — the same shape as the student
timeline added in 098, because a school reads both the same way.

Revision ID: 100_an_employment_record_says_how_it_ended
Revises: 099_an_applicant_is_not_a_student
"""

import sqlalchemy as sa
from alembic import op

revision = "100_employment_says_how_it_ended"
down_revision = "099_an_applicant_is_not_a_student"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "staff_lifecycle_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("staff_id", sa.String(length=36), nullable=False),
        sa.Column("employment_period_id", sa.String(length=36), nullable=True),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
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
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="CASCADE"),
        # The period may be tidied away without taking the event with it —
        # that somebody resigned is true whether or not the row survives.
        sa.ForeignKeyConstraint(
            ["employment_period_id"],
            ["staff_employment_periods.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_staff_lifecycle_events_tenant_id", "staff_lifecycle_events", ["tenant_id"]
    )
    # Always read for one person, in order.
    op.create_index(
        "ix_sle_staff_occurred", "staff_lifecycle_events", ["staff_id", "occurred_on"]
    )


def downgrade():
    op.drop_index("ix_sle_staff_occurred", table_name="staff_lifecycle_events")
    op.drop_index("ix_staff_lifecycle_events_tenant_id", table_name="staff_lifecycle_events")
    op.drop_table("staff_lifecycle_events")
