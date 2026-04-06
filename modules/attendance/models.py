from backend.core.database import db
from backend.core.models import TenantBaseModel
from datetime import datetime
import uuid


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

    # Who marked the attendance
    marked_by = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint(
            "date", "class_id", "student_id", "tenant_id",
            name="uq_attendance_date_class_student_tenant",
        ),
    )

    # Relationships
    class_ref = db.relationship('Class', backref=db.backref('attendance_records', lazy=True))
    student = db.relationship('Student', backref=db.backref('attendance_records', lazy=True))
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
            "marked_by": self.marked_by,
            "marked_by_name": self.marker.name if self.marker else None,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self):
        return f"<Attendance {self.date} student={self.student_id} status={self.status}>"
