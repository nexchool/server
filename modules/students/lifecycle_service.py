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

from core.branch_scope import assert_class_allowed, assert_student_allowed
from core.database import db
from core.school_time import school_today
from core.tenant import get_tenant_id

from .class_enrollment_service import assign_student_to_class
from .models import (
    EVENT_GRADUATED,
    EVENT_RE_ENROLLED,
    EVENT_SECTION_TRANSFERRED,
    EVENT_TRANSFERRED_OUT,
    EVENT_WITHDRAWN,
    Student,
    StudentLifecycleEvent,
)

STATUS_ACTIVE = "active"
STATUS_WITHDRAWN = "withdrawn"
STATUS_GRADUATED = "graduated"
STATUS_TRANSFERRED = "transferred"

# A student who has already gone cannot go again, and one who has graduated
# has finished — none of these is a state to leave from.
_ALREADY_GONE = frozenset({STATUS_WITHDRAWN, STATUS_GRADUATED, STATUS_TRANSFERRED})


def _refuse(code: str, message: str) -> Dict[str, Any]:
    """Say no in a way both transports can read.

    The message is for a person; the code is for a caller that has to decide
    what kind of failure this is. REST reports the message and ignores the
    code; GraphQL maps the code to its error contract, so neither transport
    has to recognise a refusal by matching on English — the thing that breaks
    silently the first time somebody rewords a sentence.
    """
    return {"success": False, "code": code, "error": message}


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
        return None, _refuse("TENANT_REQUIRED", "Tenant context is required")
    student = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
    if not student:
        return None, _refuse("NOT_FOUND", "Student not found")
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

    if student.student_status in _ALREADY_GONE:
        return _refuse(
            "ALREADY_GONE",
            f"This student is already recorded as {student.student_status}",
        )

    left_class_id = student.class_id
    # Closes the current enrollment and clears students.class_id together, so
    # the cache and its owner cannot disagree.
    placement = assign_student_to_class(
        student_id, None, student.academic_year_id, commit=False
    )
    if not placement.get("success"):
        db.session.rollback()
        return _refuse(
            "PLACEMENT_FAILED",
            placement.get("error", "Could not end the student's placement"),
        )

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
        return _refuse("ALREADY_GONE", "This student has already graduated")

    completed_class_id = student.class_id
    placement = assign_student_to_class(
        student_id, None, student.academic_year_id, commit=False
    )
    if not placement.get("success"):
        db.session.rollback()
        return _refuse(
            "PLACEMENT_FAILED",
            placement.get("error", "Could not close the student's placement"),
        )

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

    # Where they are going is as branch-restricted as where they are: a campus
    # admin may not place a child into another campus's class. Asked here, so
    # it holds however the workflow was reached.
    assert_class_allowed(class_id)

    if student.student_status not in _ALREADY_GONE:
        return _refuse(
            "NOT_GONE", "Only a student who has left can be re-enrolled"
        )

    placement = assign_student_to_class(
        student_id, class_id, academic_year_id, commit=False
    )
    if not placement.get("success"):
        db.session.rollback()
        return _refuse(
            "PLACEMENT_FAILED",
            placement.get("error", "Could not place the returning student"),
        )

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



def transfer_section(
    student_id: str,
    *,
    to_class_id: str,
    occurred_on: Optional[datetime.date] = None,
    reason: Optional[str] = None,
    recorded_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A student moves to another section of the same year — 8A to 8B.

    Their enrollment is updated, not restarted: one year, one placement. The
    section they came from is kept by the event, because the enrollment now
    only says where they are.

    Not a status change. A student who moves rooms is still an active student
    of the school; `transferred` means they left it (see `transfer_out`).
    """
    from modules.classes.models import Class

    student, refusal = _student_for_workflow(student_id)
    if refusal:
        return refusal

    assert_class_allowed(to_class_id)

    destination = Class.query.filter_by(
        id=to_class_id, tenant_id=student.tenant_id
    ).first()
    if destination is None:
        return _refuse("CLASS_NOT_FOUND", "Class not found")
    if student.class_id == to_class_id:
        return _refuse("SAME_CLASS", "The student is already in this class")
    if (
        student.academic_year_id
        and destination.academic_year_id != student.academic_year_id
    ):
        # Moving a student across years is promotion (or a re-enrollment),
        # both of which do more than this and are asked for by name.
        return _refuse(
            "WRONG_YEAR",
            "That class belongs to another academic year. Use promotion or "
            "re-enrollment to move a student between years.",
        )

    from_class_id = student.class_id
    placement = assign_student_to_class(
        student_id, to_class_id, destination.academic_year_id, commit=False
    )
    if not placement.get("success"):
        db.session.rollback()
        return _refuse(
            "PLACEMENT_FAILED", placement.get("error", "Could not move the student")
        )

    record_event(
        student,
        EVENT_SECTION_TRANSFERRED,
        occurred_on=occurred_on,
        reason=reason,
        details={"from_class_id": from_class_id, "to_class_id": to_class_id},
        recorded_by_user_id=recorded_by_user_id,
    )
    db.session.commit()

    return {"success": True, "student": student.to_dict()}


def transfer_out(
    student_id: str,
    *,
    destination_school: Optional[str] = None,
    occurred_on: Optional[datetime.date] = None,
    reason: Optional[str] = None,
    recorded_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A student leaves this school for another one.

    Kept apart from withdrawal because the two are different facts about a
    child: one has gone somewhere, the other has stopped. Schools issue a
    transfer certificate for the first and want to be able to find it again.

    Like withdrawal, nothing is deleted — the student relationship and every
    past enrollment remain, so the record still answers who taught this
    child and when.
    """
    student, refusal = _student_for_workflow(student_id)
    if refusal:
        return refusal

    if student.student_status in _ALREADY_GONE:
        return _refuse(
            "ALREADY_GONE",
            f"This student is already recorded as {student.student_status}",
        )

    left_class_id = student.class_id
    placement = assign_student_to_class(
        student_id, None, student.academic_year_id, commit=False
    )
    if not placement.get("success"):
        db.session.rollback()
        return _refuse(
            "PLACEMENT_FAILED",
            placement.get("error", "Could not end the student's placement"),
        )

    student.student_status = STATUS_TRANSFERRED
    details = {"class_id": left_class_id} if left_class_id else {}
    if destination_school:
        details["destination_school"] = destination_school
    record_event(
        student,
        EVENT_TRANSFERRED_OUT,
        occurred_on=occurred_on,
        reason=reason,
        details=details or None,
        recorded_by_user_id=recorded_by_user_id,
    )
    db.session.commit()
    _refresh_billable_count(student.tenant_id)

    return {"success": True, "student": student.to_dict()}
