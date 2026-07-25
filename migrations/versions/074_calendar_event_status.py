"""calendar event status

Adds a lifecycle `status` (draft | active | archived | cancelled) to the
calendar's schedulable entities — exam_windows and school_events. Only
`active` rows drive the live calendar (day classification, working-day math,
summary counts); the others stay manageable in the list view.

Revision ID: 074_calendar_event_status
Revises: 073_calendar_audit_fields
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa


revision = "074_calendar_event_status"
down_revision = "073_calendar_audit_fields"
branch_labels = None
depends_on = None

TABLES = ("exam_windows", "school_events")


def upgrade():
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default=sa.text("'active'"),
            ),
        )


def downgrade():
    for table in reversed(TABLES):
        op.drop_column(table, "status")
