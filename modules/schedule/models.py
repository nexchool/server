"""
Schedule Override Models

Per-day overrides for timetable slots: substitute teacher assignment,
activity replacement, or class cancellation.
"""

import uuid
from datetime import datetime

from backend.core.database import db
from backend.core.models import TenantBaseModel


class ScheduleOverride(TenantBaseModel):
    """
    A per-day override of a timetable slot.

    override_type:
      'substitute' – different teacher takes the class
      'activity'   – replaced by an activity (sports, assembly, library, etc.)
      'cancelled'  – class is cancelled for the day

    Only one override per (slot_id, override_date).
    """
    __tablename__ = "schedule_overrides"
    __table_args__ = (
        db.UniqueConstraint("slot_id", "override_date", name="uq_schedule_override_slot_date"),
    )

    TYPE_SUBSTITUTE = "substitute"
    TYPE_ACTIVITY = "activity"
    TYPE_CANCELLED = "cancelled"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    slot_id = db.Column(
        db.String(36),
        db.ForeignKey("timetable_slots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    override_date = db.Column(db.Date, nullable=False, index=True)
    override_type = db.Column(db.String(20), nullable=False, default=TYPE_SUBSTITUTE)
    substitute_teacher_id = db.Column(
        db.String(36),
        db.ForeignKey("teachers.id", ondelete="SET NULL"),
        nullable=True,
    )
    activity_label = db.Column(db.String(100), nullable=True)
    note = db.Column(db.Text, nullable=True)
    created_by = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    slot_ref = db.relationship("TimetableSlot", foreign_keys=[slot_id], lazy=True)
    substitute_teacher = db.relationship("Teacher", foreign_keys=[substitute_teacher_id], lazy=True)
    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)

    def to_dict(self):
        sub_name = None
        if self.substitute_teacher and self.substitute_teacher.user:
            sub_name = self.substitute_teacher.user.name
        return {
            "id": self.id,
            "slot_id": self.slot_id,
            "override_date": self.override_date.isoformat() if self.override_date else None,
            "override_type": self.override_type,
            "substitute_teacher_id": self.substitute_teacher_id,
            "substitute_teacher_name": sub_name,
            "activity_label": self.activity_label,
            "note": self.note,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self):
        return f"<ScheduleOverride slot={self.slot_id} date={self.override_date} type={self.override_type}>"
