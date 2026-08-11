"""A sub-admin restricted to one campus sees only that campus.

Teachers, transport and hostel had no branch scoping at all — on a trust
running twenty campuses, a head of one campus could see every campus's staff,
every child riding a bus and every child in a bed. Tenancy kept one school out
of another's data; nothing kept one campus out of another's.

The rule is the same as everywhere else: no UserSchoolUnit rows means
unrestricted, which is what every existing admin is.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from flask import g

from modules.auth.models import User
from modules.classes.models import Class
from modules.students.models import Student
from modules.sub_admins.models import UserSchoolUnit
from modules.teachers.models import Teacher


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def units(db_session, tenant):
    from modules.school_units.models import SchoolUnit

    unit_a = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="Campus A",
        code=f"A-{uuid.uuid4().hex[:6]}",
    )
    unit_b = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="Campus B",
        code=f"B-{uuid.uuid4().hex[:6]}",
    )
    db_session.add_all([unit_a, unit_b])
    db_session.flush()
    return unit_a, unit_b


@pytest.fixture
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id,
        name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(year)
    db_session.flush()
    return year


@pytest.fixture
def classes(db_session, tenant, units, academic_year):
    unit_a, unit_b = units
    class_a = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 1", section="A",
        academic_year_id=academic_year.id, school_unit_id=unit_a.id,
    )
    class_b = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 1", section="B",
        academic_year_id=academic_year.id, school_unit_id=unit_b.id,
    )
    db_session.add_all([class_a, class_b])
    db_session.flush()
    return class_a, class_b


def _make_student(db_session, tenant, class_id, academic_year_id):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=_new_id("u-"), tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name=f"Child {suffix}",
    )
    db_session.add(user)
    db_session.flush()
    student = Student(
        id=_new_id("s-"), tenant_id=tenant.id, user_id=user.id,
        person_id=user.person_id, admission_number=f"ADM-{suffix}",
        class_id=class_id, academic_year_id=academic_year_id,
    )
    db_session.add(student)
    db_session.flush()
    return student


def _make_teacher(db_session, tenant, class_id=None):
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

    if class_id:
        from modules.academics.backbone.models import ClassTeacherAssignment

        db_session.add(
            ClassTeacherAssignment(
                id=_new_id("cta-"), tenant_id=tenant.id,
                class_id=class_id, teacher_id=teacher.id,
                role="primary", is_active=True,
            )
        )
        db_session.flush()
    return teacher


@pytest.fixture
def restricted_to_campus_a(db_session, tenant, units):
    unit_a, _ = units
    user = User(
        id=_new_id("ru-"), tenant_id=tenant.id,
        email=f"ru-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60, name="Head of Campus A",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        UserSchoolUnit(
            id=_new_id("usu-"), tenant_id=tenant.id,
            user_id=user.id, school_unit_id=unit_a.id,
        )
    )
    db_session.flush()
    return user


@pytest.fixture
def unrestricted(db_session, tenant):
    """No UserSchoolUnit rows — every existing admin looks like this."""
    user = User(
        id=_new_id("uu-"), tenant_id=tenant.id,
        email=f"uu-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60, name="Trust Administrator",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _as(flask_app, tenant, user):
    ctx = flask_app.test_request_context("/")
    ctx.push()
    g.tenant_id = tenant.id
    g.current_user = user
    return ctx


# ---------------------------------------------------------------------------
# Teachers
# ---------------------------------------------------------------------------

def test_a_campus_head_sees_only_their_campus_teachers(
    flask_app, db_session, tenant, classes, restricted_to_campus_a
):
    from modules.teachers.services import list_teachers

    class_a, class_b = classes
    theirs = _make_teacher(db_session, tenant, class_a.id)
    _make_teacher(db_session, tenant, class_b.id)

    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        visible = {t["id"] for t in list_teachers()["items"]}
    finally:
        ctx.pop()

    assert visible == {theirs.id}


def test_the_trust_administrator_still_sees_every_teacher(
    flask_app, db_session, tenant, classes, unrestricted
):
    """Fail-open until restricted: existing admins must be unaffected."""
    from modules.teachers.services import list_teachers

    class_a, class_b = classes
    a = _make_teacher(db_session, tenant, class_a.id)
    b = _make_teacher(db_session, tenant, class_b.id)
    unassigned = _make_teacher(db_session, tenant, None)

    ctx = _as(flask_app, tenant, unrestricted)
    try:
        visible = {t["id"] for t in list_teachers()["items"]}
    finally:
        ctx.pop()

    assert {a.id, b.id, unassigned.id} <= visible


def test_a_teacher_with_no_class_belongs_to_no_campus_yet(
    flask_app, db_session, tenant, classes, restricted_to_campus_a
):
    """The same rule students already follow — a classless student is excluded.

    They are not lost: the trust administrator sees them, and they appear to a
    campus the moment they are given a class there.
    """
    from modules.teachers.services import list_teachers

    unassigned = _make_teacher(db_session, tenant, None)

    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        visible = {t["id"] for t in list_teachers()["items"]}
    finally:
        ctx.pop()

    assert unassigned.id not in visible


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def _enroll(db_session, tenant, student, academic_year):
    from modules.transport.models import (
        TransportBus, TransportEnrollment, TransportRoute,
    )

    suffix = uuid.uuid4().hex[:6]
    bus = TransportBus(
        tenant_id=tenant.id, bus_number=f"BUS-{suffix}", capacity=40,
        status="active",
    )
    route = TransportRoute(tenant_id=tenant.id, name=f"Route {suffix}", status="active")
    db_session.add_all([bus, route])
    db_session.flush()

    enrollment = TransportEnrollment(
        tenant_id=tenant.id, student_id=student.id,
        academic_year_id=academic_year.id, bus_id=bus.id, route_id=route.id,
        start_date=date(2026, 6, 1), monthly_fee=900, status="active",
    )
    db_session.add(enrollment)
    db_session.flush()
    return enrollment


def test_a_campus_head_sees_only_their_campus_children_on_buses(
    flask_app, db_session, tenant, classes, academic_year, restricted_to_campus_a
):
    from modules.transport.services import list_enrollments

    class_a, class_b = classes
    ours = _enroll(db_session, tenant,
                   _make_student(db_session, tenant, class_a.id, academic_year.id),
                   academic_year)
    _enroll(db_session, tenant,
            _make_student(db_session, tenant, class_b.id, academic_year.id),
            academic_year)

    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        visible = {e["id"] for e in list_enrollments()}
    finally:
        ctx.pop()

    assert visible == {ours.id}


# ---------------------------------------------------------------------------
# Hostel
# ---------------------------------------------------------------------------

def _allocate(db_session, tenant, student, academic_year):
    from modules.hostel.models import (
        Hostel, HostelAllocation, HostelBed, HostelRoom,
    )

    suffix = uuid.uuid4().hex[:6]
    hostel = Hostel(tenant_id=tenant.id, name=f"Hostel {suffix}", capacity=50)
    db_session.add(hostel)
    db_session.flush()
    room = HostelRoom(
        tenant_id=tenant.id, hostel_id=hostel.id, room_number=f"R{suffix}",
        capacity=2,
    )
    db_session.add(room)
    db_session.flush()
    bed = HostelBed(
        tenant_id=tenant.id, room_id=room.id, bed_number=f"B{suffix}",
    )
    db_session.add(bed)
    db_session.flush()

    allocation = HostelAllocation(
        tenant_id=tenant.id, hostel_id=hostel.id, room_id=room.id, bed_id=bed.id,
        student_id=student.id, academic_year_id=academic_year.id,
        check_in_at=datetime(2026, 6, 1), status="active",
    )
    db_session.add(allocation)
    db_session.flush()
    return allocation


def test_a_campus_head_sees_only_their_campus_boarders(
    flask_app, db_session, tenant, classes, academic_year, restricted_to_campus_a
):
    from modules.hostel.services.allocation_service import AllocationService

    class_a, class_b = classes
    ours = _allocate(db_session, tenant,
                     _make_student(db_session, tenant, class_a.id, academic_year.id),
                     academic_year)
    _allocate(db_session, tenant,
              _make_student(db_session, tenant, class_b.id, academic_year.id),
              academic_year)

    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        service = AllocationService(db_session)
        visible = {a.id for a in service.list_allocations(tenant_id=tenant.id)}
    finally:
        ctx.pop()

    assert visible == {ours.id}
