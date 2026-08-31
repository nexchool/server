"""The dashboard counted rows by loading them and looping in Python.

`_alerts` runs on every admin page load and computes the "issues" tiles. Two of
its counts were the wrong shape at any real size, and both are transport:

  * **students on inactive routes** pulled *every active enrolment's route_id*
    into a Python list — several thousand rows on a trust that buses its
    students — and then counted the ones whose route was not active by walking
    that list.

  * **buses near capacity** ran a `COUNT(*)` **inside a loop over the buses**.
    Forty buses meant forty round trips, on a page that is loaded constantly.

The rest of the function does the same thing on smaller sets (class ids,
class-subject ids), which is tolerable at a few hundred rows but is the same
mistake, so it moves to SQL too.

These tests pin the counts first — the point is that the numbers do not change
— and then pin the cost, which is what actually needed fixing.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy import event

from core.database import db
from modules.dashboard import service as dashboard


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id,
        name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(ay)
    db_session.flush()
    return ay


def _student(db_session, tenant):
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:10]
    person = Person(id=f"pe-{suffix}", tenant_id=tenant.id, full_name="Rider")
    db_session.add(person)
    db_session.flush()
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"{suffix}@test.school", password_hash="x" * 60,
                name="Rider", person_id=person.id)
    db_session.add(user)
    db_session.flush()
    student = Student(id=f"s-{suffix}", tenant_id=tenant.id, user_id=user.id,
                      person_id=person.id, admission_number=f"A-{suffix[:8]}")
    db_session.add(student)
    db_session.flush()
    return student


def _route(db_session, tenant, *, status="active"):
    from modules.transport.models import TransportRoute

    route = TransportRoute(id=_new_id("rt-"), tenant_id=tenant.id,
                           name=f"Route {uuid.uuid4().hex[:5]}", status=status)
    db_session.add(route)
    db_session.flush()
    return route


def _bus(db_session, tenant, *, capacity=10, status="active"):
    from modules.transport.models import TransportBus

    bus = TransportBus(id=_new_id("bs-"), tenant_id=tenant.id,
                       bus_number=f"B{uuid.uuid4().hex[:5]}",
                       capacity=capacity, status=status)
    db_session.add(bus)
    db_session.flush()
    return bus


def _enrol(db_session, tenant, year, bus, route, *, status="active"):
    from modules.transport.models import TransportEnrollment

    enrolment = TransportEnrollment(
        id=_new_id("te-"), tenant_id=tenant.id,
        student_id=_student(db_session, tenant).id,
        academic_year_id=year.id, bus_id=bus.id, route_id=route.id,
        status=status, monthly_fee=500, start_date=date(2026, 6, 1),
    )
    db_session.add(enrolment)
    db_session.flush()
    return enrolment


def _alerts(tenant):
    return dashboard._alerts(tenant.id, True, finance_enabled=False)


# ---------------------------------------------------------------------------
# The numbers must not change
# ---------------------------------------------------------------------------

def test_students_on_an_inactive_route_are_counted(ctx, db_session, tenant, year):
    live = _route(db_session, tenant, status="active")
    retired = _route(db_session, tenant, status="inactive")
    bus = _bus(db_session, tenant, capacity=100)

    _enrol(db_session, tenant, year, bus, live)
    _enrol(db_session, tenant, year, bus, retired)
    _enrol(db_session, tenant, year, bus, retired)

    assert _alerts(tenant)["transport_issues"] == 2


def test_a_cancelled_enrolment_is_not_an_issue(ctx, db_session, tenant, year):
    retired = _route(db_session, tenant, status="inactive")
    bus = _bus(db_session, tenant, capacity=100)
    _enrol(db_session, tenant, year, bus, retired, status="cancelled")

    assert _alerts(tenant)["transport_issues"] == 0


def test_a_bus_at_eighty_five_percent_is_near_capacity(ctx, db_session, tenant, year):
    live = _route(db_session, tenant, status="active")
    full = _bus(db_session, tenant, capacity=10)
    for _ in range(9):                       # 90%
        _enrol(db_session, tenant, year, full, live)

    assert _alerts(tenant)["transport_issues"] == 1


def test_a_bus_below_the_threshold_is_not_flagged(ctx, db_session, tenant, year):
    live = _route(db_session, tenant, status="active")
    roomy = _bus(db_session, tenant, capacity=10)
    for _ in range(5):                       # 50%
        _enrol(db_session, tenant, year, roomy, live)

    assert _alerts(tenant)["transport_issues"] == 0


def test_a_bus_with_no_stated_capacity_is_skipped(ctx, db_session, tenant, year):
    """Dividing by a zero capacity would be a crash, not a full bus."""
    live = _route(db_session, tenant, status="active")
    unknown = _bus(db_session, tenant, capacity=0)
    for _ in range(5):
        _enrol(db_session, tenant, year, unknown, live)

    assert _alerts(tenant)["transport_issues"] == 0


def test_an_inactive_bus_is_not_flagged(ctx, db_session, tenant, year):
    live = _route(db_session, tenant, status="active")
    parked = _bus(db_session, tenant, capacity=10, status="retired")
    for _ in range(10):
        _enrol(db_session, tenant, year, parked, live)

    assert _alerts(tenant)["transport_issues"] == 0


def test_an_empty_bus_is_not_flagged(ctx, db_session, tenant, year):
    _bus(db_session, tenant, capacity=10)

    assert _alerts(tenant)["transport_issues"] == 0


# ---------------------------------------------------------------------------
# The cost must not grow with the fleet
# ---------------------------------------------------------------------------

def _queries_for_alerts(tenant):
    seen: list[str] = []

    def record(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        dashboard._alerts(tenant.id, True, finance_enabled=False)
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    return len(seen)


def test_the_cost_does_not_grow_with_the_number_of_buses(
    ctx, db_session, tenant, year
):
    """A COUNT per bus is a round trip per bus, on the most-loaded page."""
    live = _route(db_session, tenant, status="active")
    for _ in range(2):
        _enrol(db_session, tenant, year, _bus(db_session, tenant), live)
    small = _queries_for_alerts(tenant)

    for _ in range(18):
        _enrol(db_session, tenant, year, _bus(db_session, tenant), live)
    large = _queries_for_alerts(tenant)

    assert large == small, (
        f"{small} queries for 2 buses, {large} for 20 — one per bus"
    )


# ---------------------------------------------------------------------------
# The same shape on the smaller sets
# ---------------------------------------------------------------------------

def _class(db_session, tenant, year):
    from modules.classes.models import Class

    cls = Class(id=_new_id("c-"), tenant_id=tenant.id,
                name=f"Grade {uuid.uuid4().hex[:3]}", section="A",
                academic_year_id=year.id)
    db_session.add(cls)
    db_session.flush()
    return cls


def _subject(db_session, tenant):
    from modules.subjects.models import Subject

    subject = Subject(id=_new_id("sub-"), tenant_id=tenant.id,
                      name=f"Subject {uuid.uuid4().hex[:5]}",
                      code=f"S{uuid.uuid4().hex[:5]}")
    db_session.add(subject)
    db_session.flush()
    return subject


def _class_subject(db_session, tenant, cls, *, with_primary_teacher=False):
    from modules.classes.models import ClassSubject

    cs = ClassSubject(id=_new_id("cs-"), tenant_id=tenant.id, class_id=cls.id,
                      subject_id=_subject(db_session, tenant).id,
                      status="active", weekly_periods=4)
    db_session.add(cs)
    db_session.flush()

    if with_primary_teacher:
        from modules.academics.backbone.models import ClassSubjectTeacher

        db_session.add(ClassSubjectTeacher(
            id=_new_id("cst-"), tenant_id=tenant.id, class_subject_id=cs.id,
            teacher_id=_teacher(db_session, tenant).id,
            role="primary", is_active=True,
        ))
        db_session.flush()
    return cs


def _teacher(db_session, tenant):
    from tests.conftest import employ_for
    from modules.auth.models import User
    from modules.teachers.models import Teacher

    suffix = uuid.uuid4().hex[:10]
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"t-{suffix}@test.school", password_hash="x" * 60,
                name="Teacher")
    db_session.add(user)
    db_session.flush()
    teacher = Teacher(
        id=_new_id("t-"), tenant_id=tenant.id, user_id=user.id,
        staff_id=employ_for(user, employee_number=f"E-{suffix[:8]}").id,
    )
    db_session.add(teacher)
    db_session.flush()
    return teacher


def test_a_class_subject_with_no_primary_teacher_is_counted(
    ctx, db_session, tenant, year
):
    cls = _class(db_session, tenant, year)
    _class_subject(db_session, tenant, cls, with_primary_teacher=True)
    _class_subject(db_session, tenant, cls, with_primary_teacher=False)

    assert _alerts(tenant)["subjects_without_teacher"] == 1


def test_a_class_with_no_subjects_is_counted(ctx, db_session, tenant, year):
    with_subject = _class(db_session, tenant, year)
    _class_subject(db_session, tenant, with_subject, with_primary_teacher=True)
    _class(db_session, tenant, year)          # bare
    _class(db_session, tenant, year)          # bare

    assert _alerts(tenant)["classes_without_subjects"] == 2


def test_the_cost_does_not_grow_with_the_number_of_classes(
    ctx, db_session, tenant, year
):
    for _ in range(2):
        _class_subject(db_session, tenant, _class(db_session, tenant, year))
    small = _queries_for_alerts(tenant)

    for _ in range(18):
        _class_subject(db_session, tenant, _class(db_session, tenant, year))
    large = _queries_for_alerts(tenant)

    assert large == small, (
        f"{small} queries for 2 classes, {large} for 20"
    )
