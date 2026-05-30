"""Unit tests for GET /api/transport/students/me (nexchool Slice 4).

Pattern follows tests/timetable/test_weekly_endpoints.py: invoke the route's
underlying function via __wrapped__ to bypass decorators, with patched g,
request, and services.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SERVER_DIR = Path(__file__).resolve().parent.parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _unwrap(fn):
    inner = fn
    while hasattr(inner, "__wrapped__"):
        inner = inner.__wrapped__
    return inner


def _call_route(route_fn, *, service_return, current_user_id="u-1",
                tenant_id="t-1"):
    from modules.transport import routes as tr_routes

    fake_g = SimpleNamespace(
        current_user=SimpleNamespace(id=current_user_id),
        tenant_id=tenant_id,
    )
    fake_request = SimpleNamespace(args={})

    captured = {}

    def fake_success(data=None, message=None, status_code=200):
        captured["data"] = data
        captured["status_code"] = status_code
        return ("ok", status_code)

    def fake_error(error, message=None, status_code=400, details=None):
        captured["error"] = error
        captured["message"] = message
        captured["status_code"] = status_code
        return ("err", status_code)

    def fake_not_found(resource="Resource"):
        captured["error"] = "NotFound"
        captured["message"] = f"{resource} not found"
        captured["status_code"] = 404
        return ("nf", 404)

    def fake_validation(details):
        captured["error"] = "ValidationError"
        captured["details"] = details
        captured["status_code"] = 400
        return ("ve", 400)

    fake_services = MagicMock()
    fake_services.get_student_transport_assignment = MagicMock(
        return_value=service_return
    )

    inner = _unwrap(route_fn)

    with (
        patch.object(tr_routes, "g", fake_g, create=True),
        patch.object(tr_routes, "request", fake_request),
        patch.object(tr_routes, "success_response", fake_success),
        patch.object(tr_routes, "error_response", fake_error),
        patch.object(tr_routes, "not_found_response", fake_not_found),
        patch.object(tr_routes, "validation_error_response", fake_validation),
        patch.object(tr_routes, "services", fake_services),
    ):
        inner()

    return captured, fake_services


# ---------------------------------------------------------------------------
# Route presence
# ---------------------------------------------------------------------------

def test_student_my_transport_endpoint_exists():
    """The route handler must be importable from the routes module."""
    from modules.transport import routes as tr_routes

    assert hasattr(tr_routes, "student_my_transport"), \
        "student_my_transport view function not found in modules.transport.routes"


# ---------------------------------------------------------------------------
# Happy path — enrolled student
# ---------------------------------------------------------------------------

def test_student_my_transport_happy_path_enrolled():
    from modules.transport import routes as tr_routes

    service_return = {
        "enrolled": True,
        "bus": {"id": "b-1", "registration_number": "KA-01-AB-1234", "capacity": 40},
        "route": {"id": "r-1", "name": "Route A"},
        "pickup_stop": {
            "id": "s-1",
            "name": "Stop A",
            "address": None,
            "scheduled_time": "07:30",
            "eta": "07:30",
        },
        "drop_stop": None,
        "driver": {"id": "d-1", "name": "Driver A", "phone": "555-0001"},
        "stops": [],
        "exceptions": [],
    }

    captured, fake_services = _call_route(
        tr_routes.student_my_transport,
        service_return=service_return,
    )

    assert captured["status_code"] == 200
    assert captured["data"] == service_return
    fake_services.get_student_transport_assignment.assert_called_once_with(
        "t-1", "u-1"
    )


# ---------------------------------------------------------------------------
# Not enrolled
# ---------------------------------------------------------------------------

def test_student_my_transport_not_enrolled_returns_200_with_flag():
    from modules.transport import routes as tr_routes

    service_return = {"enrolled": False}

    captured, _ = _call_route(
        tr_routes.student_my_transport,
        service_return=service_return,
    )

    assert captured["status_code"] == 200
    assert captured["data"] == {"enrolled": False}


# ---------------------------------------------------------------------------
# Non-student caller — service returns None → 403
# ---------------------------------------------------------------------------

def test_student_my_transport_non_student_returns_403():
    from modules.transport import routes as tr_routes

    captured, _ = _call_route(
        tr_routes.student_my_transport,
        service_return=None,
    )

    assert captured["status_code"] == 403
    assert captured.get("error") == "Forbidden"
