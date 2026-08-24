"""Recording and resolving what a student studies.

**One authoritative resolution path.** `effective_class_subjects` is the only
place that combines the class's offerings with a student's elections, so
Examination, attendance, report cards, the timetable and the student profile
all get the same answer. If a second one appears, the two will disagree and
neither will be wrong on its own.

The rule, in the order a school would state it:

    every active mandatory subject the class offers
  + every elective the student elected to take
  - anything they dropped or were exempted from

An elective with no election is **not** taken. That is the difference between
an elective and a mandatory subject, and it is why a Science section offering
both Biology and Computer Science does not put every student in both.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.database import db
from modules.academics.backbone.models import StudentClassEnrollment
from modules.classes.models import ClassSubject

from .elections import (
    ELECTION_NOT_TAKEN,
    ELECTION_STATUSES,
    ELECTION_TAKING,
    StudentSubjectElection,
)


def _refuse(message: str) -> Dict[str, Any]:
    return {"success": False, "error": message}


def _active_class_subjects(tenant_id: str, class_id: str) -> List[ClassSubject]:
    """What this class is taught. Mirrors `subjects.services` exactly.

    Both readings of "active" are applied — `status` and `deleted_at` — because
    the rest of the academic code treats a class subject as live only when both
    agree.
    """
    return (
        ClassSubject.query.filter(
            ClassSubject.tenant_id == tenant_id,
            ClassSubject.class_id == class_id,
            ClassSubject.deleted_at.is_(None),
            ClassSubject.status == "active",
        )
        .order_by(ClassSubject.sort_order.asc().nullslast(), ClassSubject.id.asc())
        .all()
    )


def elections_for_enrollment(
    enrollment_id: str, tenant_id: str
) -> List[StudentSubjectElection]:
    return (
        StudentSubjectElection.query.filter(
            StudentSubjectElection.tenant_id == tenant_id,
            StudentSubjectElection.student_class_enrollment_id == enrollment_id,
            StudentSubjectElection.deleted_at.is_(None),
        ).all()
    )


def effective_class_subjects(
    enrollment_id: str, tenant_id: str
) -> List[ClassSubject]:
    """The subjects this enrollment actually studies.

    Returns `ClassSubject` rows rather than ids or dicts so callers keep the
    weekly load, term and elective flags they already read elsewhere.
    """
    enrollment = StudentClassEnrollment.query.filter_by(
        id=enrollment_id, tenant_id=tenant_id
    ).first()
    if enrollment is None:
        return []

    offered = _active_class_subjects(tenant_id, enrollment.class_id)
    decisions = {
        row.class_subject_id: row.status
        for row in elections_for_enrollment(enrollment_id, tenant_id)
    }

    effective: List[ClassSubject] = []
    for offering in offered:
        decision = decisions.get(offering.id)
        if decision in ELECTION_NOT_TAKEN:
            continue
        if offering.is_mandatory:
            effective.append(offering)
        elif decision == ELECTION_TAKING:
            effective.append(offering)
        # An elective nobody elected is simply not studied.
    return effective


def record_election(
    *,
    tenant_id: str,
    enrollment_id: str,
    class_subject_id: str,
    status: str,
    note: Optional[str] = None,
    decided_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """State what a student does about one subject their class offers.

    Idempotent per (enrollment, class subject): recording again updates the
    standing decision rather than adding a second one, because a student has
    one answer per subject and the unique index says so.
    """
    if status not in ELECTION_STATUSES:
        return _refuse(f"status must be one of {', '.join(ELECTION_STATUSES)}")

    enrollment = StudentClassEnrollment.query.filter_by(
        id=enrollment_id, tenant_id=tenant_id
    ).first()
    if enrollment is None:
        return _refuse("Enrollment not found")

    offering = ClassSubject.query.filter_by(
        id=class_subject_id, tenant_id=tenant_id
    ).first()
    if offering is None:
        return _refuse("Class subject not found")

    # The decision only means something about the class the student is in.
    # Electing a subject from another section is how a student ends up sitting
    # a paper nobody scheduled for them.
    if offering.class_id != enrollment.class_id:
        return _refuse(
            "That subject belongs to a different class than this enrollment"
        )

    if offering.deleted_at is not None or offering.status != "active":
        return _refuse("That subject is no longer offered by this class")

    existing = StudentSubjectElection.query.filter_by(
        tenant_id=tenant_id,
        student_class_enrollment_id=enrollment_id,
        class_subject_id=class_subject_id,
        deleted_at=None,
    ).first()

    if existing is not None:
        existing.status = status
        if note is not None:
            existing.note = note
        if decided_by_user_id is not None:
            existing.decided_by_user_id = decided_by_user_id
        db.session.flush()
        return {"success": True, "election_id": existing.id, "created": False}

    row = StudentSubjectElection(
        tenant_id=tenant_id,
        student_class_enrollment_id=enrollment_id,
        class_subject_id=class_subject_id,
        status=status,
        note=note,
        decided_by_user_id=decided_by_user_id,
    )
    db.session.add(row)
    db.session.flush()
    return {"success": True, "election_id": row.id, "created": True}


def withdraw_election(enrollment_id: str, class_subject_id: str, tenant_id: str) -> Dict[str, Any]:
    """Remove a standing decision, returning the subject to the class default.

    Soft-deleted rather than removed: what a school decided about a child's
    subjects is the kind of thing it is later asked about, and the partial
    unique index lets a fresh decision be recorded afterwards.
    """
    row = StudentSubjectElection.query.filter_by(
        tenant_id=tenant_id,
        student_class_enrollment_id=enrollment_id,
        class_subject_id=class_subject_id,
        deleted_at=None,
    ).first()
    if row is None:
        return _refuse("No election recorded for that subject")

    from core.school_time import utc_now

    row.deleted_at = utc_now()
    db.session.flush()
    return {"success": True}


def class_has_electives(tenant_id: str, class_id: str) -> bool:
    """Whether this class asks its students to choose anything.

    The admin screens use this to stay out of the way: a class with no
    electives should look exactly as it did before elections existed.
    """
    return bool(
        ClassSubject.query.filter(
            ClassSubject.tenant_id == tenant_id,
            ClassSubject.class_id == class_id,
            ClassSubject.deleted_at.is_(None),
            ClassSubject.status == "active",
            ClassSubject.is_mandatory.is_(False),
        ).first()
    )
