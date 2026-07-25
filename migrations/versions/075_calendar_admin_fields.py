"""calendar admin fields

Adds the columns backing the Academic Calendar admin/utilities layer:
  - archived_at / archived_by  — set when a published calendar is archived
    (status draft | published | archived; archived is read-only).
  - preferences JSONB          — per-calendar UI prefs (default view/month,
    week start, date/time format, default event color).

Revision ID: 075_calendar_admin_fields
Revises: 074_calendar_event_status
Create Date: 2026-07-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "075_calendar_admin_fields"
down_revision = "074_calendar_event_status"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "academic_calendars",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "academic_calendars",
        sa.Column("archived_by", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "academic_calendars",
        sa.Column("preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_column("academic_calendars", "preferences")
    op.drop_column("academic_calendars", "archived_by")
    op.drop_column("academic_calendars", "archived_at")
