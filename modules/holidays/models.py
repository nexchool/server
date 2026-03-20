"""
Holiday Model

Supports three holiday shapes:
  1. Single-day  — start_date == end_date, is_recurring=False
  2. Range       — start_date < end_date,  is_recurring=False  (vacations/breaks)
  3. Recurring   — is_recurring=True, recurring_day_of_week=0-6 (Mon=0 … Sun=6)
                   start_date/end_date are ignored; the holiday applies to every
                   matching weekday in the academic year.

Sunday collision:
  A computed property `falls_on_existing_off_day` (returned in to_dict()) is True
  when a non-recurring holiday's start_date falls on the tenant's weekly-off day
  (typically Sunday / recurring_day_of_week==6). The API consumers can surface
  this as a warning so admins can choose to add a compensatory holiday.
"""

from datetime import datetime
import uuid

from backend.core.database import db
from backend.core.models import TenantBaseModel

HOLIDAY_TYPES = ("public", "school", "regional", "optional", "weekly_off")

# Python weekday(): 0=Mon … 6=Sun
DAY_NAMES = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday",
}


class Holiday(TenantBaseModel):
    """
    Holiday record for a school tenant.
    Scoped by tenant_id (inherited from TenantBaseModel).
    """
    __tablename__ = "holidays"
    __table_args__ = (
        db.UniqueConstraint(
            "start_date", "name", "tenant_id",
            name="uq_holidays_start_date_name_tenant",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)

    holiday_type = db.Column(db.String(20), nullable=False, default="school")

    # Date range fields (both nullable to allow pure recurring with no fixed date)
    start_date = db.Column(db.Date, nullable=True, index=True)
    end_date = db.Column(db.Date, nullable=True, index=True)

    # Recurring pattern (e.g. every Sunday)
    is_recurring = db.Column(db.Boolean, nullable=False, default=False)
    recurring_day_of_week = db.Column(db.Integer, nullable=True)   # 0=Mon … 6=Sun

    # Optional link to an academic year
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False,
        default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    academic_year = db.relationship(
        "AcademicYear",
        backref=db.backref("holidays", lazy=True),
    )

    # ------------------------------------------------------------------
    # Computed helpers
    # ------------------------------------------------------------------

    @property
    def is_single_day(self) -> bool:
        """True when start == end (or no end set)."""
        if self.is_recurring:
            return False
        return self.start_date is not None and (
            self.end_date is None or self.start_date == self.end_date
        )

    @property
    def duration_days(self) -> int:
        """Number of calendar days covered (1 for single-day, >=2 for range)."""
        if self.is_recurring or not self.start_date:
            return 0
        end = self.end_date or self.start_date
        return max(1, (end - self.start_date).days + 1)

    @property
    def falls_on_sunday(self) -> bool:
        """True when a non-recurring single-day holiday lands on a Sunday."""
        if self.is_recurring or not self.start_date:
            return False
        return self.start_date.weekday() == 6  # 6 = Sunday

    @property
    def recurring_day_name(self) -> str | None:
        if self.recurring_day_of_week is not None:
            return DAY_NAMES.get(self.recurring_day_of_week)
        return None

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "holiday_type": self.holiday_type,
            # Date fields
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "is_single_day": self.is_single_day,
            "duration_days": self.duration_days,
            # Recurring
            "is_recurring": self.is_recurring,
            "recurring_day_of_week": self.recurring_day_of_week,
            "recurring_day_name": self.recurring_day_name,
            # Smart flags
            "falls_on_sunday": self.falls_on_sunday,
            # Relations
            "academic_year_id": self.academic_year_id,
            "academic_year_name": (
                self.academic_year.name if self.academic_year else None
            ),
            # Timestamps
            "tenant_id": self.tenant_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        if self.is_recurring:
            return f"<Holiday recurring={self.recurring_day_name} type={self.holiday_type}>"
        return f"<Holiday '{self.name}' {self.start_date}–{self.end_date} type={self.holiday_type}>"
