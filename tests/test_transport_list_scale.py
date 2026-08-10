"""A transport list costs the same whether four children ride or four hundred.

Listing enrollments used to read each row's route, its stop, its schedules and
its student separately — six queries a child. A school with three thousand on
buses paid eighteen thousand queries to open one screen, which is the shape the
scale contract exists to forbid.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy import event

from core.database import db


@pytest.fixture
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        tenant_id=tenant.id,
        name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1),
        end_date=date(2027, 3, 31),
    )
    db_session.add(year)
    db_session.flush()
    return year


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _bus_and_route(db_session, tenant):
    from modules.transport.models import TransportBus, TransportRoute

    suffix = uuid.uuid4().hex[:6]
    bus = TransportBus(
        tenant_id=tenant.id, bus_number=f"BUS-{suffix}", capacity=60, status="active"
    )
    route = TransportRoute(tenant_id=tenant.id, name=f"Route {suffix}", status="active")
    db_session.add_all([bus, route])
    db_session.flush()
    return bus, route


def _child_who_rides(db_session, tenant):
    """A student, since an enrollment is a child on a bus."""
    from modules.auth.models import User
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:8]
    user = User(
        tenant_id=tenant.id,
        email=f"rider-{suffix}@test.school",
        password_hash="x" * 60,
        name=f"Rider {suffix}",
    )
    db_session.add(user)
    db_session.flush()

    student = Student(
        tenant_id=tenant.id,
        user_id=user.id,
        person_id=user.person_id,
        admission_number=f"ADM-{suffix}",
    )
    db_session.add(student)
    db_session.flush()
    return student


def _enroll(db_session, tenant, bus, route, year, count):
    from modules.transport.models import TransportEnrollment

    for _ in range(count):
        db_session.add(
            TransportEnrollment(
                tenant_id=tenant.id,
                student_id=_child_who_rides(db_session, tenant).id,
                academic_year_id=year.id,
                bus_id=bus.id,
                route_id=route.id,
                start_date=date(2026, 6, 1),
                monthly_fee=900,
                status="active",
            )
        )
    db_session.flush()


def test_listing_enrollments_does_not_query_per_child(
    ctx, tenant, db_session, academic_year
):
    from modules.transport import services

    bus, route = _bus_and_route(db_session, tenant)

    def queries_for(additional):
        _enroll(db_session, tenant, bus, route, academic_year, additional)

        seen = []

        def record(conn, cursor, statement, params, context, executemany):
            seen.append(statement)

        event.listen(db.engine, "before_cursor_execute", record)
        try:
            services.list_enrollments()
        finally:
            event.remove(db.engine, "before_cursor_execute", record)
        return len(seen)

    few = queries_for(2)
    many = queries_for(10)

    assert many <= few, (
        f"transport enrollment queries grew with the number of children "
        f"({few} -> {many}): N+1"
    )


# ---------------------------------------------------------------------------
# Asking for a page
# ---------------------------------------------------------------------------

def test_a_caller_that_asks_for_nothing_gets_what_it_always_got(
    ctx, tenant, db_session, academic_year
):
    """admin-web and the Expo app both read these as plain arrays.

    Handing them an envelope they cannot read, or a first page dressed up as
    the whole fleet, are both worse than the query being slow.
    """
    from modules.transport import services

    bus, route = _bus_and_route(db_session, tenant)
    _enroll(db_session, tenant, bus, route, academic_year, 3)

    assert isinstance(services.list_enrollments(), list)
    assert isinstance(services.list_buses(), list)
    assert isinstance(services.list_routes(), list)
    assert isinstance(services.list_drivers(), list)


def test_asking_for_a_page_describes_the_whole(ctx, tenant, db_session, academic_year):
    from modules.transport import services

    bus, route = _bus_and_route(db_session, tenant)
    _enroll(db_session, tenant, bus, route, academic_year, 7)

    first = services.list_enrollments(page=1, per_page=3)

    assert len(first["items"]) == 3
    assert first["total"] == 7
    assert first["total_pages"] == 3
    assert first["page"] == 1

    last = services.list_enrollments(page=3, per_page=3)
    assert len(last["items"]) == 1


def test_a_page_of_children_does_not_read_every_child(
    ctx, tenant, db_session, academic_year
):
    """The point of paging this list: it grows with the school, not the fleet."""
    from modules.transport import services

    bus, route = _bus_and_route(db_session, tenant)
    _enroll(db_session, tenant, bus, route, academic_year, 12)

    assert len(services.list_enrollments(page=1, per_page=4)["items"]) == 4
    assert len(services.list_enrollments()) == 12


def test_a_client_cannot_ask_for_an_unbounded_page(ctx, tenant, db_session, academic_year):
    """A page size is a promise about the largest response, not a suggestion."""
    from modules.transport import services

    bus, route = _bus_and_route(db_session, tenant)
    _enroll(db_session, tenant, bus, route, academic_year, 3)

    asked_for_everything = services.list_enrollments(page=1, per_page=100_000)

    assert asked_for_everything["per_page"] == services.MAX_TRANSPORT_PAGE_SIZE


def test_nonsense_page_values_do_not_hide_rows(ctx, tenant, db_session, academic_year):
    from modules.transport import services

    bus, route = _bus_and_route(db_session, tenant)
    _enroll(db_session, tenant, bus, route, academic_year, 3)

    assert len(services.list_buses(page="not-a-number", per_page="nonsense")) == 1


def test_a_paged_list_is_searched_on_the_server(
    ctx, tenant, db_session, academic_year
):
    """A screen that pages cannot filter what it has not fetched.

    Searching in the browser would find a child only if they happened to be on
    the page already shown, so a student on page four reads as one who does not
    exist.
    """
    from modules.people.service import revise_identity
    from modules.transport import services

    bus, route = _bus_and_route(db_session, tenant)
    _enroll(db_session, tenant, bus, route, academic_year, 6)

    everyone = services.list_enrollments()
    wanted = everyone[-1]
    student = _student_of(wanted["student_id"])
    revise_identity(student.person, {"full_name": "Findable Child"})
    db_session.flush()

    # Deliberately smaller than the number enrolled: without server-side
    # search this child is not on the first page and would not be found.
    found = services.list_enrollments(search="Findable", page=1, per_page=2)

    assert found["total"] == 1
    assert found["items"][0]["student_name"] == "Findable Child"


def test_searching_by_admission_number_finds_the_child(
    ctx, tenant, db_session, academic_year
):
    from modules.transport import services

    bus, route = _bus_and_route(db_session, tenant)
    _enroll(db_session, tenant, bus, route, academic_year, 4)

    everyone = services.list_enrollments()
    admission_number = everyone[0]["admission_number"]

    found = services.list_enrollments(search=admission_number)

    assert len(found) == 1
    assert found[0]["admission_number"] == admission_number


def _student_of(student_id):
    from modules.students.models import Student

    return Student.query.get(student_id)


# ---------------------------------------------------------------------------
# The dashboard counts on the server
# ---------------------------------------------------------------------------

def test_the_dashboard_counts_children_waiting_for_a_bus(
    ctx, tenant, db_session, academic_year
):
    """The browser used to fetch every student and every enrollment for this.

    Comparing two whole tables in the client is the same scale problem as an
    N+1, just paid in bandwidth instead of queries.
    """
    from modules.transport import services

    bus, route = _bus_and_route(db_session, tenant)
    _enroll(db_session, tenant, bus, route, academic_year, 2)

    waiting = _child_who_rides(db_session, tenant)
    waiting.is_transport_opted = True
    db_session.flush()

    stats = services.dashboard_stats()

    assert stats["students_opted_without_enrollment"] == 1
    assert stats["students_with_active_enrollment"] == 2


def test_the_dashboard_does_not_query_per_child(ctx, tenant, db_session, academic_year):
    from modules.transport import services

    bus, route = _bus_and_route(db_session, tenant)

    def queries_for(additional):
        _enroll(db_session, tenant, bus, route, academic_year, additional)

        seen = []

        def record(conn, cursor, statement, params, context, executemany):
            seen.append(statement)

        event.listen(db.engine, "before_cursor_execute", record)
        try:
            services.dashboard_stats()
        finally:
            event.remove(db.engine, "before_cursor_execute", record)
        return len(seen)

    few = queries_for(2)
    many = queries_for(10)

    assert many <= few, (
        f"dashboard queries grew with the number of children ({few} -> {many}): N+1"
    )


# ---------------------------------------------------------------------------
# The fleet costs the same whether four buses run or four hundred
# ---------------------------------------------------------------------------

def _fleet(db_session, tenant, count):
    """`count` buses, each with an active assignment to its own route."""
    from modules.transport.models import (
        TransportBus,
        TransportBusAssignment,
        TransportDriver,
        TransportRoute,
    )

    suffix = uuid.uuid4().hex[:6]
    driver = TransportDriver(
        tenant_id=tenant.id, name=f"Driver {suffix}", phone=f"9{suffix}00",
        license_number=f"LN-{suffix}", status="active",
    )
    db_session.add(driver)
    db_session.flush()

    for index in range(count):
        bus = TransportBus(
            tenant_id=tenant.id, bus_number=f"F{suffix}-{index}",
            capacity=40, status="active",
        )
        route = TransportRoute(
            tenant_id=tenant.id, name=f"R{suffix}-{index}", status="active"
        )
        db_session.add_all([bus, route])
        db_session.flush()
        db_session.add(
            TransportBusAssignment(
                tenant_id=tenant.id, bus_id=bus.id, route_id=route.id,
                driver_id=driver.id, effective_from=date(2026, 1, 1),
                status="active",
            )
        )
    db_session.flush()


def _queries_during(action):
    seen = []

    def record(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        action()
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    return len(seen)


def test_listing_the_fleet_does_not_query_per_bus(ctx, tenant, db_session):
    """The operational warning used to be asked one bus at a time.

    Each bus cost a query for its assignments and another counting its
    schedules, on top of the row itself. Measured on the real database before
    this changed: 29 buses took 62 queries, 104 took 212 and 254 took 512 — and
    because the rows are built before the page is cut, asking for twenty of them
    still paid for all 254.
    """
    from modules.transport import services

    _fleet(db_session, tenant, 3)
    few = _queries_during(lambda: services.list_buses(page=1, per_page=20))

    _fleet(db_session, tenant, 15)
    many = _queries_during(lambda: services.list_buses(page=1, per_page=20))

    assert many <= few, (
        f"fleet queries grew with the number of buses ({few} -> {many}): N+1"
    )


def test_the_dashboard_does_not_query_per_bus(ctx, tenant, db_session):
    """Same shape, counting how many buses lack a usable route."""
    from modules.transport import services

    _fleet(db_session, tenant, 3)
    few = _queries_during(services.dashboard_stats)

    _fleet(db_session, tenant, 15)
    many = _queries_during(services.dashboard_stats)

    assert many <= few, (
        f"dashboard queries grew with the number of buses ({few} -> {many}): N+1"
    )


def test_the_batched_warning_says_what_the_single_bus_one_says(
    ctx, tenant, db_session
):
    """Two paths compute this now, and they must not drift.

    `_bus_operational_warning` still loads for one bus, for the detail view;
    the fleet reads the same facts once and decides in memory.
    """
    from modules.transport import services
    from modules.transport.models import TransportBus, TransportRoute

    _fleet(db_session, tenant, 3)
    # A bus with no assignment at all, so more than one branch is compared.
    db_session.add(
        TransportBus(
            tenant_id=tenant.id, bus_number=f"LONE-{uuid.uuid4().hex[:6]}",
            capacity=40, status="active",
        )
    )
    # And a bus whose route is not active.
    stale = TransportRoute.query.filter_by(tenant_id=tenant.id).first()
    if stale:
        stale.status = "inactive"
    db_session.flush()

    ay = services.resolve_default_academic_year_id()
    on = services._today()
    rows = services.list_buses(page=1, per_page=100)
    items = rows["items"] if isinstance(rows, dict) else rows

    assert items, "no buses to compare"
    for row in items:
        single = services._bus_operational_warning(tenant.id, row["id"], ay, on)
        assert row["transport_operational"] == single, row["id"]
