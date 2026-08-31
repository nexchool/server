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
    # `g` lives on the app context, which `test_request_context` may reuse, so
    # a scope resolved for a previous user would otherwise answer for this one.
    # A real request gets a fresh app context and cannot hit this.
    g.pop("_branch_scope_allowed_unit_ids", None)
    g.pop("_branch_scope_allowed_class_ids", None)
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


# ---------------------------------------------------------------------------
# Hostel — gatepasses and visitors
#
# Phase 21 scoped *allocations* (which bed a child sleeps in) and stopped
# there. A gatepass and a visitor log are facts about the same child, carry
# the same `student_id`, and were left unscoped — so a head of one campus
# reads every campus's gatepasses, including each child's parent phone
# number, and every visitor who has ever signed in for a child they have no
# authority over.
#
# Hostels themselves have no `school_unit_id` — they are tenant-wide — so the
# student is the only anchor, which is exactly what `list_allocations` uses.
# ---------------------------------------------------------------------------

def _hostel(db_session, tenant):
    from modules.hostel.models import Hostel

    suffix = uuid.uuid4().hex[:6]
    hostel = Hostel(tenant_id=tenant.id, name=f"Hostel {suffix}", capacity=50)
    db_session.add(hostel)
    db_session.flush()
    return hostel


def _gatepass(db_session, tenant, student, hostel, *, status="pending",
              expected_return=None):
    from modules.hostel.models import HostelGatepass

    gatepass = HostelGatepass(
        tenant_id=tenant.id, student_id=student.id, hostel_id=hostel.id,
        type="day_out", status=status,
        departure_datetime=datetime(2026, 9, 1, 9, 0),
        expected_return_datetime=expected_return or datetime(2026, 9, 1, 18, 0),
        parent_phone="9800000000",
    )
    db_session.add(gatepass)
    db_session.flush()
    return gatepass


def _visitor_log(db_session, tenant, student, hostel):
    from modules.hostel.models import HostelVisitor, HostelVisitorLog

    suffix = uuid.uuid4().hex[:8]
    visitor = HostelVisitor(
        tenant_id=tenant.id, phone=f"98{suffix[:8]}", name=f"Visitor {suffix}",
        relation_type="father",
    )
    db_session.add(visitor)
    db_session.flush()
    log = HostelVisitorLog(
        tenant_id=tenant.id, visitor_id=visitor.id, student_id=student.id,
        hostel_id=hostel.id, check_in_at=datetime(2026, 9, 1, 11, 0),
    )
    db_session.add(log)
    db_session.flush()
    return log


@pytest.fixture
def two_campus_boarders(db_session, tenant, classes, academic_year):
    """One boarder on each campus, sharing a tenant-wide hostel."""
    class_a, class_b = classes
    return {
        "hostel": _hostel(db_session, tenant),
        "ours": _make_student(db_session, tenant, class_a.id, academic_year.id),
        "theirs": _make_student(db_session, tenant, class_b.id, academic_year.id),
    }


def test_a_campus_head_sees_only_their_campus_gatepasses(
    flask_app, db_session, tenant, two_campus_boarders, restricted_to_campus_a
):
    from modules.hostel.services.gatepass_service import GatepassService

    hostel = two_campus_boarders["hostel"]
    ours = _gatepass(db_session, tenant, two_campus_boarders["ours"], hostel)
    _gatepass(db_session, tenant, two_campus_boarders["theirs"], hostel)

    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        visible = {
            gp.id
            for gp in GatepassService(db_session).list_gatepasses(
                tenant_id=tenant.id
            )["items"]
        }
    finally:
        ctx.pop()

    assert visible == {ours.id}


def test_the_trust_administrator_still_sees_every_gatepass(
    flask_app, db_session, tenant, two_campus_boarders, unrestricted
):
    """No UserSchoolUnit rows means unrestricted — every existing admin."""
    hostel = two_campus_boarders["hostel"]
    ours = _gatepass(db_session, tenant, two_campus_boarders["ours"], hostel)
    theirs = _gatepass(db_session, tenant, two_campus_boarders["theirs"], hostel)

    from modules.hostel.services.gatepass_service import GatepassService

    ctx = _as(flask_app, tenant, unrestricted)
    try:
        visible = {
            gp.id
            for gp in GatepassService(db_session).list_gatepasses(
                tenant_id=tenant.id
            )["items"]
        }
    finally:
        ctx.pop()

    assert {ours.id, theirs.id} <= visible


def test_a_campus_head_sees_only_their_campus_overdue_alerts(
    flask_app, db_session, tenant, two_campus_boarders, restricted_to_campus_a
):
    """The warden's alert list — a child who has not come back.

    Note this is `ReportService.overdue_alerts`, not the similarly named
    `GatepassService.find_overdue_gatepasses`. The two are easy to confuse:
    the latter finds ACTIVE gatepasses that are past due so the beat task can
    mark them, and no route reaches it. This one reads rows already marked
    OVERDUE, and is what the screen calls.
    """
    from modules.hostel.services.report_service import ReportService

    hostel = two_campus_boarders["hostel"]
    ours = _gatepass(db_session, tenant, two_campus_boarders["ours"], hostel,
                     status="overdue")
    _gatepass(db_session, tenant, two_campus_boarders["theirs"], hostel,
              status="overdue")

    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        visible = {
            gp.id
            for gp in ReportService(db_session).overdue_alerts(tenant_id=tenant.id)
        }
    finally:
        ctx.pop()

    assert visible == {ours.id}


def test_a_campus_head_exports_only_their_campus_residents(
    flask_app, db_session, tenant, classes, academic_year, restricted_to_campus_a
):
    """residents.csv is a download, so an unscoped one leaves the building."""
    from modules.hostel.services.report_service import ReportService

    class_a, class_b = classes
    ours = _allocate(db_session, tenant,
                     _make_student(db_session, tenant, class_a.id, academic_year.id),
                     academic_year)
    _allocate(db_session, tenant,
              _make_student(db_session, tenant, class_b.id, academic_year.id),
              academic_year)

    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        exported = {
            row["student_id"]
            for row in ReportService(db_session).residents_csv_rows(
                tenant_id=tenant.id
            )
        }
    finally:
        ctx.pop()

    assert exported == {ours.student_id}


def test_a_campus_head_sees_only_their_campus_visitor_logs(
    flask_app, db_session, tenant, two_campus_boarders, restricted_to_campus_a
):
    from modules.hostel.services.visitor_service import VisitorService

    hostel = two_campus_boarders["hostel"]
    ours = _visitor_log(db_session, tenant, two_campus_boarders["ours"], hostel)
    _visitor_log(db_session, tenant, two_campus_boarders["theirs"], hostel)

    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        visible = {
            log.id
            for log in VisitorService(db_session).list_visitor_logs(
                tenant_id=tenant.id
            )
        }
    finally:
        ctx.pop()

    assert visible == {ours.id}


def test_the_overnight_job_still_sweeps_every_campus(
    flask_app, db_session, tenant, two_campus_boarders
):
    """`mark_overdue_gatepasses_task` runs on a beat schedule, not a request.

    Branch scope reads the current user off the request context, so outside one
    it resolves to UNRESTRICTED — which is what the sweep needs, since it must
    mark every campus's gatepasses overdue. Pinned here because scoping this
    query would otherwise silently stop the job doing its work.
    """
    from modules.hostel.services.gatepass_service import GatepassService

    hostel = two_campus_boarders["hostel"]
    long_ago = datetime(2020, 1, 1, 18, 0)
    ours = _gatepass(db_session, tenant, two_campus_boarders["ours"], hostel,
                     status="active", expected_return=long_ago)
    theirs = _gatepass(db_session, tenant, two_campus_boarders["theirs"], hostel,
                       status="active", expected_return=long_ago)

    # Deliberately no request context — this is how the beat task calls it.
    visible = {gp.id for gp in GatepassService(db_session).find_overdue_gatepasses()}

    assert {ours.id, theirs.id} <= visible


def test_a_campus_head_cannot_open_another_campus_gatepass(
    flask_app, db_session, tenant, two_campus_boarders, restricted_to_campus_a
):
    """Reading one by id must not be the way around the list being scoped.

    Filtered rather than refused: a 403 would confirm the gatepass exists, and
    for a single object "not found" is the honest answer to someone with no
    authority over the child it belongs to.
    """
    from modules.hostel.services.gatepass_service import GatepassService

    hostel = two_campus_boarders["hostel"]
    ours = _gatepass(db_session, tenant, two_campus_boarders["ours"], hostel)
    theirs = _gatepass(db_session, tenant, two_campus_boarders["theirs"], hostel)

    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        service = GatepassService(db_session)
        mine = service.get_gatepass(ours.id, tenant_id=tenant.id)
        other = service.get_gatepass(theirs.id, tenant_id=tenant.id)
    finally:
        ctx.pop()

    assert mine is not None and mine.id == ours.id
    assert other is None
