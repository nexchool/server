"""Teaching is an academic participation of employment (ADR-005)."""

from __future__ import annotations

import uuid
from datetime import date

from modules.auth.identity_service import ActiveContext, available_contexts
from modules.people.backfill import backfill_tenant
from modules.people.employment import EMPLOYMENT_STATUS_LEFT, Staff


def _add_user(db_session, tenant, name):
    from modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}",
        tenant_id=tenant.id,
        email=f"{suffix}@test.school",
        password_hash="x" * 60,
        name=name,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _add_teacher(db_session, tenant, user, *, status="active"):
    """A teacher, employed first — teaching is a participation of employment."""
    from modules.people.service import employ, employment_status_for_legacy_flag
    from modules.teachers.models import Teacher

    staff = employ(
        tenant.id,
        user.person_id,
        joined_on=date(2020, 6, 1),
        employment_status=employment_status_for_legacy_flag(status),
    )

    teacher = Teacher(
        id=f"t-{uuid.uuid4().hex[:8]}",
        tenant_id=tenant.id,
        user_id=user.id,
        staff_id=staff.id,
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


# ---------------------------------------------------------------------------
# Teaching hangs off employment
# ---------------------------------------------------------------------------

def test_teaching_is_attached_to_the_employment_it_belongs_to(db_session, tenant):
    user = _add_user(db_session, tenant, "Rohit Mehta")
    teacher = _add_teacher(db_session, tenant, user)

    backfill_tenant(tenant.id)

    staff = Staff.query.filter_by(person_id=user.person_id).one()
    assert teacher.staff_id == staff.id


def test_a_person_who_does_not_teach_has_no_teaching_record(db_session, tenant):
    from modules.teachers.models import Teacher

    user = _add_user(db_session, tenant, "Meera Shah")

    backfill_tenant(tenant.id)

    staff = Staff.query.filter_by(person_id=user.person_id).one()
    assert Teacher.query.filter_by(staff_id=staff.id).first() is None


def test_linking_teachers_twice_changes_nothing(db_session, tenant):
    user = _add_user(db_session, tenant, "Rohit Mehta")
    _add_teacher(db_session, tenant, user)

    backfill_tenant(tenant.id)
    second = backfill_tenant(tenant.id)

    assert second.teachers_linked == 0


# ---------------------------------------------------------------------------
# Contexts now come entirely from the People model
# ---------------------------------------------------------------------------

def test_a_teacher_holds_the_teacher_context(db_session, tenant):
    user = _add_user(db_session, tenant, "Rohit Mehta")
    _add_teacher(db_session, tenant, user)

    backfill_tenant(tenant.id)

    assert available_contexts(user) == [ActiveContext.TEACHER]


def test_a_non_teaching_employee_holds_the_staff_context(db_session, tenant):
    user = _add_user(db_session, tenant, "Meera Shah")

    backfill_tenant(tenant.id)

    assert available_contexts(user) == [ActiveContext.STAFF]


def test_a_student_holds_the_student_context(db_session, tenant):
    user = _add_user(db_session, tenant, "Aarav Patel")
    _add_student(db_session, tenant, user)

    backfill_tenant(tenant.id)

    assert available_contexts(user) == [ActiveContext.STUDENT]


def test_a_departed_teacher_keeps_no_experience(db_session, tenant):
    """Employment ended, so the teaching experience ends with it."""
    user = _add_user(db_session, tenant, "Former Teacher")
    _add_teacher(db_session, tenant, user, status="inactive")

    backfill_tenant(tenant.id)

    staff = Staff.query.filter_by(person_id=user.person_id).one()
    assert staff.employment_status == EMPLOYMENT_STATUS_LEFT
    assert available_contexts(user) == []


def test_an_account_with_no_person_has_no_experience(db_session, tenant):
    user = _add_user(db_session, tenant, "Unlinked")

    assert available_contexts(user) == []
