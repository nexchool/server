"""What happens to a student, as things a school does rather than fields it sets.

A student leaving is not `student_status = 'withdrawn'`. It is a date, a
reason, the end of a place in a class, and a record that any of it happened.
Setting the word alone left the other four undone — which is why a graduated
student went on being billed, and why nothing could say when a child left or
why.

Each workflow here does the whole thing: the placement, the status, and the
event that lets someone reconstruct it later. `student_status` is not written
anywhere else (`update_student` refuses these values, `bulk_update_status` is
gone) so the workflow is the only way in, which is what makes the record
trustworthy.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from core.branch_scope import assert_student_allowed
from core.database import db
from core.school_time import school_today
from core.tenant import get_tenant_id

from .class_enrollment_service import assign_student_to_class
from .models import (
    EVENT_GRADUATED,
    EVENT_RE_ENROLLED,
    EVENT_WITHDRAWN,
    Student,
    StudentLifecycleEvent,
)

STATUS_ACTIVE = "active"
STATUS_WITHDRAWN = "withdrawn"
STATUS_GRADUATED = "graduated"

# A student who has already left cannot leave again, and one who has
# graduated has finished — neither is a state to withdraw from.
_CANNOT_LEAVE_AGAIN = frozenset({STATUS_WITHDRAWN, STATUS_GRADUATED})


def record_event(
    student: Student,
    event: str,
    *,
    occurred_on: Optional[datetime.date] = None,
    reason: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    recorded_by_user_id: Optional[str] = None,
) -> StudentLifecycleEvent:
    """Write one milestone to the student's history.

    Added to the session, not committed: an event describes something the
    caller is doing, so it belongs in that caller's transaction. If the work
    rolls back, so does the claim that it happened.
    """
    entry = StudentLifecycleEvent(
        tenant_id=student.tenant_id,
        student_id=student.id,
        event=event,
        occurred_on=occurred_on or school_today(),
        academic_year_id=student.academic_year_id,
        reason=reason,
        details=details,
        recorded_by_user_id=recorded_by_user_id,
    )
    db.session.add(entry)
    return entry


def timeline_for(student_id: str) -> list:
    """One student's history, oldest first — the order a story is read in."""
    return (
        StudentLifecycleEvent.query.filter_by(student_id=student_id)
        .order_by(
            StudentLifecycleEvent.occurred_on.asc(),
            StudentLifecycleEvent.created_at.asc(),
        )
        .all()
    )


def _student_for_workflow(student_id: str):
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None, {"success": False, "error": "Tenant context is required"}
    student = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
    if not student:
        return None, {"success": False, "error": "Student not found"}
    # A branch-restricted admin may only act on students in their own campus.
    assert_student_allowed(student_id)
    return student, None


def _refresh_billable_count(tenant_id: str) -> None:
    """Withdrawal and graduation change who the school is billed for."""
    try:
        from modules.subscription.usage import recompute_tenant_usage

        recompute_tenant_usage(tenant_id)
    except Exception:  # usage is best-effort; the workflow already happened
        import logging

        logging.getLogger(__name__).exception(
            "recompute_tenant_usage failed after a lifecycle change"
        )


def withdraw_student(
    student_id: str,
    *,
    reason: Optional[str] = None,
    occurred_on: Optional[datetime.date] = None,
    recorded_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A student leaves before completing their education.

    Their place in a class ends, so the enrollment closes and the class cache
    clears. Nothing is deleted: the Person, the studentship, the admission and
    every past enrollment stay exactly as they were, because a student who
    returns next year is the same child (see `reenroll_student`).
    """
    student, refusal = _student_for_workflow(student_id)
    if refusal:
        return refusal

    if student.student_status in _CANNOT_LEAVE_AGAIN:
        return {
            "success": False,
            "error": f"This student is already recorded as {student.student_status}",
        }

    left_class_id = student.class_id
    # Closes the current enrollment and clears students.class_id together, so
    # the cache and its owner cannot disagree.
    placement = assign_student_to_class(
        student_id, None, student.academic_year_id, commit=False
    )
    if not placement.get("success"):
        db.session.rollback()
        return {
            "success": False,
            "error": placement.get("error", "Could not end the student's placement"),
        }

    student.student_status = STATUS_WITHDRAWN
    record_event(
        student,
        EVENT_WITHDRAWN,
        occurred_on=occurred_on,
        reason=reason,
        details={"class_id": left_class_id} if left_class_id else None,
        recorded_by_user_id=recorded_by_user_id,
    )
    db.session.commit()
    _refresh_billable_count(student.tenant_id)

    return {"success": True, "student": student.to_dict()}


def graduate_student(
    student_id: str,
    *,
    occurred_on: Optional[datetime.date] = None,
    reason: Optional[str] = None,
    recorded_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A student completes their education.

    Deliberately does NOT leave a current enrollment behind: a graduate has no
    place in a class, and other modules read that absence — transport's year
    rollover skips exactly these students. What marks the graduation is the
    status and the event, not a terminal row.
    """
    student, refusal = _student_for_workflow(student_id)
    if refusal:
        return refusal

    if student.student_status == STATUS_GRADUATED:
        return {"success": False, "error": "This student has already graduated"}

    completed_class_id = student.class_id
    placement = assign_student_to_class(
        student_id, None, student.academic_year_id, commit=False
    )
    if not placement.get("success"):
        db.session.rollback()
        return {
            "success": False,
            "error": placement.get("error", "Could not close the student's placement"),
        }

    student.student_status = STATUS_GRADUATED
    record_event(
        student,
        EVENT_GRADUATED,
        occurred_on=occurred_on,
        reason=reason,
        details={"class_id": completed_class_id} if completed_class_id else None,
        recorded_by_user_id=recorded_by_user_id,
    )
    db.session.commit()
    _refresh_billable_count(student.tenant_id)

    return {"success": True, "student": student.to_dict()}


def reenroll_student(
    student_id: str,
    *,
    class_id: str,
    academic_year_id: Optional[str] = None,
    occurred_on: Optional[datetime.date] = None,
    reason: Optional[str] = None,
    recorded_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A student who left comes back.

    They are not admitted again. The canon is exact about this: the original
    Person, the original Student relationship and the original admission
    history all remain unchanged, and re-enrollment "simply creates a new
    Academic Enrollment". Re-admitting would mint a second admission number
    for one child and split their history in two.
    """
    student, refusal = _student_for_workflow(student_id)
    if refusal:
        return refusal

    if student.student_status not in (STATUS_WITHDRAWN, STATUS_GRADUATED):
        return {
            "success": False,
            "error": "Only a student who has left can be re-enrolled",
        }

    placement = assign_student_to_class(
        student_id, class_id, academic_year_id, commit=False
    )
    if not placement.get("success"):
        db.session.rollback()
        return {
            "success": False,
            "error": placement.get("error", "Could not place the returning student"),
        }

    student.student_status = STATUS_ACTIVE
    record_event(
        student,
        EVENT_RE_ENROLLED,
        occurred_on=occurred_on,
        reason=reason,
        details={"class_id": class_id},
        recorded_by_user_id=recorded_by_user_id,
    )
    db.session.commit()
    _refresh_billable_count(student.tenant_id)

    return {"success": True, "student": student.to_dict()}
