"""What a student actually studies, where it differs from what the class offers.

`class_subjects` says what a section is taught. For most sections that is the
whole answer — every child in Grade 4 A takes all of it, and this table stays
empty. Grade 11 is where it stops being true: a Science section offers Biology
*and* Computer Science, and each student takes one.

So elections are **deviations**, not a roster. A school with no electives
writes no rows, and the simple case costs nothing.

The election belongs to the **enrollment**, not the student: the same child has
one subject set in Grade 10 2025-26 and another in Grade 11 2026-27, and may
also hold an additional enrollment (a coaching batch) with its own subjects.
Keying on student_id would collapse all of those into one list.
"""

import uuid

from sqlalchemy import CheckConstraint, Index, text

from core.database import db
from core.models import TenantBaseModel
from core.school_time import utc_now


# The student takes this subject. Meaningful on an elective (they chose it);
# redundant but permitted on a mandatory one.
ELECTION_TAKING = "taking"
# The student does not take it, though the class offers it.
ELECTION_DROPPED = "dropped"
# The school has excused them — a language exemption, a medical exemption from
# a practical. Distinct from dropped because a school is asked to justify it.
ELECTION_EXEMPTED = "exempted"

ELECTION_STATUSES = (ELECTION_TAKING, ELECTION_DROPPED, ELECTION_EXEMPTED)
# The two that remove a subject from the student's set.
ELECTION_NOT_TAKEN = (ELECTION_DROPPED, ELECTION_EXEMPTED)


class StudentSubjectElection(TenantBaseModel):
    """One student's decision about one subject their class offers."""

    __tablename__ = "student_subject_elections"
    __table_args__ = (
        Index(
            "uq_sse_enrollment_class_subject",
            "tenant_id",
            "student_class_enrollment_id",
            "class_subject_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "idx_sse_enrollment",
            "tenant_id",
            "student_class_enrollment_id",
        ),
        CheckConstraint(
            "status IN ('taking', 'dropped', 'exempted')",
            name="ck_sse_status",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_class_enrollment_id = db.Column(
        db.String(36),
        db.ForeignKey("student_class_enrollments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    class_subject_id = db.Column(
        db.String(36),
        db.ForeignKey("class_subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = db.Column(db.String(20), nullable=False, default=ELECTION_TAKING)
    # Why a school excused a child from a subject is the kind of thing they are
    # later asked to produce. Optional: choosing between two electives needs no
    # explanation.
    note = db.Column(db.Text, nullable=True)
    decided_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    enrollment = db.relationship(
        "StudentClassEnrollment",
        backref=db.backref("subject_elections", lazy="selectin"),
        passive_deletes=True,
    )
    class_subject = db.relationship("ClassSubject", lazy="joined")

    def to_dict(self):
        return {
            "id": self.id,
            "student_class_enrollment_id": self.student_class_enrollment_id,
            "class_subject_id": self.class_subject_id,
            "status": self.status,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<StudentSubjectElection {self.class_subject_id} {self.status}>"
