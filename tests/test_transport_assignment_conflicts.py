"""create_assignment must reject a driver/helper double-booked across buses.

A bus's one-active-assignment rule is DB-enforced; the driver and helper had no
guard, so one person could be assigned to two buses for an overlapping period.
"""
from __future__ import annotations

import sys
import uuid
from datetime import date
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


def _bus(tenant, number):
    from modules.transport.models import TransportBus

    return _mk(TransportBus, tenant_id=tenant.id, bus_number=number, capacity=40, status="active")


def _driver(tenant):
    from modules.transport.models import TransportDriver

    return _mk(TransportDriver, tenant_id=tenant.id, name="QA Driver", status="active")


def _route(tenant, name):
    from modules.transport.models import TransportRoute

    return _mk(TransportRoute, tenant_id=tenant.id, name=name, status="active")


def test_create_assignment_blocks_driver_double_booking(flask_app, db_session, tenant):
    from modules.transport import services

    bus_a, bus_b = _bus(tenant, "BUS-A"), _bus(tenant, "BUS-B")
    driver = _driver(tenant)
    route_a, route_b = _route(tenant, "Route A"), _route(tenant, "Route B")

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        a, err = services.create_assignment({
            "bus_id": bus_a.id, "driver_id": driver.id, "route_id": route_a.id,
            "effective_from": date(2026, 6, 1),
        })
        assert err is None and a is not None
        # Same driver, a DIFFERENT bus, overlapping period -> rejected.
        b, err2 = services.create_assignment({
            "bus_id": bus_b.id, "driver_id": driver.id, "route_id": route_b.id,
            "effective_from": date(2026, 6, 15),
        })
    assert b is None
    assert err2 is not None and "driver" in err2.lower()


def test_create_assignment_allows_driver_in_non_overlapping_period(flask_app, db_session, tenant):
    from modules.transport import services

    bus_a, bus_b = _bus(tenant, "BUS-A"), _bus(tenant, "BUS-B")
    driver = _driver(tenant)
    route_a, route_b = _route(tenant, "Route A"), _route(tenant, "Route B")

    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        _a, err = services.create_assignment({
            "bus_id": bus_a.id, "driver_id": driver.id, "route_id": route_a.id,
            "effective_from": date(2026, 1, 1), "effective_to": date(2026, 3, 31),
        })
        assert err is None
        # Same driver, a NON-overlapping later period -> allowed.
        b, err2 = services.create_assignment({
            "bus_id": bus_b.id, "driver_id": driver.id, "route_id": route_b.id,
            "effective_from": date(2026, 4, 1), "effective_to": date(2026, 6, 30),
        })
    assert err2 is None
    assert b is not None
