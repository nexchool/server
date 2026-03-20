"""
Timetable Module - Models

TimetableSlot and TimetableConfig for School ERP.
Scoped by tenant.
"""

from datetime import datetime, time
import uuid

from backend.core.database import db
from backend.core.models import TenantBaseModel


# Default breaks structure: [{"after_period": 3, "duration_minutes": 15, "label": "Short Break"}, ...]
DEFAULT_BREAKS_JSON = [
    {"after_period": 3, "duration_minutes": 15, "label": "Short Break"},
    {"after_period": 5, "duration_minutes": 45, "label": "Lunch"},
    {"after_period": 7, "duration_minutes": 15, "label": "Short Break"},
]


class TimetableConfig(TenantBaseModel):
    """
    School-specific timetable configuration (one per tenant).

    Stores class durations, gaps, breaks. Used by the timetable generator
    to compute period start/end times. Persisted so it doesn't reset.
    """
    __tablename__ = "timetable_config"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", name="uq_timetable_config_tenant"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    general_class_duration_minutes = db.Column(db.Integer, nullable=False, default=45)
    first_class_duration_minutes = db.Column(db.Integer, nullable=False, default=50)
    gap_between_classes_minutes = db.Column(db.Integer, nullable=False, default=5)
    periods_per_day = db.Column(db.Integer, nullable=False, default=8)
    school_start_time = db.Column(db.Time, nullable=False, default=lambda: time(8, 0))
    breaks_json = db.Column(db.JSON, nullable=True)  # List of {after_period, duration_minutes, label}
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_breaks(self):
        return self.breaks_json if self.breaks_json is not None else DEFAULT_BREAKS_JSON

    def to_dict(self):
        def time_str(t):
            return t.strftime("%H:%M") if t and hasattr(t, "strftime") else None
        return {
            "id": self.id,
            "general_class_duration_minutes": self.general_class_duration_minutes,
            "first_class_duration_minutes": self.first_class_duration_minutes,
            "gap_between_classes_minutes": self.gap_between_classes_minutes,
            "periods_per_day": self.periods_per_day,
            "school_start_time": time_str(self.school_start_time),
            "breaks": self.get_breaks(),
        }


class TimetableSlot(TenantBaseModel):
    """
    TimetableSlot Model

    Represents a single period in the weekly timetable for a class.
    Links class, subject, and teacher. Unique per (class_id, day_of_week, period_number).
    day_of_week: 0=Monday, 6=Sunday.
    """
    __tablename__ = "timetable_slots"

    __table_args__ = (
        db.UniqueConstraint(
            "class_id", "day_of_week", "period_number",
            name="uq_timetable_slots_class_day_period",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    class_id = db.Column(
        db.String(36),
        db.ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id = db.Column(
        db.String(36),
        db.ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    teacher_id = db.Column(
        db.String(36),
        db.ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Monday, 6=Sunday
    period_number = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    room = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    class_ref = db.relationship("Class", foreign_keys=[class_id], lazy=True)
    subject_ref = db.relationship("Subject", foreign_keys=[subject_id], lazy=True)
    teacher_ref = db.relationship("Teacher", foreign_keys=[teacher_id], lazy=True)

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def _time_to_str(self, t):
        if t is None:
            return None
        return t.strftime("%H:%M") if hasattr(t, "strftime") else str(t)

    def to_dict(self):
        return {
            "id": self.id,
            "class_id": self.class_id,
            "subject_id": self.subject_id,
            "subject_name": self.subject_ref.name if self.subject_ref else None,
            "teacher_id": self.teacher_id,
            "teacher_name": self.teacher_ref.user.name if self.teacher_ref and self.teacher_ref.user else None,
            "day_of_week": self.day_of_week,
            "period_number": self.period_number,
            "start_time": self._time_to_str(self.start_time),
            "end_time": self._time_to_str(self.end_time),
            "room": self.room,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<TimetableSlot class={self.class_id} day={self.day_of_week} period={self.period_number}>"
