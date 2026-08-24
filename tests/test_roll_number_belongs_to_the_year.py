"""A roll number is a position in a section for one year, not a property of a child.

The same student is 17 in Grade 10 and 42 in Grade 11. Reprinting the Grade 10
marksheet must still say 17 — and before migration 110 it said 42, because
`students.roll_number` was a single column and nothing recorded what it used to
be.

The enrollment holds the record. `students.roll_number` stays as a cache of the
**primary** enrollment, guarded here the same way `students.class_id` is.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import (
    ENROLLMENT_TYPE_PRIMARY,
    StudentClassEnrollment,
)
from modules.classes.models import Class
from modules.students.class_enrollment_service import (
    assign_student_to_class,
    enroll_additional,
    set_enrollment_roll_number,
    set_primary_roll_number,
)
from modules.students.models import Student


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _year(db_session, tenant, label, start, end):
    row = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id,
        name=f"{label}-{uuid.uuid4().hex[:6]}",
        start_date=start, end_date=end,
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def years(db_session, tenant):
    return {
        "2025": _year(db_session, tenant, "2025-26", date(2025, 6, 1), date(2026, 3, 31)),
        "2026": _year(db_session, tenant, "2026-27", date(2026, 6, 1), date(2027, 3, 31)),
    }


@pytest.fixture
def sections(db_session, tenant, years):
    made = {}
    for key, year in years.items():
        row = Class(
            id=_new_id("cl-"), tenant_id=tenant.id, section="A",
            name=f"Grade {key}", academic_year_id=year.id,
        )
        db_session.add(row)
        made[key] = row
    extra = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section="JEE",
        name="JEE Batch", academic_year_id=years["2026"].id,
    )
    db_session.add(extra)
    made["extra"] = extra
    db_session.flush()
    return made


@pytest.fixture
def student(db_session, tenant, years):
    from modules.people.models import Person

    person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name="Riya Patel")
    db_session.add(person)
    db_session.flush()
    row = Student(
        id=_new_id("s-"), tenant_id=tenant.id, person_id=person.id,
        admission_number=f"ADM{uuid.uuid4().hex[:8]}",
        academic_year_id=years["2025"].id,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _enrollments(student_id, tenant_id):
    return StudentClassEnrollment.query.filter_by(
        student_id=student_id, tenant_id=tenant_id
    ).all()


# ---------------------------------------------------------------------------
# The case the single column could not hold
# ---------------------------------------------------------------------------

def test_each_year_keeps_its_own_roll_number(
    ctx, db_session, tenant, student, sections
):
    assign_student_to_class(student.id, sections["2025"].id, commit=False)
    set_primary_roll_number(student.id, tenant.id, 17)
    db_session.flush()

    # Next year: new placement, new number.
    assign_student_to_class(student.id, sections["2026"].id, commit=False)
    set_primary_roll_number(student.id, tenant.id, 42)
    db_session.flush()

    by_class = {e.class_id: e.roll_number for e in _enrollments(student.id, tenant.id)}
    assert by_class[sections["2025"].id] == 17, "last year's roll number was rewritten"
    assert by_class[sections["2026"].id] == 42
    assert student.roll_number == 42


def test_changing_this_years_number_does_not_touch_last_years(
    ctx, db_session, tenant, student, sections
):
    assign_student_to_class(student.id, sections["2025"].id, commit=False)
    set_primary_roll_number(student.id, tenant.id, 17)
    db_session.flush()
    assign_student_to_class(student.id, sections["2026"].id, commit=False)
    db_session.flush()

    set_primary_roll_number(student.id, tenant.id, 5)
    set_primary_roll_number(student.id, tenant.id, 6)
    db_session.flush()

    historical = [
        e for e in _enrollments(student.id, tenant.id)
        if e.class_id == sections["2025"].id
    ][0]
    assert historical.roll_number == 17
    assert student.roll_number == 6


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------

def test_the_cache_agrees_with_the_primary_enrollment(
    ctx, db_session, tenant, student, sections
):
    assign_student_to_class(student.id, sections["2026"].id, commit=False)
    set_primary_roll_number(student.id, tenant.id, 12)
    db_session.flush()

    placement = StudentClassEnrollment.query.filter_by(
        student_id=student.id, tenant_id=tenant.id,
        is_current=True, enrollment_type=ENROLLMENT_TYPE_PRIMARY,
    ).first()
    assert student.roll_number == placement.roll_number == 12


def test_an_additional_enrollment_does_not_move_the_cache(
    ctx, db_session, tenant, student, sections
):
    """A vacation batch may number its own register. That is not the child's
    roll number in their class."""
    assign_student_to_class(student.id, sections["2026"].id, commit=False)
    set_primary_roll_number(student.id, tenant.id, 42)
    db_session.flush()

    joined = enroll_additional(
        tenant_id=tenant.id, student_id=student.id, class_id=sections["extra"].id
    )
    set_enrollment_roll_number(joined["enrollment_id"], tenant.id, 99)
    db_session.flush()

    assert student.roll_number == 42
    extra = StudentClassEnrollment.query.filter_by(
        id=joined["enrollment_id"]
    ).first()
    assert extra.roll_number == 99


def test_a_student_may_have_no_roll_number(ctx, db_session, tenant, student, sections):
    assign_student_to_class(student.id, sections["2026"].id, commit=False)
    db_session.flush()

    placement = StudentClassEnrollment.query.filter_by(
        student_id=student.id, tenant_id=tenant.id, is_current=True,
        enrollment_type=ENROLLMENT_TYPE_PRIMARY,
    ).first()
    assert student.roll_number is None
    assert placement.roll_number is None


def test_a_number_set_before_placement_reaches_the_enrollment(
    ctx, db_session, tenant, student, sections
):
    """Admission sets a roll number before the child is placed."""
    set_primary_roll_number(student.id, tenant.id, 7)
    db_session.flush()
    assert student.roll_number == 7

    assign_student_to_class(student.id, sections["2026"].id, commit=False)
    db_session.flush()

    placement = StudentClassEnrollment.query.filter_by(
        student_id=student.id, tenant_id=tenant.id, is_current=True,
        enrollment_type=ENROLLMENT_TYPE_PRIMARY,
    ).first()
    assert placement.roll_number == 7


def test_the_payload_still_carries_roll_number(ctx, db_session, tenant, student, sections):
    """Existing clients read `student.roll_number` and must keep working."""
    assign_student_to_class(student.id, sections["2026"].id, commit=False)
    set_primary_roll_number(student.id, tenant.id, 42)
    db_session.flush()

    assert student.to_dict()["roll_number"] == 42
