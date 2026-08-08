from core.database import db
from core.models import TenantBaseModel
from datetime import datetime
import uuid
from core.school_time import utc_now


class Attendance(TenantBaseModel):
    """
    DEPRECATED (migration 023): Prefer AttendanceSession + AttendanceRecord for new reads/writes.

    Legacy flat table — one row per student per class per date. Kept for backward compatibility
    until attendance services are switched to session-based API (phase 2).
    """
    __tablename__ = "attendance"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    date = db.Column(db.Date, nullable=False, index=True)
    class_id = db.Column(db.String(36), db.ForeignKey("classes.id"), nullable=False)
    student_id = db.Column(db.String(36), db.ForeignKey("students.id"), nullable=False)
    status = db.Column(db.String(10), nullable=False)  # present / absent / late
    remarks = db.Column(db.Text, nullable=True)
    leave_id = db.Column(
        db.String(36),
        db.ForeignKey("student_leaves.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Who marked the attendance
    marked_by = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        db.UniqueConstraint(
            "date", "class_id", "student_id", "tenant_id",
            name="uq_attendance_date_class_student_tenant",
        ),
    )

    # Relationships
    class_ref = db.relationship('Class', backref=db.backref('attendance_records', lazy=True))
    student = db.relationship(
        'Student',
        backref=db.backref('attendance_records', lazy=True),
        passive_deletes=True,
    )
    marker = db.relationship('User', foreign_keys=[marked_by])

    def save(self):
        db.session.add(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "class_id": self.class_id,
            "student_id": self.student_id,
            "student_name": self.student.user.name if self.student and self.student.user else None,
            "admission_number": self.student.admission_number if self.student else None,
            "status": self.status,
            "remarks": self.remarks,
            "leave_id": self.leave_id,
            "marked_by": self.marked_by,
            "marked_by_name": self.marker.name if self.marker else None,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self):
        return f"<Attendance {self.date} student={self.student_id} status={self.status}>"


CORRECTION_REQUESTED = "requested"
CORRECTION_APPROVED = "approved"
CORRECTION_REJECTED = "rejected"

CORRECTION_STATUSES = (CORRECTION_REQUESTED, CORRECTION_APPROVED, CORRECTION_REJECTED)


class AttendanceCorrection(TenantBaseModel):
    """A request to change attendance that has already been settled.

    Attendance is evidence. A teacher marking the register is one thing; a
    record being altered a week later is another, and a school asked why a
    child was absent on the day of an incident needs to be able to answer
    what was recorded, what it was changed to, by whom and why.

    So a correction is never an edit. It states the change, carries a reason,
    names its requester, and — where the school requires it — waits for
    someone to approve it. Applying it is what finally moves the record.
    """

    __tablename__ = "attendance_corrections"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    attendance_record_id = db.Column(
        db.String(36),
        db.ForeignKey("attendance_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # What it was when the correction was asked for, kept even after the
    # record moves on — the point of the record is the change, not the end
    # state, which the record itself already holds.
    from_status = db.Column(db.String(20), nullable=False)
    to_status = db.Column(db.String(20), nullable=False)
    # Required. A correction without a reason is an edit with extra steps.
    reason = db.Column(db.Text, nullable=False)

    status = db.Column(
        db.String(20), nullable=False, default=CORRECTION_REQUESTED, index=True
    )
    requested_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    decided_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at = db.Column(db.DateTime(timezone=True), nullable=True)
    decision_note = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "attendance_record_id": self.attendance_record_id,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "reason": self.reason,
            "status": self.status,
            "requested_by_user_id": self.requested_by_user_id,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "decided_by_user_id": self.decided_by_user_id,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decision_note": self.decision_note,
        }

    def __repr__(self):
        return f"<AttendanceCorrection {self.from_status}->{self.to_status} {self.status}>"
