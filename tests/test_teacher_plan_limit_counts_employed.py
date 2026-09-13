"""The tenant's teacher seat limit counts teachers the school still employs.

It used to count every teacher row, so a teacher who resigned or retired
kept holding a seat against the licence. It now counts teachers whose
employment is current (modules.people.employment.EMPLOYED_STATUSES), the
same rule the teachers list uses for "currently employed".
"""

from __future__ import annotations

from datetime import date

import pytest

from modules.teachers import services
from tests.conftest import _new_id


def _teacher(db_session, tenant, *, number, employment_status):
    from modules.people.employment import Staff, StaffEmploymentPeriod
    from modules.people.models import Person
    from modules.teachers.models import Teacher

    person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name=f"T {number}",
                    phone_number="9800000000")
    db_session.add(person)
    db_session.flush()
    staff = Staff(id=_new_id("s-"), tenant_id=tenant.id, person=person,
                  employee_number=number, designation="Teacher",
                  employment_status=employment_status)
    db_session.add(staff)
    db_session.flush()
    gone = employment_status in {"resigned", "retired", "terminated", "left"}
    db_session.add(StaffEmploymentPeriod(
        id=_new_id("per-"), tenant_id=tenant.id, staff=staff, joined_on=date(2024, 6, 1),
        left_on=date(2025, 3, 31) if gone else None,
        end_reason=employment_status if gone else None,
    ))
    teacher = Teacher(id=_new_id("t-"), tenant_id=tenant.id, staff=staff)
    db_session.add(teacher)
    db_session.flush()
    return teacher


@pytest.fixture
def two_seat_plan(db_session, tenant):
    """A tenant licensed for two employed teachers — the limit lives on the tenant."""
    tenant.max_employed_teachers = 2
    db_session.flush()
    return tenant


def test_teachers_who_have_left_do_not_use_up_the_plan(db_session, tenant, two_seat_plan):
    _teacher(db_session, tenant, number="E1", employment_status="working")
    _teacher(db_session, tenant, number="E2", employment_status="resigned")
    _teacher(db_session, tenant, number="E3", employment_status="retired")

    allowed, message = services._check_teacher_plan_limit(tenant.id)
    assert allowed is True and message is None


def test_the_limit_still_bites_on_employed_teachers(db_session, tenant, two_seat_plan):
    _teacher(db_session, tenant, number="E1", employment_status="working")
    # On leave or on probation is still employed.
    _teacher(db_session, tenant, number="E2", employment_status="on_leave")

    allowed, message = services._check_teacher_plan_limit(tenant.id)
    assert allowed is False
    assert "2" in message


def test_headroom_is_seats_left_for_employed_teachers(db_session, tenant, two_seat_plan):
    _teacher(db_session, tenant, number="E1", employment_status="probation")
    _teacher(db_session, tenant, number="E2", employment_status="terminated")

    assert services.plan_teacher_headroom(tenant.id) == 1


def test_headroom_is_unlimited_without_a_plan(db_session, tenant):
    assert services.plan_teacher_headroom(tenant.id) is None
