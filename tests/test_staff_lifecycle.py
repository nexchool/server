"""Leaving the school, and coming back to it.

`end_reason` on a period held one word. These record the rest — which of
resignation, retirement or dismissal it was, on what date, for what stated
reason — because that is what a service letter is written from.

The case that matters most is the return: a teacher who comes back is the
same employee, with their first spell intact.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from modules.people.employment import (
    STAFF_EVENT_REJOINED,
    STAFF_EVENT_RESIGNED,
    STAFF_EVENT_RETIRED,
    Staff,
    StaffEmploymentPeriod,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _employed(db_session, tenant, name="Meera Joshi"):
    """Somebody working here, the way `employ()` leaves them."""
    from modules.people.models import Person
    from modules.people.service import employ

    person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name=name)
    db_session.add(person)
    db_session.flush()
    staff = employ(
        tenant.id,
        person.id,
        employee_number=f"EMP-{uuid.uuid4().hex[:6]}",
        designation="Senior Teacher",
        joined_on=date(2020, 6, 1),
    )
    db_session.flush()
    return staff


def _periods(staff_id):
    return StaffEmploymentPeriod.query.filter_by(staff_id=staff_id).all()


def _events(staff_id):
    from modules.people.separation import employment_timeline

    return [event.event for event in employment_timeline(staff_id)]


# ---------------------------------------------------------------------------
# Leaving
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "action,status,event",
    [
        ("resign", "resigned", STAFF_EVENT_RESIGNED),
        ("retire", "retired", STAFF_EVENT_RETIRED),
    ],
)
def test_leaving_closes_the_period_and_says_how(
    ctx, tenant, db_session, action, status, event
):
    from modules.people import separation

    staff = _employed(db_session, tenant)

    result = getattr(separation, action)(
        staff.id, last_working_day=date(2026, 5, 31), reason="Moving city"
    )
    assert result["success"], result

    db_session.refresh(staff)
    assert staff.employment_status == status

    period = _periods(staff.id)[0]
    assert period.left_on == date(2026, 5, 31)
    assert period.end_reason == status
    assert period.is_open is False

    from modules.people.separation import employment_timeline

    recorded = employment_timeline(staff.id)[-1]
    assert recorded.event == event
    assert recorded.reason == "Moving city"
    assert recorded.occurred_on == date(2026, 5, 31)


def test_resignation_and_retirement_are_told_apart(ctx, tenant, db_session):
    """A school's references, records and pensions treat them differently."""
    from modules.people import separation

    resigning = _employed(db_session, tenant, "Anil Kumar")
    retiring = _employed(db_session, tenant, "Sunita Rao")

    separation.resign(resigning.id)
    separation.retire(retiring.id)

    db_session.refresh(resigning)
    db_session.refresh(retiring)
    assert resigning.employment_status == "resigned"
    assert retiring.employment_status == "retired"
    assert _periods(resigning.id)[0].end_reason == "resigned"
    assert _periods(retiring.id)[0].end_reason == "retired"


def test_somebody_who_has_left_cannot_leave_again(ctx, tenant, db_session):
    from modules.people import separation

    staff = _employed(db_session, tenant)
    assert separation.resign(staff.id)["success"]

    again = separation.retire(staff.id)
    assert again["success"] is False
    assert "not currently employed" in again["error"].lower()


def test_notice_keeps_them_employed(ctx, tenant, db_session):
    """During notice a person still works here — the canon's middle step."""
    from modules.people import separation

    staff = _employed(db_session, tenant)

    result = separation.give_notice(staff.id, last_working_day=date(2026, 5, 31))
    assert result["success"], result

    db_session.refresh(staff)
    assert staff.employment_status == "notice_period"
    assert staff.is_employed is True
    # Still open — they have not gone yet.
    assert _periods(staff.id)[0].is_open is True


# ---------------------------------------------------------------------------
# Teaching stops when employment does
# ---------------------------------------------------------------------------

def test_leaving_ends_the_classes_they_were_answerable_for(
    ctx, tenant, db_session
):
    """The canon requires it, and a class whose teacher left must not read
    as staffed — nobody would be told to cover it."""
    from datetime import date as _d

    from modules.academics.academic_year.models import AcademicYear
    from modules.academics.backbone.models import ClassTeacherAssignment
    from modules.classes.models import Class
    from modules.people import separation
    from modules.teachers.models import Teacher

    staff = _employed(db_session, tenant)
    teacher = Teacher(id=_new_id("t-"), tenant_id=tenant.id, staff_id=staff.id)
    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=_d(2026, 6, 1), end_date=_d(2027, 3, 31),
    )
    db_session.add_all([teacher, year])
    db_session.flush()

    cls = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 6", section="A",
        academic_year_id=year.id, teacher_id=teacher.id,
    )
    db_session.add(cls)
    db_session.flush()
    db_session.add(
        ClassTeacherAssignment(
            id=_new_id("cta-"), tenant_id=tenant.id, class_id=cls.id,
            teacher_id=teacher.id, role="primary", is_active=True,
        )
    )
    db_session.flush()

    result = separation.resign(staff.id, last_working_day=_d(2026, 12, 31))
    assert result["success"], result
    assert result["on_leaving"]["teaching_ended"]["classes"] == 1

    held = ClassTeacherAssignment.query.filter_by(teacher_id=teacher.id).first()
    assert held.is_active is False
    assert held.effective_to == _d(2026, 12, 31)

    # The cache follows its owner: no class teacher, not a departed one.
    db_session.refresh(cls)
    assert cls.teacher_id is None


# ---------------------------------------------------------------------------
# Coming back
# ---------------------------------------------------------------------------

def test_returning_opens_a_second_period_not_a_second_employee(
    ctx, tenant, db_session
):
    """The canon: no new Person, no new Staff relationship, only a period."""
    from modules.people import separation

    staff = _employed(db_session, tenant)
    person_id = staff.person_id
    employee_number = staff.employee_number

    separation.resign(staff.id, last_working_day=date(2026, 5, 31))
    result = separation.rejoin(staff.id, joined_on=date(2028, 6, 1))
    assert result["success"], result

    db_session.refresh(staff)
    assert staff.employment_status == "working"
    assert staff.person_id == person_id
    assert staff.employee_number == employee_number
    # One employee, two spells.
    assert Staff.query.filter_by(person_id=person_id).count() == 1
    periods = sorted(_periods(staff.id), key=lambda p: p.joined_on)
    assert len(periods) == 2
    assert periods[0].left_on == date(2026, 5, 31)
    assert periods[0].end_reason == "resigned"
    assert periods[1].is_open is True


def test_the_first_spell_is_left_exactly_as_it_was(ctx, tenant, db_session):
    """History is not rewritten by somebody coming back."""
    from modules.people import separation

    staff = _employed(db_session, tenant)
    separation.retire(staff.id, last_working_day=date(2026, 5, 31), reason="Retired")
    separation.rejoin(staff.id, joined_on=date(2027, 6, 1))

    first = sorted(_periods(staff.id), key=lambda p: p.joined_on)[0]
    assert first.joined_on == date(2020, 6, 1)
    assert first.left_on == date(2026, 5, 31)
    assert first.end_reason == "retired"


def test_somebody_already_working_here_cannot_rejoin(ctx, tenant, db_session):
    from modules.people import separation

    staff = _employed(db_session, tenant)

    result = separation.rejoin(staff.id)
    assert result["success"] is False
    assert "already employed" in result["error"].lower()


def test_the_timeline_reads_as_a_career(ctx, tenant, db_session):
    from modules.people import separation

    staff = _employed(db_session, tenant)
    separation.resign(staff.id, last_working_day=date(2026, 5, 31))
    separation.rejoin(staff.id, joined_on=date(2028, 6, 1))
    separation.retire(staff.id, last_working_day=date(2030, 3, 31))

    assert _events(staff.id) == [
        STAFF_EVENT_RESIGNED,
        STAFF_EVENT_REJOINED,
        STAFF_EVENT_RETIRED,
    ]


def test_authority_ends_with_the_employment(ctx, tenant, db_session):
    """Already true by design (ADR-013) — pinned here because the separation
    workflows are now the thing that ends employment."""
    from modules.people import separation
    from modules.rbac.authority_service import (
        authority_profiles_for_person,
        grant_authority,
    )
    from modules.rbac.models import Role

    staff = _employed(db_session, tenant)
    role = Role(id=_new_id("r-"), tenant_id=tenant.id, name=f"Coordinator-{uuid.uuid4().hex[:4]}")
    db_session.add(role)
    db_session.flush()
    grant_authority(staff.id, role.id)
    assert authority_profiles_for_person(staff.person_id)

    separation.resign(staff.id)

    assert authority_profiles_for_person(staff.person_id) == []
