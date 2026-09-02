"""A bus roster is a list of children, so it follows the children's campuses.

`list_enrollments` — the transport screen — is branch-scoped: `branch_scope.py`
says which bus a child rides is a fact about the child, not about the vehicle,
because a trust may run one fleet across every campus.

Three reads of the same rows were not scoped, and two of them are downloads:

  * `get_bus_details` — the seat-by-seat roster for one bus
  * `export_bus_students_csv`
  * `export_route_students_csv`

So a head of Campus A opened a bus and saw every campus's children on it, and
could export the list as a file. This is the same asymmetry the hostel module
had — the screen scoped, the CSV not.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from modules.auth.models import User
from modules.classes.models import Class
from modules.students.models import Student
from modules.sub_admins.models import UserSchoolUnit
from modules.transport import services as transport


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def units(db_session, tenant):
    from modules.school_units.models import SchoolUnit

    a = SchoolUnit(id=_new_id("su-"), tenant_id=tenant.id, name="Campus A",
                   code=f"A-{uuid.uuid4().hex[:6]}")
    b = SchoolUnit(id=_new_id("su-"), tenant_id=tenant.id, name="Campus B",
                   code=f"B-{uuid.uuid4().hex[:6]}")
    db_session.add_all([a, b])
    db_session.flush()
    return a, b


@pytest.fixture
def year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(id=_new_id("ay-"), tenant_id=tenant.id,
                      name=f"AY-{uuid.uuid4().hex[:6]}",
                      start_date=date(2026, 6, 1), end_date=date(2027, 3, 31))
    db_session.add(ay)
    db_session.flush()
    return ay


@pytest.fixture
def classes(db_session, tenant, units, year):
    a, b = units
    ca = Class(id=_new_id("c-"), tenant_id=tenant.id, name="Grade 2",
               section="A", academic_year_id=year.id, school_unit_id=a.id)
    cb = Class(id=_new_id("c-"), tenant_id=tenant.id, name="Grade 2",
               section="B", academic_year_id=year.id, school_unit_id=b.id)
    db_session.add_all([ca, cb])
    db_session.flush()
    return ca, cb


def _child(db_session, tenant, cls, name):
    from modules.people.models import Person

    suffix = uuid.uuid4().hex[:10]
    person = Person(id=f"pe-{suffix}", tenant_id=tenant.id, full_name=name)
    db_session.add(person)
    db_session.flush()
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"{suffix}@test.school", password_hash="x" * 60,
                name=name, person_id=person.id)
    db_session.add(user)
    db_session.flush()
    student = Student(id=f"s-{suffix}", tenant_id=tenant.id, user_id=user.id,
                      person_id=person.id, admission_number=f"A-{suffix[:8]}",
                      class_id=cls.id, academic_year_id=cls.academic_year_id)
    db_session.add(student)
    db_session.flush()
    return student


@pytest.fixture
def one_bus_two_campuses(db_session, tenant, classes, year):
    """One vehicle serving both campuses — the shape branch_scope describes."""
    from modules.transport.models import (
        TransportBus, TransportEnrollment, TransportRoute,
    )

    ca, cb = classes
    bus = TransportBus(id=_new_id("bs-"), tenant_id=tenant.id,
                       bus_number=f"B{uuid.uuid4().hex[:5]}", capacity=40)
    route = TransportRoute(id=_new_id("rt-"), tenant_id=tenant.id,
                           name=f"Route {uuid.uuid4().hex[:5]}", status="active")
    db_session.add_all([bus, route])
    db_session.flush()

    made = {}
    for key, cls, name in (("ours", ca, "Aarti Ours"), ("theirs", cb, "Bilal Theirs")):
        child = _child(db_session, tenant, cls, name)
        enrolment = TransportEnrollment(
            id=_new_id("te-"), tenant_id=tenant.id, student_id=child.id,
            academic_year_id=year.id, bus_id=bus.id, route_id=route.id,
            status="active", monthly_fee=500, start_date=date(2026, 6, 1),
        )
        db_session.add(enrolment)
        db_session.flush()
        made[key] = {"student": child, "enrolment": enrolment, "name": name}

    made["bus"] = bus
    made["route"] = route
    return made


@pytest.fixture
def restricted_to_campus_a(db_session, tenant, units):
    a, _ = units
    user = User(id=_new_id("ru-"), tenant_id=tenant.id,
                email=f"ru-{uuid.uuid4().hex[:6]}@test.school",
                password_hash="x" * 60, name="Head of Campus A")
    db_session.add(user)
    db_session.flush()
    db_session.add(UserSchoolUnit(id=_new_id("usu-"), tenant_id=tenant.id,
                                  user_id=user.id, school_unit_id=a.id))
    db_session.flush()
    return user


@pytest.fixture
def unrestricted(db_session, tenant):
    user = User(id=_new_id("uu-"), tenant_id=tenant.id,
                email=f"uu-{uuid.uuid4().hex[:6]}@test.school",
                password_hash="x" * 60, name="Trust Administrator")
    db_session.add(user)
    db_session.flush()
    return user


def _as(flask_app, tenant, user):
    ctx = flask_app.test_request_context("/")
    ctx.push()
    g.pop("_branch_scope_allowed_unit_ids", None)
    g.pop("_branch_scope_allowed_class_ids", None)
    g.tenant_id = tenant.id
    g.current_user = user
    return ctx


# ---------------------------------------------------------------------------
# The roster screen
# ---------------------------------------------------------------------------

def test_a_campus_head_sees_only_their_children_on_the_bus(
    flask_app, db_session, tenant, one_bus_two_campuses, restricted_to_campus_a
):
    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        details, err = transport.get_bus_details(one_bus_two_campuses["bus"].id)
    finally:
        ctx.pop()

    assert err is None, err
    seated = {s["student_id"] for s in details["students"]}
    assert seated == {one_bus_two_campuses["ours"]["student"].id}


def test_the_trust_administrator_sees_the_whole_bus(
    flask_app, db_session, tenant, one_bus_two_campuses, unrestricted
):
    """One fleet across every campus is the normal shape; unrestricted sees it."""
    ctx = _as(flask_app, tenant, unrestricted)
    try:
        details, err = transport.get_bus_details(one_bus_two_campuses["bus"].id)
    finally:
        ctx.pop()

    assert err is None, err
    seated = {s["student_id"] for s in details["students"]}
    assert seated == {
        one_bus_two_campuses["ours"]["student"].id,
        one_bus_two_campuses["theirs"]["student"].id,
    }


# ---------------------------------------------------------------------------
# The downloads
# ---------------------------------------------------------------------------

def test_a_campus_head_exports_only_their_children_from_a_bus(
    flask_app, db_session, tenant, one_bus_two_campuses, restricted_to_campus_a
):
    """A CSV leaves the building, so an unscoped one leaves with it."""
    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        csv_text, err = transport.export_bus_students_csv(
            one_bus_two_campuses["bus"].id
        )
    finally:
        ctx.pop()

    assert err is None, err
    assert "Aarti Ours" in csv_text
    assert "Bilal Theirs" not in csv_text


def test_a_campus_head_exports_only_their_children_from_a_route(
    flask_app, db_session, tenant, one_bus_two_campuses, restricted_to_campus_a
):
    ctx = _as(flask_app, tenant, restricted_to_campus_a)
    try:
        csv_text, err = transport.export_route_students_csv(
            one_bus_two_campuses["route"].id
        )
    finally:
        ctx.pop()

    assert err is None, err
    assert "Aarti Ours" in csv_text
    assert "Bilal Theirs" not in csv_text


def test_the_trust_administrator_exports_everyone(
    flask_app, db_session, tenant, one_bus_two_campuses, unrestricted
):
    ctx = _as(flask_app, tenant, unrestricted)
    try:
        csv_text, err = transport.export_bus_students_csv(
            one_bus_two_campuses["bus"].id
        )
    finally:
        ctx.pop()

    assert err is None, err
    assert "Aarti Ours" in csv_text
    assert "Bilal Theirs" in csv_text
