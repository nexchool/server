"""Who sees what on the academic calendar.

The matrix in `docs/architecture/specs/2026-09-15-mobile-academic-calendar.md`
§1, one test per row. These are authorization tests: a failure here is a
teacher reading another class's exam schedule, not a cosmetic defect.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def request_ctx(flask_app, tenant):
    """Calendar services read `g.tenant_id`, so they run inside a request."""
    from flask import g

    ctx = flask_app.test_request_context("/api/academics/calendar")
    ctx.push()
    g.tenant_id = tenant.id
    yield
    ctx.pop()


@pytest.fixture
def academic_year(db_session, tenant):
    """June 2026: Mon 1st … Tue 30th. Sundays 7/14/21/28, 2nd Sat 13, 4th 27.

    The same helper the calendar's own tests use, so the working-day
    arithmetic asserted here is the arithmetic asserted there.
    """
    from tests.test_academic_calendar import _make_year

    year = _make_year(db_session, tenant)
    year.is_active = True
    db_session.flush()
    return year


@pytest.fixture
def two_classes(db_session, tenant, academic_year):
    """Two classes in one tenant. The teacher below teaches the first."""
    from modules.classes.models import Class

    rows = [
        Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="Std 8", section="A",
            academic_year_id=academic_year.id,
        ),
        Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="Std 12", section="B",
            academic_year_id=academic_year.id,
        ),
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


def _a_teacher(db_session, tenant):
    """A Teacher row reached the way `teacher_for_user` reaches one.

    Account -> Person -> Staff -> Teacher (ADR-001/003/005). Setting
    `teachers.user_id` instead resolves to nobody — that column is a leftover
    from before the chain existed.
    """
    from modules.auth.models import User
    from modules.teachers.models import Teacher
    from tests.conftest import employ_for

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Teacher",
    )
    db_session.add(user)
    db_session.flush()
    staff = employ_for(user, employee_number=f"EMP-{suffix}")
    teacher = Teacher(id=_new_id("t-"), tenant_id=tenant.id, staff_id=staff.id)
    db_session.add(teacher)
    db_session.flush()
    return user, teacher


# ---------------------------------------------------------------------------
# "Their students" — both ways a teacher meets a class
# ---------------------------------------------------------------------------

def test_subject_teaching_counts_as_teaching_the_class(db_session, tenant, two_classes):
    """A subject teacher who is not the class teacher still teaches the class.

    `classes_taught_by` answers "class teacher of", which is the narrower
    question attendance asks. Reusing it here would have hidden a maths
    teacher's own exam window from them.
    """
    from modules.academics.backbone.models import ClassSubjectTeacher
    from modules.academics.teaching_assignment import class_ids_taught_by
    from modules.classes.models import ClassSubject
    from modules.subjects.models import Subject

    taught, other = two_classes
    _user, teacher = _a_teacher(db_session, tenant)

    subject = Subject(id=_new_id("s-"), tenant_id=tenant.id, name="Mathematics")
    db_session.add(subject)
    db_session.flush()
    offering = ClassSubject(
        id=_new_id("cs-"), tenant_id=tenant.id, class_id=taught.id,
        subject_id=subject.id, weekly_periods=5,
    )
    db_session.add(offering)
    db_session.flush()
    db_session.add(
        ClassSubjectTeacher(
            id=_new_id("cst-"), tenant_id=tenant.id, class_subject_id=offering.id,
            teacher_id=teacher.id, role="primary", is_active=True,
        )
    )
    db_session.flush()

    reached = class_ids_taught_by(teacher.id)

    assert taught.id in reached
    assert other.id not in reached


def test_class_teacher_duty_counts_too(db_session, tenant, two_classes):
    from modules.academics.backbone.models import ClassTeacherAssignment
    from modules.academics.teaching_assignment import class_ids_taught_by

    owned, other = two_classes
    _user, teacher = _a_teacher(db_session, tenant)

    db_session.add(
        ClassTeacherAssignment(
            id=_new_id("cta-"), tenant_id=tenant.id, class_id=owned.id,
            teacher_id=teacher.id, role="primary", is_active=True,
        )
    )
    db_session.flush()

    reached = class_ids_taught_by(teacher.id)

    assert reached == {owned.id}
    assert other.id not in reached


def _a_student(db_session, tenant, class_id):
    """An account with a studentship in `class_id`.

    `Student.person_id` is filled by the before_flush listener that attaches
    every arriving account and studentship to the person behind it, which is
    also the chain `student_for_user` walks.
    """
    from modules.auth.models import User
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Student",
    )
    db_session.add(user)
    db_session.flush()
    student = Student(
        id=_new_id("s-"), tenant_id=tenant.id, user_id=user.id,
        admission_number=f"ADM-{suffix}", class_id=class_id,
    )
    db_session.add(student)
    db_session.flush()
    return user, student


@pytest.fixture
def teaching_user(db_session, tenant, two_classes):
    """A signed-in teacher of the first of `two_classes`."""
    from modules.academics.backbone.models import ClassTeacherAssignment

    taught, _other = two_classes
    user, teacher = _a_teacher(db_session, tenant)
    db_session.add(
        ClassTeacherAssignment(
            id=_new_id("cta-"), tenant_id=tenant.id, class_id=taught.id,
            teacher_id=teacher.id, role="primary", is_active=True,
        )
    )
    db_session.flush()
    return user, taught.id


@pytest.fixture
def studying_user(db_session, tenant, two_classes):
    """A signed-in student of the first of `two_classes`."""
    own, _other = two_classes
    user, _student = _a_student(db_session, tenant, own.id)
    return user, own.id


# ---------------------------------------------------------------------------
# Resolving an audience
# ---------------------------------------------------------------------------

def test_manage_holder_is_unrestricted(db_session, tenant):
    """An admin sees the whole calendar — the shape admin-web has always had."""
    from modules.academics.calendar.audience import resolve_calendar_audience
    from tests.test_calendar_setup_graphql import _staff_with

    user, _token = _staff_with(db_session, tenant, "academic_calendar.manage")

    audience = resolve_calendar_audience(user)

    assert audience.unrestricted is True
    assert audience.class_ids is None


def test_office_staff_without_teaching_are_unrestricted(db_session, tenant):
    """A view-only sub-admin keeps the view they have on admin-web today.

    Narrowing keys on being a teacher or a student, not on lacking `manage` —
    otherwise this would silently take the calendar away from the office desk.
    """
    from modules.academics.calendar.audience import resolve_calendar_audience
    from tests.test_calendar_setup_graphql import _staff_with

    user, _token = _staff_with(db_session, tenant, "academic_calendar.read")

    audience = resolve_calendar_audience(user)

    assert audience.unrestricted is True


def test_teacher_is_scoped_to_the_classes_they_teach(
    db_session, tenant, two_classes, teaching_user
):
    from modules.academics.calendar.audience import resolve_calendar_audience

    user, taught_class_id = teaching_user

    audience = resolve_calendar_audience(user)

    assert audience.unrestricted is False
    assert audience.class_ids == {taught_class_id}
    assert audience.applies_to == {"entire_school", "students", "teachers", "staff"}


def test_student_is_scoped_to_their_class_and_hides_staff_audiences(
    db_session, tenant, two_classes, studying_user
):
    from modules.academics.calendar.audience import resolve_calendar_audience

    user, own_class_id = studying_user

    audience = resolve_calendar_audience(user)

    assert audience.unrestricted is False
    assert audience.class_ids == {own_class_id}
    assert audience.applies_to == {"entire_school", "students"}


def test_no_caller_is_entitled_to_nothing(db_session, tenant):
    """The permission classes reject this long before here.

    Answering "everything" would make them the only thing standing in the way.
    """
    from modules.academics.calendar.audience import resolve_calendar_audience

    audience = resolve_calendar_audience(user=None)

    assert audience.unrestricted is False
    assert audience.class_ids == frozenset()
    assert audience.applies_to == frozenset()


@pytest.fixture
def exams(db_session, tenant, academic_year, two_classes):
    """Three windows: one per class, and one for the whole school."""
    from modules.academics.calendar.models import ExamWindow

    taught, other = two_classes
    rows = [
        ExamWindow(
            id=_new_id("ew-"), tenant_id=tenant.id, academic_year_id=academic_year.id,
            name="Std 8 Unit Test", exam_type="unit_test", status="active",
            start_date=date(2026, 8, 3), end_date=date(2026, 8, 7),
            applicable_class_ids=[taught.id],
        ),
        ExamWindow(
            id=_new_id("ew-"), tenant_id=tenant.id, academic_year_id=academic_year.id,
            name="Std 12 Pre-Board", exam_type="pre_board", status="active",
            start_date=date(2026, 9, 1), end_date=date(2026, 9, 10),
            applicable_class_ids=[other.id],
        ),
        ExamWindow(
            id=_new_id("ew-"), tenant_id=tenant.id, academic_year_id=academic_year.id,
            name="Annual Exams", exam_type="final", status="active",
            start_date=date(2027, 2, 1), end_date=date(2027, 2, 20),
            applicable_class_ids=[],
        ),
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


def _names(rows):
    return {row.name for row in rows}


def test_teacher_sees_own_class_exam_and_the_whole_school_one_only(
    db_session, tenant, academic_year, exams, teaching_user, request_ctx
):
    from modules.academics.calendar.audience import resolve_calendar_audience
    from modules.academics.calendar.services import list_exam_windows

    user, _ = teaching_user
    audience = resolve_calendar_audience(user)

    seen = _names(list_exam_windows(academic_year.id, audience=audience))

    assert seen == {"Std 8 Unit Test", "Annual Exams"}
    assert "Std 12 Pre-Board" not in seen


def test_student_sees_only_their_own_class_exam(
    db_session, tenant, academic_year, exams, studying_user, request_ctx
):
    from modules.academics.calendar.audience import resolve_calendar_audience
    from modules.academics.calendar.services import list_exam_windows

    user, _ = studying_user
    audience = resolve_calendar_audience(user)

    seen = _names(list_exam_windows(academic_year.id, audience=audience))

    assert seen == {"Std 8 Unit Test", "Annual Exams"}


def test_admin_sees_every_exam_window(db_session, tenant, academic_year, exams, request_ctx):
    from modules.academics.calendar.audience import UNRESTRICTED
    from modules.academics.calendar.services import list_exam_windows

    seen = _names(list_exam_windows(academic_year.id, audience=UNRESTRICTED))

    assert len(seen) == 3


def test_student_does_not_see_a_staff_only_event(
    db_session, tenant, academic_year, studying_user, request_ctx
):
    from modules.academics.calendar.audience import resolve_calendar_audience
    from modules.academics.calendar.models import SchoolEvent
    from modules.academics.calendar.services import list_school_events

    db_session.add_all([
        SchoolEvent(
            id=_new_id("se-"), tenant_id=tenant.id, academic_year_id=academic_year.id,
            name="Staff Training", event_type="training", status="active",
            event_date=date(2026, 7, 10), applies_to="staff",
        ),
        SchoolEvent(
            id=_new_id("se-"), tenant_id=tenant.id, academic_year_id=academic_year.id,
            name="Sports Day", event_type="activity", status="active",
            event_date=date(2026, 12, 12), applies_to="entire_school",
        ),
    ])
    db_session.flush()

    user, _ = studying_user
    audience = resolve_calendar_audience(user)

    assert _names(list_school_events(academic_year.id, audience=audience)) == {"Sports Day"}


def test_teacher_does_see_a_student_facing_event(
    db_session, tenant, academic_year, teaching_user, request_ctx
):
    """A sports day is a teacher's working day too.

    Only exams are class-filtered for teachers; events are not.
    """
    from modules.academics.calendar.audience import resolve_calendar_audience
    from modules.academics.calendar.models import SchoolEvent
    from modules.academics.calendar.services import list_school_events

    db_session.add(
        SchoolEvent(
            id=_new_id("se-"), tenant_id=tenant.id, academic_year_id=academic_year.id,
            name="Sports Day", event_type="activity", status="active",
            event_date=date(2026, 12, 12), applies_to="students",
        )
    )
    db_session.flush()

    user, _ = teaching_user
    audience = resolve_calendar_audience(user)

    assert _names(list_school_events(academic_year.id, audience=audience)) == {"Sports Day"}


# ---------------------------------------------------------------------------
# The day feed and the summary answer the caller's question
# ---------------------------------------------------------------------------

def test_a_staff_only_holiday_is_a_working_day_for_a_student(
    db_session, tenant, academic_year, studying_user, request_ctx
):
    """The summary answers the caller's question, not the school's.

    A closure that applies only to staff does not close school for students,
    so it must not be subtracted from their working days.
    """
    from modules.academics.calendar import services
    from modules.academics.calendar.audience import UNRESTRICTED, resolve_calendar_audience
    from tests.test_academic_calendar import _add_holiday, _configured_calendar

    cal = _configured_calendar(services, academic_year)
    staff_day = _add_holiday(db_session, tenant, academic_year, "Staff Development", "2026-06-10")
    staff_day.applies_to = "staff"
    db_session.flush()

    user, _ = studying_user
    student_view = services.compute_summary(cal, audience=resolve_calendar_audience(user))
    school_view = services.compute_summary(cal, audience=UNRESTRICTED)

    assert school_view["public_holiday_days"] == 1
    assert student_view["public_holiday_days"] == 0
    assert student_view["working_days"] == school_view["working_days"] + 1


def test_the_day_feed_hides_another_class_exam_from_a_student(
    db_session, tenant, academic_year, two_classes, studying_user, request_ctx
):
    from modules.academics.calendar import services
    from modules.academics.calendar.audience import resolve_calendar_audience
    from tests.test_academic_calendar import _configured_calendar

    own, other = two_classes
    cal = _configured_calendar(services, academic_year)
    services.create_exam_window(
        academic_year.id,
        {"name": "Std 8 Unit Test", "start_date": "2026-06-08",
         "end_date": "2026-06-09", "applicable_class_ids": [own.id]},
    )
    services.create_exam_window(
        academic_year.id,
        {"name": "Std 12 Pre-Board", "start_date": "2026-06-22",
         "end_date": "2026-06-23", "applicable_class_ids": [other.id]},
    )

    user, _ = studying_user
    feed = {
        day["date"]: day
        for day in services.get_days_feed(cal, audience=resolve_calendar_audience(user))
    }

    assert feed["2026-06-08"]["has_exam"] is True     # their own class
    assert feed["2026-06-22"]["has_exam"] is False    # somebody else's


def test_a_weekly_off_reaches_every_audience(
    db_session, tenant, academic_year, studying_user, request_ctx
):
    """A weekly closure is the school's timetable, not an announcement.

    It has no `applies_to` to narrow by, and narrowing it would tell a student
    their school is open on a Sunday.
    """
    from modules.academics.calendar import services
    from modules.academics.calendar.audience import resolve_calendar_audience
    from tests.test_academic_calendar import _configured_calendar

    cal = _configured_calendar(services, academic_year)
    user, _ = studying_user

    feed = {
        day["date"]: day
        for day in services.get_days_feed(cal, audience=resolve_calendar_audience(user))
    }

    assert feed["2026-06-07"]["day_type"] == "weekly_holiday"   # Sunday
    assert feed["2026-06-27"]["day_type"] == "weekly_holiday"   # 4th Saturday
