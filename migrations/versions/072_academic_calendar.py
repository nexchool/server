"""academic calendar module

Creates the three academic-calendar tables:
  - academic_calendars  (wizard/publish state per academic year)
  - exam_windows        (reserved exam date ranges)
  - school_events       (single-day calendar events)

Also adds holidays.applies_to (audience; defaults to entire_school).

Revision ID: 072_academic_calendar
Revises: 071_programme_template_board_code
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "072_academic_calendar"
down_revision = "071_programme_template_board_code"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "academic_calendars",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("academic_year_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("current_step", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("weekly_holidays_config", JSONB, nullable=True),
        sa.Column("published_summary", JSONB, nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "academic_year_id", name="uq_academic_calendars_tenant_year"),
    )
    op.create_index("ix_academic_calendars_tenant_id", "academic_calendars", ["tenant_id"])
    op.create_index("ix_academic_calendars_academic_year_id", "academic_calendars", ["academic_year_id"])

    op.create_table(
        "exam_windows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("academic_year_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("exam_type", sa.String(length=20), nullable=False, server_default=sa.text("'other'")),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("applicable_class_ids", JSONB, nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_exam_windows_tenant_id", "exam_windows", ["tenant_id"])
    op.create_index("ix_exam_windows_academic_year_id", "exam_windows", ["academic_year_id"])
    op.create_index("ix_exam_windows_start_date", "exam_windows", ["start_date"])
    op.create_index("idx_exam_windows_tenant_year", "exam_windows", ["tenant_id", "academic_year_id"])

    op.create_table(
        "school_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("academic_year_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False, server_default=sa.text("'event'")),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("applies_to", sa.String(length=20), nullable=False, server_default=sa.text("'entire_school'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_school_events_tenant_id", "school_events", ["tenant_id"])
    op.create_index("ix_school_events_academic_year_id", "school_events", ["academic_year_id"])
    op.create_index("ix_school_events_event_date", "school_events", ["event_date"])
    op.create_index("idx_school_events_tenant_year", "school_events", ["tenant_id", "academic_year_id"])

    op.add_column(
        "holidays",
        sa.Column(
            "applies_to",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'entire_school'"),
        ),
    )


def downgrade():
    op.drop_column("holidays", "applies_to")
    op.drop_index("idx_school_events_tenant_year", table_name="school_events")
    op.drop_index("ix_school_events_event_date", table_name="school_events")
    op.drop_index("ix_school_events_academic_year_id", table_name="school_events")
    op.drop_index("ix_school_events_tenant_id", table_name="school_events")
    op.drop_table("school_events")
    op.drop_index("idx_exam_windows_tenant_year", table_name="exam_windows")
    op.drop_index("ix_exam_windows_start_date", table_name="exam_windows")
    op.drop_index("ix_exam_windows_academic_year_id", table_name="exam_windows")
    op.drop_index("ix_exam_windows_tenant_id", table_name="exam_windows")
    op.drop_table("exam_windows")
    op.drop_index("ix_academic_calendars_academic_year_id", table_name="academic_calendars")
    op.drop_index("ix_academic_calendars_tenant_id", table_name="academic_calendars")
    op.drop_table("academic_calendars")
