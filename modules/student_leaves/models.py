"""StudentLeave model — single source of truth for student leave requests."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text

from core.database import db
from core.models import TenantBaseModel


# Leave type and status values are kept as module-level tuples to avoid
# divergence between service code, route validation, and the DB check constraints.
LEAVE_TYPES = ("sick", "medical", "family", "religious", "other")
LEAVE_STATUSES = (
    "pending_class_teacher",
    "pending_admin",
    "approved",
    "rejected",
    "cancelled",
)
HALF_DAY_VALUES = ("am", "pm")


class StudentLeave(TenantBaseModel):
    """Student leave request — one row per submitted request."""

    __tablename__ = "student_leaves"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    student_id = db.Column(db.String(36), db.ForeignKey("students.id"), nullable=False, index=True)
    class_id = db.Column(db.String(36), db.ForeignKey("classes.id"), nullable=False)
    # Snapshot of the class teacher at submit time — used for admin fallback eligibility
    # even if the student is later reassigned to a different class.
    class_teacher_id = db.Column(db.String(36), db.ForeignKey("teachers.id"), nullable=True)

    leave_type = db.Column(db.String(20), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    half_day = db.Column(db.String(4), nullable=True)
    reason = db.Column(db.Text, nullable=False)
    attachment_document_id = db.Column(
        db.String(36),
        db.ForeignKey("student_documents.id", ondelete="SET NULL"),
        nullable=True,
    )

    status = db.Column(db.String(32), nullable=False)
    requires_admin_approval = db.Column(db.Boolean, nullable=False, default=False, server_default=text("false"))

    decided_by_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = db.Column(db.DateTime(timezone=True), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)

    cancel_requested_at = db.Column(db.DateTime(timezone=True), nullable=True)
    cancel_requested_reason = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=datetime.utcnow
    )

    # Relationships
    student = db.relationship("Student", foreign_keys=[student_id])
    class_ref = db.relationship("Class", foreign_keys=[class_id])
    class_teacher = db.relationship("Teacher", foreign_keys=[class_teacher_id])
    attachment = db.relationship("StudentDocument", foreign_keys=[attachment_document_id])
    decided_by = db.relationship("User", foreign_keys=[decided_by_id])

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "student_id": self.student_id,
            "student_name": self.student.user.name if self.student and self.student.user else None,
            "admission_number": self.student.admission_number if self.student else None,
            "class_id": self.class_id,
            "class_teacher_id": self.class_teacher_id,
            "leave_type": self.leave_type,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "half_day": self.half_day,
            "reason": self.reason,
            "attachment_document_id": self.attachment_document_id,
            "status": self.status,
            "requires_admin_approval": self.requires_admin_approval,
            "decided_by_id": self.decided_by_id,
            "decided_by_name": self.decided_by.name if self.decided_by else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "rejection_reason": self.rejection_reason,
            "cancel_requested_at": self.cancel_requested_at.isoformat() if self.cancel_requested_at else None,
            "cancel_requested_reason": self.cancel_requested_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<StudentLeave id={self.id} student={self.student_id} {self.start_date}→{self.end_date} {self.status}>"
