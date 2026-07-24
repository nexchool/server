"""
Academic Calendar Models

The academic calendar composes existing entities (AcademicYear, AcademicTerm,
Holiday) with three new ones:

  AcademicCalendar — one row per (tenant, academic_year); tracks the setup
      wizard state (current_step, status draft|published), the weekly-holiday
      configuration, and a summary snapshot taken at publish time.
  ExamWindow — a reserved date range for examinations, scoped to classes.
  SchoolEvent — a single-day school event (activity/meeting/celebration).

Weekly holidays:
  Full weekdays are stored as recurring Holiday rows (holiday_type=weekly_off)
  so existing consumers (attendance, dashboards) keep working. The
  second/fourth-Saturday flags live in weekly_holidays_config here because the
  Holiday model has no nth-weekday recurrence; matching dated rows are
  materialized at publish time (see services.publish_calendar).
"""

from datetime import datetime
import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

from core.database import db
from core.models import TenantBaseModel

CALENDAR_STATUSES = ("draft", "published", "archived")

# Allowed values for each per-calendar preference (validated in services).
CALENDAR_PREFERENCE_OPTIONS = {
    "default_view": ("month", "week", "list"),
    "week_start": ("monday", "sunday"),
    "date_format": ("dd_mmm_yyyy", "yyyy_mm_dd", "mm_dd_yyyy"),
    "time_format": ("24h", "12h"),
    "default_event_color": ("amber", "blue", "green", "red", "violet", "gray"),
}


def default_calendar_preferences() -> dict:
    return {
        "default_view": "month",
        "default_month": None,       # yyyy-mm; null = current month
        "week_start": "monday",
        "date_format": "dd_mmm_yyyy",
        "time_format": "24h",
        "default_event_color": "amber",
    }

# Wizard steps, in order. current_step holds the furthest step reached (1-based).
WIZARD_STEPS = (
    "academic_year",       # 1
    "weekly_holidays",     # 2
    "public_holidays",     # 3
    "vacations",           # 4
    "semesters",           # 5
    "exam_windows",        # 6
    "school_events",       # 7
    "review",              # 8
)
TOTAL_WIZARD_STEPS = len(WIZARD_STEPS)

EXAM_TYPES = ("unit_test", "mid_term", "final", "pre_board", "board", "other")
EVENT_TYPES = ("activity", "event", "meeting", "celebration", "training", "other")

APPLIES_TO_VALUES = ("entire_school", "students", "teachers", "staff")

# Lifecycle status shared by exam windows and school events. Only LIVE_STATUS
# rows drive the calendar (day classification, working-day math, summary);
# the rest stay editable in the list view but are off the live calendar.
EVENT_STATUSES = ("draft", "active", "archived", "cancelled")
LIVE_STATUS = "active"
# Statuses that free up their dates (excluded from overlap/duplicate checks).
INACTIVE_STATUSES = ("archived", "cancelled")

# Field-length limits enforced for names/descriptions across calendar events.
EVENT_NAME_MAX = 120
EVENT_DESCRIPTION_MAX = 1000


def default_weekly_holidays_config() -> dict:
    return {
        "days": [],                # Python weekday ints: 0=Mon … 6=Sun
        "second_saturday": False,
        "fourth_saturday": False,
    }


class AcademicCalendar(TenantBaseModel):
    """Setup/publish state of the academic calendar for one academic year."""

    __tablename__ = "academic_calendars"
    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "academic_year_id",
            name="uq_academic_calendars_tenant_year",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = db.Column(
        db.String(20), nullable=False, default="draft", server_default=text("'draft'")
    )
    current_step = db.Column(
        db.SmallInteger, nullable=False, default=1, server_default=text("1")
    )
    weekly_holidays_config = db.Column(JSONB, nullable=True)
    # Snapshot of the review summary at publish time (working days, counts).
    published_summary = db.Column(JSONB, nullable=True)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    published_by = db.Column(db.String(36), nullable=True)
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)
    archived_by = db.Column(db.String(36), nullable=True)
    # Per-calendar UI preferences (default view/month, week start, formats, color).
    preferences = db.Column(JSONB, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )

    academic_year = db.relationship("AcademicYear", foreign_keys=[academic_year_id])

    @property
    def weekly_config(self) -> dict:
        base = default_weekly_holidays_config()
        base.update(self.weekly_holidays_config or {})
        return base

    @property
    def prefs(self) -> dict:
        base = default_calendar_preferences()
        base.update(self.preferences or {})
        return base

    def to_dict(self):
        return {
            "id": self.id,
            "academic_year_id": self.academic_year_id,
            "academic_year": self.academic_year.to_dict() if self.academic_year else None,
            "status": self.status,
            "current_step": self.current_step,
            "total_steps": TOTAL_WIZARD_STEPS,
            "weekly_holidays_config": self.weekly_config,
            "preferences": self.prefs,
            "published_summary": self.published_summary,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "published_by": self.published_by,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "archived_by": self.archived_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<AcademicCalendar year={self.academic_year_id} status={self.status}>"


class ExamWindow(TenantBaseModel):
    """A reserved examination date range; timetable/events should avoid it."""

    __tablename__ = "exam_windows"
    __table_args__ = (
        db.Index("idx_exam_windows_tenant_year", "tenant_id", "academic_year_id"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False)
    exam_type = db.Column(db.String(20), nullable=False, default="other")
    status = db.Column(
        db.String(20), nullable=False, default="active",
        server_default=text("'active'"),
    )
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False)
    # List of class ids the window applies to; empty/null → all classes.
    applicable_class_ids = db.Column(JSONB, nullable=True)
    description = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.String(36), nullable=True)
    updated_by = db.Column(db.String(36), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )

    academic_year = db.relationship("AcademicYear", foreign_keys=[academic_year_id])

    @property
    def duration_days(self) -> int:
        if not self.start_date or not self.end_date:
            return 0
        return (self.end_date - self.start_date).days + 1

    def to_dict(self):
        return {
            "id": self.id,
            "academic_year_id": self.academic_year_id,
            "name": self.name,
            "exam_type": self.exam_type,
            "status": self.status,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "duration_days": self.duration_days,
            "applicable_class_ids": self.applicable_class_ids or [],
            "description": self.description,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<ExamWindow '{self.name}' {self.start_date}–{self.end_date}>"


class SchoolEvent(TenantBaseModel):
    """A single-day school event shown on the academic calendar."""

    __tablename__ = "school_events"
    __table_args__ = (
        db.Index("idx_school_events_tenant_year", "tenant_id", "academic_year_id"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(120), nullable=False)
    event_type = db.Column(db.String(20), nullable=False, default="event")
    status = db.Column(
        db.String(20), nullable=False, default="active",
        server_default=text("'active'"),
    )
    event_date = db.Column(db.Date, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    applies_to = db.Column(
        db.String(20), nullable=False, default="entire_school",
        server_default=text("'entire_school'"),
    )
    created_by = db.Column(db.String(36), nullable=True)
    updated_by = db.Column(db.String(36), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )

    academic_year = db.relationship("AcademicYear", foreign_keys=[academic_year_id])

    def to_dict(self):
        return {
            "id": self.id,
            "academic_year_id": self.academic_year_id,
            "name": self.name,
            "event_type": self.event_type,
            "status": self.status,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "description": self.description,
            "applies_to": self.applies_to,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<SchoolEvent '{self.name}' {self.event_date}>"
