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
