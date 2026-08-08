"""What happens to a student, and what the school can still find out afterwards.

Before these workflows existed, a student's status was a field anyone could
set. Nothing recorded when a child left or why, a graduate went on being
billed because promotion never changed their status, and the billing code
excluded a value — `withdrawn` — that nothing could write.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from modules.students.models import (
    EVENT_GRADUATED,
    EVENT_RE_ENROLLED,
    EVENT_WITHDRAWN,
    Student,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    db_session.add(year)
    db_session.flush()
    return year


@pytest.fixture
def klass(db_session, tenant, academic_year):
    from modules.classes.models import Class

    cls = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 5", section="A",
        academic_year_id=academic_year.id,
    )
    db_session.add(cls)
    db_session.flush()
    return cls


def _admit(db_session, tenant, academic_year, klass=None):
    """A student placed in a class, the way admission leaves them."""
    from modules.people.models import Person

    person = Person(
        id=_new_id("p-"), tenant_id=tenant.id, full_name="Aarav Patel"
    )
    db_session.add(person)
    db_session.flush()
    student = Student(
        id=_new_id("s-"),
        tenant_id=tenant.id,
        person_id=person.id,
        admission_number=f"ADM-{uuid.uuid4().hex[:6]}",
        academic_year_id=academic_year.id,
        class_id=klass.id if klass else None,
        student_status="active",
    )
    db_session.add(student)
    db_session.flush()
    if klass is not None:
        from modules.students.class_enrollment_service import assign_student_to_class

        assign_student_to_class(student.id, klass.id, academic_year.id)
    return student


def _events(student_id):
    from modules.students.lifecycle_service import timeline_for

    return [event.event for event in timeline_for(student_id)]


def _current_enrollment(student_id):
    from modules.academics.backbone.models import StudentClassEnrollment

    return StudentClassEnrollment.query.filter_by(
        student_id=student_id, is_current=True
    ).first()


# ---------------------------------------------------------------------------
# Withdrawal
# ---------------------------------------------------------------------------

def test_withdrawing_ends_the_placement_and_says_why(
    ctx, tenant, db_session, academic_year, klass
):
    from modules.students.lifecycle_service import withdraw_student

    student = _admit(db_session, tenant, academic_year, klass)

    result = withdraw_student(
        student.id, reason="Family relocating", occurred_on=date(2026, 9, 1)
    )
    assert result["success"], result

    db_session.refresh(student)
    assert student.student_status == "withdrawn"
    # The place in a class is gone, and the cache agrees with its owner.
    assert student.class_id is None
    assert _current_enrollment(student.id) is None

    from modules.students.lifecycle_service import timeline_for

    recorded = timeline_for(student.id)[-1]
    assert recorded.event == EVENT_WITHDRAWN
    assert recorded.reason == "Family relocating"
    assert recorded.occurred_on == date(2026, 9, 1)


def test_withdrawal_keeps_the_student(ctx, tenant, db_session, academic_year, klass):
    """Never delete: a child who leaves may be back next year."""
    from modules.students.lifecycle_service import withdraw_student

    student = _admit(db_session, tenant, academic_year, klass)
    admission_number = student.admission_number

    withdraw_student(student.id)

    still_there = Student.query.filter_by(id=student.id).first()
    assert still_there is not None
    assert still_there.admission_number == admission_number
    assert still_there.person_id is not None


def test_a_student_cannot_leave_twice(ctx, tenant, db_session, academic_year, klass):
    from modules.students.lifecycle_service import withdraw_student

    student = _admit(db_session, tenant, academic_year, klass)
    assert withdraw_student(student.id)["success"]

    again = withdraw_student(student.id)
    assert again["success"] is False
    assert "already" in again["error"].lower()


# ---------------------------------------------------------------------------
# Graduation
# ---------------------------------------------------------------------------

def test_graduating_leaves_no_current_enrollment(
    ctx, tenant, db_session, academic_year, klass
):
    """Other modules read that absence — transport's rollover skips graduates."""
    from modules.students.lifecycle_service import graduate_student

    student = _admit(db_session, tenant, academic_year, klass)

    assert graduate_student(student.id)["success"]

    db_session.refresh(student)
    assert student.student_status == "graduated"
    assert student.class_id is None
    assert _current_enrollment(student.id) is None
    assert EVENT_GRADUATED in _events(student.id)


def test_a_graduate_stops_being_billed(ctx, tenant, db_session, academic_year, klass):
    """The defect this closes: promotion graduated students and left them active."""
    from modules.students.lifecycle_service import graduate_student
    from modules.subscription.usage import INACTIVE_STUDENT_STATUSES

    student = _admit(db_session, tenant, academic_year, klass)
    graduate_student(student.id)

    db_session.refresh(student)
    assert student.student_status in INACTIVE_STUDENT_STATUSES


# ---------------------------------------------------------------------------
# Return
# ---------------------------------------------------------------------------

def test_a_returning_student_is_not_admitted_again(
    ctx, tenant, db_session, academic_year, klass
):
    """The same child: same person, same studentship, same admission number."""
    from modules.students.lifecycle_service import reenroll_student, withdraw_student

    student = _admit(db_session, tenant, academic_year, klass)
    admission_number = student.admission_number
    person_id = student.person_id

    withdraw_student(student.id)
    result = reenroll_student(student.id, class_id=klass.id)
    assert result["success"], result

    db_session.refresh(student)
    assert student.student_status == "active"
    assert student.admission_number == admission_number
    assert student.person_id == person_id
    # Back in a class, with a fresh enrollment.
    assert _current_enrollment(student.id) is not None
    assert Student.query.filter_by(person_id=person_id).count() == 1


def test_only_someone_who_left_can_return(
    ctx, tenant, db_session, academic_year, klass
):
    from modules.students.lifecycle_service import reenroll_student

    student = _admit(db_session, tenant, academic_year, klass)

    result = reenroll_student(student.id, class_id=klass.id)
    assert result["success"] is False


def test_the_timeline_reads_as_a_story(ctx, tenant, db_session, academic_year, klass):
    from modules.students.lifecycle_service import reenroll_student, withdraw_student

    student = _admit(db_session, tenant, academic_year, klass)
    withdraw_student(student.id, occurred_on=date(2026, 9, 1))
    reenroll_student(student.id, class_id=klass.id, occurred_on=date(2027, 6, 1))

    assert _events(student.id) == [EVENT_WITHDRAWN, EVENT_RE_ENROLLED]


# ---------------------------------------------------------------------------
# Status is workflow-driven
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["withdrawn", "graduated", "transferred"])
def test_an_edit_cannot_set_a_lifecycle_outcome(
    ctx, tenant, db_session, academic_year, klass, status
):
    """Setting the word alone would leave the placement and the record undone."""
    from modules.students.services import update_student

    student = _admit(db_session, tenant, academic_year, klass)

    result = update_student(student.id, student_status=status)
    assert result["success"] is False
    assert "workflow" in result["error"].lower()

    db_session.refresh(student)
    assert student.student_status == "active"


@pytest.mark.parametrize("status", ["withdrawn", "graduated", "transferred"])
def test_a_bulk_edit_cannot_set_a_lifecycle_outcome(
    ctx, tenant, db_session, academic_year, klass, status
):
    from modules.students.services import bulk_update_status

    student = _admit(db_session, tenant, academic_year, klass)

    result = bulk_update_status([student.id], status)
    assert result["success"] is False
    assert "workflow" in result["error"].lower()


def test_a_cohort_can_still_be_marked_as_leaving(
    ctx, tenant, db_session, academic_year, klass
):
    """`leaving` is a marker, not an outcome — bulk is the right tool for it."""
    from modules.students.services import bulk_update_status

    first = _admit(db_session, tenant, academic_year, klass)
    second = _admit(db_session, tenant, academic_year, klass)

    result = bulk_update_status([first.id, second.id], "leaving")
    assert result["success"], result
    assert result["updated"] == 2
