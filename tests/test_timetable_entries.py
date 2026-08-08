"""A teacher cannot be in two classrooms at once.

The rule was enforced by the parallel `timetable_slots` API, which migration
096 deleted. It is enforced here too — and better, because this comparison
reads clock times, so two classes on different bell schedules whose periods
overlap are caught, which period-number equality could never see.

These tests exist because that enforcement had no coverage of its own: the
tests that guarded it were written against the implementation that is gone.
"""

from __future__ import annotations

import uuid
from datetime import date, time

import pytest
from flask import g

from modules.academics.backbone.models import (
    BellSchedule,
    BellSchedulePeriod,
    ClassSubjectTeacher,
    TimetableVersion,
)
from modules.academics.services import timetable_v2
from modules.auth.models import User
from modules.classes.models import Class, ClassSubject
from modules.subjects.models import Subject
from modules.teachers.models import Teacher


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
def bell_schedule(db_session, tenant, academic_year):
    """Two lesson periods, so "a different period" is expressible."""
    schedule = BellSchedule(
        id=_new_id("bs-"), tenant_id=tenant.id, name="Standard",
        academic_year_id=academic_year.id, is_default=True,
    )
    db_session.add(schedule)
    db_session.flush()
    db_session.add_all([
        BellSchedulePeriod(
            id=_new_id("bsp-"), tenant_id=tenant.id, bell_schedule_id=schedule.id,
            period_number=1, period_kind="lesson",
            starts_at=time(8, 0), ends_at=time(8, 45), sort_order=1,
        ),
        BellSchedulePeriod(
            id=_new_id("bsp-"), tenant_id=tenant.id, bell_schedule_id=schedule.id,
            period_number=2, period_kind="lesson",
            starts_at=time(8, 45), ends_at=time(9, 30), sort_order=2,
        ),
    ])
    db_session.flush()
    return schedule


def _teacher(db_session, tenant):
    from tests.conftest import employ_for

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=_new_id("u-"), tenant_id=tenant.id, email=f"t-{suffix}@test.school",
        password_hash="x" * 60, name=f"Teacher {suffix}",
    )
    db_session.add(user)
    db_session.flush()
    teacher = Teacher(
        id=_new_id("t-"), tenant_id=tenant.id, user_id=user.id,
        staff_id=employ_for(user, employee_number=f"EMP-{suffix}").id,
    )
    db_session.add(teacher)
    db_session.flush()
    return teacher


def _class_with_subject(db_session, tenant, academic_year, bell_schedule, teacher, section):
    """A class carrying one taught subject and one DRAFT timetable version."""
    cls = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 7", section=section,
        academic_year_id=academic_year.id,
    )
    subject = Subject(
        id=_new_id("sub-"), tenant_id=tenant.id, name=f"Maths {section}",
        code=f"M{section}{uuid.uuid4().hex[:4]}",
    )
    db_session.add_all([cls, subject])
    db_session.flush()

    class_subject = ClassSubject(
        id=_new_id("cs-"), tenant_id=tenant.id, class_id=cls.id,
        subject_id=subject.id, status="active", weekly_periods=5,
    )
    db_session.add(class_subject)
    db_session.flush()

    db_session.add(
        ClassSubjectTeacher(
            id=_new_id("cst-"), tenant_id=tenant.id,
            class_subject_id=class_subject.id, teacher_id=teacher.id,
            role="primary", is_active=True,
        )
    )
    version = TimetableVersion(
        id=_new_id("tv-"), tenant_id=tenant.id, class_id=cls.id,
        bell_schedule_id=bell_schedule.id, status="draft",
    )
    db_session.add(version)
    db_session.flush()
    return cls, class_subject, version


def _place(cls, class_subject, version, teacher, *, period):
    return timetable_v2.create_entry(
        cls.tenant_id,
        cls.id,
        {
            "timetable_version_id": version.id,
            "class_subject_id": class_subject.id,
            "teacher_id": teacher.id,
            "day_of_week": 1,  # ISO Monday
            "period_number": period,
        },
    )


def test_a_teacher_cannot_be_placed_in_two_classes_at_once(
    ctx, tenant, db_session, academic_year, bell_schedule
):
    teacher = _teacher(db_session, tenant)
    class_a = _class_with_subject(db_session, tenant, academic_year, bell_schedule, teacher, "A")
    class_b = _class_with_subject(db_session, tenant, academic_year, bell_schedule, teacher, "B")

    first = _place(*class_a, teacher, period=1)
    assert first["success"] is True, first

    second = _place(*class_b, teacher, period=1)
    assert second["success"] is False
    assert "already scheduled" in second["error"].lower()


def test_the_same_teacher_may_take_a_different_period(
    ctx, tenant, db_session, academic_year, bell_schedule
):
    teacher = _teacher(db_session, tenant)
    class_a = _class_with_subject(db_session, tenant, academic_year, bell_schedule, teacher, "A")
    class_b = _class_with_subject(db_session, tenant, academic_year, bell_schedule, teacher, "B")

    assert _place(*class_a, teacher, period=1)["success"] is True
    assert _place(*class_b, teacher, period=2)["success"] is True


def test_reassigning_an_entry_cannot_double_book_either(
    ctx, tenant, db_session, academic_year, bell_schedule
):
    """The edit path must refuse what the create path refuses."""
    busy = _teacher(db_session, tenant)
    free = _teacher(db_session, tenant)
    class_a = _class_with_subject(db_session, tenant, academic_year, bell_schedule, busy, "A")
    cls_b, class_subject_b, version_b = _class_with_subject(
        db_session, tenant, academic_year, bell_schedule, free, "B"
    )
    # `busy` may teach class B's subject too — otherwise the edit would be
    # refused for the wrong reason.
    db_session.add(
        ClassSubjectTeacher(
            id=_new_id("cst-"), tenant_id=tenant.id,
            class_subject_id=class_subject_b.id, teacher_id=busy.id,
            role="assistant", is_active=True,
        )
    )
    db_session.flush()

    assert _place(*class_a, busy, period=1)["success"] is True
    placed_b = _place(cls_b, class_subject_b, version_b, free, period=1)
    assert placed_b["success"] is True

    moved = timetable_v2.update_entry(
        tenant.id, cls_b.id, placed_b["entry"]["id"], {"teacher_id": busy.id}
    )
    assert moved["success"] is False
    assert "already scheduled" in moved["error"].lower()
