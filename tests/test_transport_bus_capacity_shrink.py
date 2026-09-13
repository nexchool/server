"""Shrinking a bus must respect every seat already promised, not just today's.

update_bus refused a capacity below the seats occupied today. A seat booked
from next month, or next year's roll-over, is still a promise the bus has to
keep, so the bus cannot be shrunk under those either.
"""
from __future__ import annotations

import sys
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from flask import g

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _mk(model_cls, **kw):
    from core.database import db

    obj = model_cls(id=uuid.uuid4().hex, **kw)
    db.session.add(obj)
    db.session.flush()
    return obj


def _seat(tenant, *, bus, route, ay, suffix, start, end=None, status="active"):
    from modules.auth.models import User
    from modules.students.models import Student
    from modules.transport.models import TransportEnrollment

    user = _mk(User, tenant_id=tenant.id, email=f"seat-{suffix}@test.local",
               password_hash="x" * 60, name=f"Seat {suffix}")
    student = _mk(Student, tenant_id=tenant.id, user_id=user.id,
                  admission_number=f"SEAT-{suffix}", academic_year_id=ay.id)
    return _mk(TransportEnrollment, tenant_id=tenant.id, student_id=student.id,
               academic_year_id=ay.id, bus_id=bus.id, route_id=route.id,
               monthly_fee=Decimal("500"), status=status, start_date=start, end_date=end)


def _fleet(tenant, capacity):
    from modules.academics.academic_year.models import AcademicYear
    from modules.transport.models import TransportBus, TransportRoute

    ay = _mk(AcademicYear, tenant_id=tenant.id, name="2026-27",
             start_date="2026-06-01", end_date="2027-03-31")
    bus = _mk(TransportBus, tenant_id=tenant.id, bus_number="SHR1",
              capacity=capacity, status="active")
    route = _mk(TransportRoute, tenant_id=tenant.id, name="Shrink Route", status="active")
    return ay, bus, route


def test_a_bus_cannot_shrink_under_a_seat_booked_from_next_month(
    flask_app, db_session, tenant
):
    from core.school_time import school_today
    from modules.transport import services

    ay, bus, route = _fleet(tenant, capacity=2)
    today = school_today()
    _seat(tenant, bus=bus, route=route, ay=ay, suffix="now", start=today - timedelta(days=30))
    _seat(tenant, bus=bus, route=route, ay=ay, suffix="soon", start=today + timedelta(days=30))

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        result, err = services.update_bus(bus.id, {"capacity": 1})
    assert result is None
    assert err is not None and "2" in err
    assert bus.capacity == 2


def test_a_seat_that_has_ended_no_longer_holds_the_bus(flask_app, db_session, tenant):
    from core.school_time import school_today
    from modules.transport import services

    ay, bus, route = _fleet(tenant, capacity=2)
    today = school_today()
    _seat(tenant, bus=bus, route=route, ay=ay, suffix="now", start=today - timedelta(days=30))
    _seat(tenant, bus=bus, route=route, ay=ay, suffix="gone",
          start=today - timedelta(days=200), end=today - timedelta(days=10))
    _seat(tenant, bus=bus, route=route, ay=ay, suffix="left",
          start=today - timedelta(days=200), status="inactive")

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        result, err = services.update_bus(bus.id, {"capacity": 1})
    assert err is None and result is not None
    assert bus.capacity == 1
