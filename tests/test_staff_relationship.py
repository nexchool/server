"""The Staff relationship and employment periods (ADR-001, ADR-005)."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from modules.people.backfill import backfill_tenant
from modules.people.employment import (
    EMPLOYMENT_STATUS_LEFT,
    EMPLOYMENT_STATUS_ON_LEAVE,
    EMPLOYMENT_STATUS_RESIGNED,
    EMPLOYMENT_STATUS_WORKING,
    Staff,
    StaffEmploymentPeriod,
)


def _add_user(db_session, tenant, *, name, is_platform_admin=False):
    from modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}",
        tenant_id=tenant.id,
        email=f"{suffix}@test.school",
        password_hash="x" * 60,
        name=name,
        is_platform_admin=is_platform_admin,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _add_teacher(db_session, tenant, user, *, status="active", joined=None, employee_id=None):
    from modules.teachers.models import Teacher

    teacher = Teacher(
        id=f"t-{uuid.uuid4().hex[:8]}",
        tenant_id=tenant.id,
        user_id=user.id,
        employee_id=employee_id or f"EMP-{uuid.uuid4().hex[:6]}",
        status=status,
        date_of_joining=joined,
        designation="Senior Teacher",
    )
    db_session.add(teacher)
    db_session.flush()
    return teacher


def _add_student(db_session, tenant, user):
    from modules.students.models import Student

    student = Student(
        id=f"s-{uuid.uuid4().hex[:8]}",
        tenant_id=tenant.id,
        user_id=user.id,
        admission_number=f"ADM-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(student)
    db_session.flush()
    return student


def _staff_for(user):
    return Staff.query.filter_by(person_id=user.person_id).first()


# ---------------------------------------------------------------------------
# Who becomes staff
# ---------------------------------------------------------------------------

def test_a_teacher_becomes_staff_carrying_their_employment_detail(db_session, tenant):
    user = _add_user(db_session, tenant, name="Rohit Mehta")
    _add_teacher(db_session, tenant, user, joined=date(2019, 6, 1), employee_id="EMP-77")

    backfill_tenant(tenant.id)

    staff = _staff_for(user)
    assert staff.employee_number == "EMP-77"
    assert staff.designation == "Senior Teacher"
    assert staff.employment_status == EMPLOYMENT_STATUS_WORKING

    period = StaffEmploymentPeriod.query.filter_by(staff_id=staff.id).one()
    assert period.joined_on == date(2019, 6, 1)
    assert period.is_open


def test_an_administrator_is_staff_even_though_v1_recorded_no_employment(
    db_session, tenant
):
    """A receptionist is employed just as a teacher is; v1 simply never said so."""
    user = _add_user(db_session, tenant, name="Meera Shah")

    backfill_tenant(tenant.id)

    staff = _staff_for(user)
    assert staff is not None
    assert staff.employment_status == EMPLOYMENT_STATUS_WORKING
    assert staff.employee_number is None


def test_a_student_does_not_become_staff(db_session, tenant):
    user = _add_user(db_session, tenant, name="Aarav Patel")
    _add_student(db_session, tenant, user)

    backfill_tenant(tenant.id)

    assert _staff_for(user) is None


def test_a_platform_administrator_is_not_employed_by_the_school(db_session, tenant):
    user = _add_user(db_session, tenant, name="Nexchool Support", is_platform_admin=True)

    backfill_tenant(tenant.id)

    assert _staff_for(user) is None


# ---------------------------------------------------------------------------
# Translating the v1 status flag
# ---------------------------------------------------------------------------

def test_a_departed_teacher_is_recorded_as_left_rather_than_a_guessed_reason(
    db_session, tenant
):
    """v1 knew only 'inactive'. Claiming they resigned would invent a fact."""
    user = _add_user(db_session, tenant, name="Former Teacher")
    _add_teacher(db_session, tenant, user, status="inactive", joined=date(2015, 4, 1))

    backfill_tenant(tenant.id)

    staff = _staff_for(user)
    assert staff.employment_status == EMPLOYMENT_STATUS_LEFT
    assert not staff.is_employed

    period = StaffEmploymentPeriod.query.filter_by(staff_id=staff.id).one()
    assert period.end_reason == EMPLOYMENT_STATUS_LEFT
    assert not period.is_open


def test_a_period_that_ended_without_a_recorded_date_is_not_open(db_session, tenant):
    period = StaffEmploymentPeriod(
        tenant_id=tenant.id, staff_id="whatever", end_reason=EMPLOYMENT_STATUS_RESIGNED
    )

    assert period.left_on is None
    assert not period.is_open


# ---------------------------------------------------------------------------
# Status and type are independent
# ---------------------------------------------------------------------------

def test_a_permanent_employee_can_be_on_leave(db_session, tenant):
    """The dimension that made the v1 model unable to express this."""
    from modules.people.employment import EMPLOYMENT_TYPE_PERMANENT
    from modules.people.models import Person

    person = Person(tenant_id=tenant.id, full_name="Anita Desai")
    db_session.add(person)
    db_session.flush()

    staff = Staff(
        tenant_id=tenant.id,
        person_id=person.id,
        employment_status=EMPLOYMENT_STATUS_ON_LEAVE,
        employment_type=EMPLOYMENT_TYPE_PERMANENT,
    )
    db_session.add(staff)
    db_session.flush()

    assert staff.employment_status == EMPLOYMENT_STATUS_ON_LEAVE
    assert staff.employment_type == EMPLOYMENT_TYPE_PERMANENT
    assert staff.is_employed


def test_an_unknown_employment_status_is_rejected_by_the_database(db_session, tenant):
    from sqlalchemy.exc import IntegrityError

    from modules.people.models import Person

    person = Person(tenant_id=tenant.id, full_name="Someone")
    db_session.add(person)
    db_session.flush()

    # The violation is contained in its own savepoint. Letting it reach the
    # transaction this test runs inside would roll back the fixture's savepoint
    # and break whichever test happens to run next.
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                Staff(
                    tenant_id=tenant.id,
                    person_id=person.id,
                    employment_status="vibing",
                )
            )

    # The session is still usable, which is the point of the savepoint.
    assert Person.query.get(person.id) is not None


# ---------------------------------------------------------------------------
# Repeatability
# ---------------------------------------------------------------------------

def test_running_the_backfill_twice_creates_one_staff_relationship(db_session, tenant):
    user = _add_user(db_session, tenant, name="Rohit Mehta")
    _add_teacher(db_session, tenant, user)

    backfill_tenant(tenant.id)
    second = backfill_tenant(tenant.id)

    assert second.staff_created == 0
    assert Staff.query.filter_by(person_id=user.person_id).count() == 1


def test_students_are_linked_to_their_person(db_session, tenant):
    user = _add_user(db_session, tenant, name="Aarav Patel")
    student = _add_student(db_session, tenant, user)

    backfill_tenant(tenant.id)

    assert student.person_id == user.person_id
