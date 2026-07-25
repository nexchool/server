"""calendar audit fields

Adds created_by / updated_by (user id snapshots) to the calendar-managed
entities so the dashboard can show audit information: holidays, exam_windows,
school_events.

Revision ID: 073_calendar_audit_fields
Revises: 072_academic_calendar
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa


revision = "073_calendar_audit_fields"
down_revision = "072_academic_calendar"
branch_labels = None
depends_on = None

TABLES = ("holidays", "exam_windows", "school_events")


def upgrade():
    for table in TABLES:
        op.add_column(table, sa.Column("created_by", sa.String(length=36), nullable=True))
        op.add_column(table, sa.Column("updated_by", sa.String(length=36), nullable=True))


def downgrade():
    for table in reversed(TABLES):
        op.drop_column(table, "updated_by")
        op.drop_column(table, "created_by")
