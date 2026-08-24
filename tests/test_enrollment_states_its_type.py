"""A student has one class and may attend several other things.

Regular Grade 11 Science + a 40-day vacation batch + JEE coaching is one child
with three current enrollments and one class. Before migration 109 the second
of those was refused by a partial unique index, which is what made coaching and
short courses unrepresentable.

The rule that survives is the one schools actually mean: **one academic
placement per student per year**, and `students.class_id` names it. Everything
else is `additional` and owns no cache.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy.exc import IntegrityError

from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import (
    ENROLLMENT_TYPE_ADDITIONAL,
    ENROLLMENT_TYPE_PRIMARY,
    StudentClassEnrollment,
)
from modules.classes.models import Class
from modules.students.class_enrollment_service import (
    additional_enrollments,
    assign_student_to_class,
    end_additional_enrollment,
    enroll_additional,
)
from modules.students.models import Student


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def academic_year(db_session, tenant):
    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(year)
    db_session.flush()
    return year


@pytest.fixture
def sections(db_session, tenant, academic_year):
    made = []
    for letter in ("A", "B", "JEE"):
        row = Class(
            id=_new_id("cl-"), tenant_id=tenant.id, section=letter,
            name=f"Grade 11 {letter}", academic_year_id=academic_year.id,
        )
        db_session.add(row)
        made.append(row)
    db_session.flush()
    return made


@pytest.fixture
def student(db_session, tenant, academic_year):
    from modules.people.models import Person

    person = Person(
        id=_new_id("p-"), tenant_id=tenant.id, full_name="Riya Patel",
    )
    db_session.add(person)
    db_session.flush()
    row = Student(
        id=_new_id("s-"), tenant_id=tenant.id, person_id=person.id,
        admission_number=f"ADM{uuid.uuid4().hex[:8]}",
        academic_year_id=academic_year.id,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _primary(student_id, tenant_id):
    return StudentClassEnrollment.query.filter_by(
        student_id=student_id, tenant_id=tenant_id,
        is_current=True, enrollment_type=ENROLLMENT_TYPE_PRIMARY,
    ).all()


# ---------------------------------------------------------------------------
# The rule that survives
# ---------------------------------------------------------------------------

def test_existing_enrollments_are_primary(ctx, db_session, tenant, student, sections):
    assign_student_to_class(student.id, sections[0].id, commit=False)
    db_session.flush()

    rows = _primary(student.id, tenant.id)
    assert len(rows) == 1
    assert rows[0].enrollment_type == ENROLLMENT_TYPE_PRIMARY


def test_a_second_primary_placement_in_one_year_is_refused(
    ctx, db_session, tenant, student, sections, academic_year
):
    assign_student_to_class(student.id, sections[0].id, commit=False)
    db_session.flush()

    db_session.begin_nested()
    db_session.add(
        StudentClassEnrollment(
            id=_new_id("en-"), tenant_id=tenant.id, student_id=student.id,
            class_id=sections[1].id, academic_year_id=academic_year.id,
            enrollment_status="active", enrollment_type=ENROLLMENT_TYPE_PRIMARY,
            is_current=True,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# ---------------------------------------------------------------------------
# What the index used to forbid
# ---------------------------------------------------------------------------

def test_a_student_may_attend_coaching_alongside_their_class(
    ctx, db_session, tenant, student, sections
):
    assign_student_to_class(student.id, sections[0].id, commit=False)
    db_session.flush()

    result = enroll_additional(
        tenant_id=tenant.id, student_id=student.id, class_id=sections[2].id
    )
    assert result["success"] is True

    extra = additional_enrollments(student.id, tenant.id)
    assert len(extra) == 1
    assert extra[0].class_id == sections[2].id


def test_several_additional_enrollments_are_allowed(
    ctx, db_session, tenant, student, sections
):
    """A vacation batch and coaching at once is not a conflict."""
    assign_student_to_class(student.id, sections[0].id, commit=False)
    db_session.flush()

    assert enroll_additional(
        tenant_id=tenant.id, student_id=student.id, class_id=sections[1].id
    )["success"]
    assert enroll_additional(
        tenant_id=tenant.id, student_id=student.id, class_id=sections[2].id
    )["success"]

    assert len(additional_enrollments(student.id, tenant.id)) == 2


def test_an_additional_enrollment_does_not_touch_the_class_cache(
    ctx, db_session, tenant, student, sections
):
    """This is the whole reason the type exists.

    `students.class_id` has 55 readers on the server and 694 across the
    clients. If coaching moved it, every one of them would start answering a
    different question.
    """
    assign_student_to_class(student.id, sections[0].id, commit=False)
    db_session.flush()
    assert student.class_id == sections[0].id

    enroll_additional(
        tenant_id=tenant.id, student_id=student.id, class_id=sections[2].id
    )
    db_session.flush()

    assert student.class_id == sections[0].id
    assert len(_primary(student.id, tenant.id)) == 1


def test_the_same_class_is_not_joined_twice(ctx, db_session, tenant, student, sections):
    assign_student_to_class(student.id, sections[0].id, commit=False)
    db_session.flush()

    first = enroll_additional(
        tenant_id=tenant.id, student_id=student.id, class_id=sections[2].id
    )
    second = enroll_additional(
        tenant_id=tenant.id, student_id=student.id, class_id=sections[2].id
    )
    assert first["success"] is True
    assert second["success"] is False


def test_ending_an_additional_enrollment_leaves_the_placement_alone(
    ctx, db_session, tenant, student, sections
):
    assign_student_to_class(student.id, sections[0].id, commit=False)
    db_session.flush()
    joined = enroll_additional(
        tenant_id=tenant.id, student_id=student.id, class_id=sections[2].id
    )

    ended = end_additional_enrollment(
        tenant_id=tenant.id, enrollment_id=joined["enrollment_id"]
    )
    assert ended["success"] is True
    assert additional_enrollments(student.id, tenant.id) == []
    assert student.class_id == sections[0].id
    assert len(_primary(student.id, tenant.id)) == 1


def test_the_academic_placement_cannot_be_ended_this_way(
    ctx, db_session, tenant, student, sections
):
    """Withdrawal, transfer and graduation are workflows, not a row edit."""
    assign_student_to_class(student.id, sections[0].id, commit=False)
    db_session.flush()
    placement = _primary(student.id, tenant.id)[0]

    result = end_additional_enrollment(
        tenant_id=tenant.id, enrollment_id=placement.id
    )
    assert result["success"] is False
    assert "workflow" in result["error"].lower()
