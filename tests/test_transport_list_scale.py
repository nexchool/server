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
