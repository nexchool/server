"""Two sections becoming one.

The point of these is what does NOT move. Attendance taken in 8B, marks
awarded there and reports issued from it happened in 8B — they stay there
when 8B merges into 8A, or the school loses the ability to answer where a
child was on a given day.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from modules.classes.models import Class


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


def _section(db_session, tenant, academic_year, label):
    cls = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 8", section=label,
        academic_year_id=academic_year.id,
    )
    db_session.add(cls)
    db_session.flush()
    return cls


def _child_in(db_session, tenant, academic_year, cls, name="Aarav Patel"):
    from modules.people.models import Person
    from modules.students.class_enrollment_service import assign_student_to_class
    from modules.students.models import Student

    person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name=name)
    db_session.add(person)
    db_session.flush()
    student = Student(
        id=_new_id("s-"), tenant_id=tenant.id, person_id=person.id,
        admission_number=f"ADM-{uuid.uuid4().hex[:6]}",
        academic_year_id=academic_year.id, class_id=cls.id, student_status="active",
    )
    db_session.add(student)
    db_session.flush()
    assign_student_to_class(student.id, cls.id, academic_year.id)
    return student


def _current_class_of(student_id):
    from modules.academics.backbone.models import StudentClassEnrollment

    row = StudentClassEnrollment.query.filter_by(
        student_id=student_id, is_current=True
    ).first()
    return row.class_id if row else None


# ---------------------------------------------------------------------------
# The children move
# ---------------------------------------------------------------------------

def test_merging_moves_everyone_into_the_surviving_section(
    ctx, tenant, db_session, academic_year
):
    from modules.classes.section_merge import merge_sections

    eight_a = _section(db_session, tenant, academic_year, "A")
    eight_b = _section(db_session, tenant, academic_year, "B")
    first = _child_in(db_session, tenant, academic_year, eight_b, "Riya")
    second = _child_in(db_session, tenant, academic_year, eight_b, "Kabir")

    result = merge_sections(eight_b.id, eight_a.id, occurred_on=date(2026, 9, 1))
    assert result["success"], result
    assert result["students_moved"] == 2

    assert _current_class_of(first.id) == eight_a.id
    assert _current_class_of(second.id) == eight_a.id


def test_the_merged_section_is_retired_not_deleted(
    ctx, tenant, db_session, academic_year
):
    """It still holds everything that happened in it."""
    from modules.classes.section_merge import merge_sections

    eight_a = _section(db_session, tenant, academic_year, "A")
    eight_b = _section(db_session, tenant, academic_year, "B")

    merge_sections(eight_b.id, eight_a.id, occurred_on=date(2026, 9, 1))

    db_session.refresh(eight_b)
    assert Class.query.filter_by(id=eight_b.id).first() is not None
    assert eight_b.is_merged_away is True
    assert eight_b.merged_into_class_id == eight_a.id
    assert eight_b.merged_on == date(2026, 9, 1)


# ---------------------------------------------------------------------------
# The history does not
# ---------------------------------------------------------------------------

def test_attendance_stays_with_the_section_it_was_taken_in(
    ctx, tenant, db_session, academic_year
):
    """The canon's requirement, and the reason a merge is not a rename."""
    from modules.academics.backbone.models import AttendanceRecord, AttendanceSession
    from modules.classes.section_merge import merge_sections

    eight_a = _section(db_session, tenant, academic_year, "A")
    eight_b = _section(db_session, tenant, academic_year, "B")
    child = _child_in(db_session, tenant, academic_year, eight_b)

    session = AttendanceSession(
        id=_new_id("as-"), tenant_id=tenant.id, class_id=eight_b.id,
        session_date=date(2026, 8, 20), status="finalized",
    )
    db_session.add(session)
    db_session.flush()
    record = AttendanceRecord(
        id=_new_id("ar-"), tenant_id=tenant.id, attendance_session_id=session.id,
        student_id=child.id, status="present",
    )
    db_session.add(record)
    db_session.flush()

    merge_sections(eight_b.id, eight_a.id, occurred_on=date(2026, 9, 1))

    # The register taken in 8B is still a register of 8B.
    db_session.refresh(session)
    assert session.class_id == eight_b.id
    db_session.refresh(record)
    assert record.attendance_session_id == session.id


def test_a_merged_section_can_still_be_found(ctx, tenant, db_session, academic_year):
    """Somebody asking why old attendance names a section nobody sits in."""
    from modules.classes.section_merge import merge_sections, merged_sections

    eight_a = _section(db_session, tenant, academic_year, "A")
    eight_b = _section(db_session, tenant, academic_year, "B")
    merge_sections(eight_b.id, eight_a.id)

    found = merged_sections(tenant.id, academic_year.id)
    assert [c.id for c in found] == [eight_b.id]


# ---------------------------------------------------------------------------
# Nothing new goes into it
# ---------------------------------------------------------------------------

def test_no_student_can_be_placed_into_a_merged_section(
    ctx, tenant, db_session, academic_year
):
    """One guard at the placement primitive covers admission, transfer,
    bulk import and promotion targets alike."""
    from modules.classes.section_merge import merge_sections
    from modules.students.class_enrollment_service import assign_student_to_class

    eight_a = _section(db_session, tenant, academic_year, "A")
    eight_b = _section(db_session, tenant, academic_year, "B")
    merge_sections(eight_b.id, eight_a.id)

    newcomer = _child_in(db_session, tenant, academic_year, eight_a, "Latecomer")
    result = assign_student_to_class(newcomer.id, eight_b.id, academic_year.id)

    assert result["success"] is False
    assert "merged" in result["error"].lower()


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_a_section_cannot_merge_into_itself(ctx, tenant, db_session, academic_year):
    from modules.classes.section_merge import merge_sections

    eight_a = _section(db_session, tenant, academic_year, "A")

    result = merge_sections(eight_a.id, eight_a.id)
    assert result["success"] is False


def test_merging_twice_is_refused(ctx, tenant, db_session, academic_year):
    from modules.classes.section_merge import merge_sections

    eight_a = _section(db_session, tenant, academic_year, "A")
    eight_b = _section(db_session, tenant, academic_year, "B")
    eight_c = _section(db_session, tenant, academic_year, "C")
    merge_sections(eight_b.id, eight_a.id)

    again = merge_sections(eight_b.id, eight_c.id)
    assert again["success"] is False
    assert "already been merged" in again["error"].lower()


def test_merging_into_a_section_that_itself_merged_is_refused(
    ctx, tenant, db_session, academic_year
):
    """Otherwise students land in a room nobody uses."""
    from modules.classes.section_merge import merge_sections

    eight_a = _section(db_session, tenant, academic_year, "A")
    eight_b = _section(db_session, tenant, academic_year, "B")
    eight_c = _section(db_session, tenant, academic_year, "C")
    merge_sections(eight_b.id, eight_a.id)

    result = merge_sections(eight_c.id, eight_b.id)
    assert result["success"] is False
    assert "surviving" in result["error"].lower()


def test_sections_of_different_years_cannot_be_merged(
    ctx, tenant, db_session, academic_year
):
    """Moving students between years is promotion, which decides more."""
    from modules.academics.academic_year.models import AcademicYear
    from modules.classes.section_merge import merge_sections

    eight_a = _section(db_session, tenant, academic_year, "A")
    next_year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2027, 6, 1), end_date=date(2028, 3, 31),
    )
    db_session.add(next_year)
    db_session.flush()
    next_section = _section(db_session, tenant, next_year, "A")

    result = merge_sections(next_section.id, eight_a.id)
    assert result["success"] is False
    assert "academic year" in result["error"].lower()
