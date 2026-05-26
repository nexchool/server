"""Unit tests for teacher/student weekly timetable endpoints (nexchool Slice 3).

Pattern follows the rest of the suite: invoke the route's underlying function via
`__wrapped__` to bypass decorators, with patched `g`, `request`, and `services`.

The endpoints under test:
    GET /api/timetable/teachers/me/weekly
    GET /api/timetable/students/me/weekly
"""

from __future__ import annotations

import sys
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

SERVER_DIR = Path(__file__).resolve().parent.parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unwrap(fn):
    """Strip decorators from a Flask view to get the bare function."""
    inner = fn
    while hasattr(inner, "__wrapped__"):
        inner = inner.__wrapped__
    return inner


def _call_route(route_fn, *, service_attr, service_return, role="teacher",
                args=None, current_user_id="u-1", tenant_id="t-1"):
    """Invoke an unwrapped weekly route with mocked g + services + request.args."""
    from modules.timetable import routes as tt_routes

    fake_g = SimpleNamespace(
        current_user=SimpleNamespace(id=current_user_id),
        tenant_id=tenant_id,
    )
    fake_request = SimpleNamespace(args=args or {})

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
    setattr(fake_services, service_attr, MagicMock(return_value=service_return))

    inner = _unwrap(route_fn)

    with (
        patch.object(tt_routes, "g", fake_g),
        patch.object(tt_routes, "request", fake_request),
        patch.object(tt_routes, "success_response", fake_success),
        patch.object(tt_routes, "error_response", fake_error),
        patch.object(tt_routes, "not_found_response", fake_not_found),
        patch.object(tt_routes, "validation_error_response", fake_validation),
        patch.object(tt_routes, "services", fake_services),
    ):
        inner()

    return captured, fake_services


# ---------------------------------------------------------------------------
# Route presence + envelope shape (teacher)
# ---------------------------------------------------------------------------

def test_teacher_weekly_endpoint_exists():
    """The route handler must be importable from the routes module."""
    from modules.timetable import routes as tt_routes

    assert hasattr(tt_routes, "teacher_weekly_timetable"), \
        "teacher_weekly_timetable view function not found in modules.timetable.routes"


def test_teacher_weekly_happy_path_returns_envelope():
    from modules.timetable import routes as tt_routes

    week_start = date(2026, 5, 25)  # Monday
    service_return = {
        "academic_year": {"id": "ay-1", "name": "2025-2026"},
        "week_start_date": week_start.isoformat(),
        "week_end_date": "2026-05-31",
        "days": [
            {"day_of_week": dow, "date": (date(2026, 5, 25 + dow))
                .isoformat() if dow <= 6 else None, "periods": []}
            for dow in range(0, 7)
        ],
    }

    captured, fake_services = _call_route(
        tt_routes.teacher_weekly_timetable,
        service_attr="get_teacher_weekly_timetable",
        service_return=service_return,
    )

    assert captured["status_code"] == 200
    data = captured["data"]
    assert "academic_year" in data
    assert "week_start_date" in data
    assert "week_end_date" in data
    assert "days" in data
    assert len(data["days"]) == 7


def test_teacher_weekly_passes_week_start_param_to_service():
    from modules.timetable import routes as tt_routes

    captured, fake_services = _call_route(
        tt_routes.teacher_weekly_timetable,
        service_attr="get_teacher_weekly_timetable",
        service_return={
            "academic_year": {"id": "ay-1", "name": "2025-2026"},
            "week_start_date": "2026-05-25",
            "week_end_date": "2026-05-31",
            "days": [],
        },
        args={"week_start_date": "2026-05-27"},
    )

    fake_services.get_teacher_weekly_timetable.assert_called_once()
    kwargs = fake_services.get_teacher_weekly_timetable.call_args.kwargs
    assert kwargs["week_start_date"] == date(2026, 5, 27)
    assert kwargs["teacher_user_id"] == "u-1"
    assert kwargs["tenant_id"] == "t-1"


def test_teacher_weekly_invalid_date_returns_validation_error():
    from modules.timetable import routes as tt_routes

    captured, _ = _call_route(
        tt_routes.teacher_weekly_timetable,
        service_attr="get_teacher_weekly_timetable",
        service_return=None,
        args={"week_start_date": "not-a-date"},
    )

    assert captured["status_code"] == 400
    assert captured.get("error") == "ValidationError"


def test_teacher_weekly_none_means_caller_is_not_a_teacher():
    """When the service returns None (caller isn't a teacher), route → 403."""
    from modules.timetable import routes as tt_routes

    captured, _ = _call_route(
        tt_routes.teacher_weekly_timetable,
        service_attr="get_teacher_weekly_timetable",
        service_return=None,
    )

    assert captured["status_code"] == 403


def test_teacher_weekly_no_published_timetable_returns_404():
    from modules.timetable import routes as tt_routes
    from modules.timetable.services import TimetableNotFoundError

    fake_g = SimpleNamespace(
        current_user=SimpleNamespace(id="u-1"),
        tenant_id="t-1",
    )
    fake_request = SimpleNamespace(args={})

    captured = {}

    def fake_success(data=None, message=None, status_code=200):
        captured["status_code"] = status_code
        return ("ok", status_code)

    def fake_not_found(resource="Resource"):
        captured["status_code"] = 404
        captured["message"] = f"{resource} not found"
        return ("nf", 404)

    def fake_error(error, message=None, status_code=400, details=None):
        captured["status_code"] = status_code
        return ("err", status_code)

    def fake_validation(details):
        captured["status_code"] = 400
        return ("ve", 400)

    fake_services = MagicMock()
    fake_services.get_teacher_weekly_timetable.side_effect = TimetableNotFoundError(
        "No published timetable"
    )

    inner = _unwrap(tt_routes.teacher_weekly_timetable)
    with (
        patch.object(tt_routes, "g", fake_g),
        patch.object(tt_routes, "request", fake_request),
        patch.object(tt_routes, "success_response", fake_success),
        patch.object(tt_routes, "error_response", fake_error),
        patch.object(tt_routes, "not_found_response", fake_not_found),
        patch.object(tt_routes, "validation_error_response", fake_validation),
        patch.object(tt_routes, "services", fake_services),
    ):
        inner()

    assert captured["status_code"] == 404


# ---------------------------------------------------------------------------
# Student endpoint
# ---------------------------------------------------------------------------

def test_student_weekly_endpoint_exists():
    from modules.timetable import routes as tt_routes

    assert hasattr(tt_routes, "student_weekly_timetable")


def test_student_weekly_happy_path_returns_envelope():
    from modules.timetable import routes as tt_routes

    service_return = {
        "academic_year": {"id": "ay-1", "name": "2025-2026"},
        "week_start_date": "2026-05-25",
        "week_end_date": "2026-05-31",
        "days": [{"day_of_week": d, "date": "2026-05-25", "periods": []}
                 for d in range(0, 7)],
    }

    captured, _ = _call_route(
        tt_routes.student_weekly_timetable,
        service_attr="get_student_weekly_timetable",
        service_return=service_return,
        role="student",
    )

    assert captured["status_code"] == 200
    data = captured["data"]
    assert "academic_year" in data
    assert "days" in data
    assert len(data["days"]) == 7


def test_student_weekly_none_means_caller_is_not_a_student():
    from modules.timetable import routes as tt_routes

    captured, _ = _call_route(
        tt_routes.student_weekly_timetable,
        service_attr="get_student_weekly_timetable",
        service_return=None,
        role="student",
    )
    assert captured["status_code"] == 403


def test_student_weekly_passes_academic_year_id_override():
    from modules.timetable import routes as tt_routes

    captured, fake_services = _call_route(
        tt_routes.student_weekly_timetable,
        service_attr="get_student_weekly_timetable",
        service_return={
            "academic_year": {"id": "ay-9", "name": "2024-2025"},
            "week_start_date": "2026-05-25",
            "week_end_date": "2026-05-31",
            "days": [],
        },
        args={"academic_year_id": "ay-9"},
    )

    kwargs = fake_services.get_student_weekly_timetable.call_args.kwargs
    assert kwargs["academic_year_id"] == "ay-9"


# ---------------------------------------------------------------------------
# Service-layer normalization (pure functions, no DB)
# ---------------------------------------------------------------------------

def test_normalize_to_iso_monday_wednesday_returns_monday_of_same_week():
    from modules.timetable.services import _normalize_to_iso_monday

    wed = date(2026, 5, 27)
    assert _normalize_to_iso_monday(wed) == date(2026, 5, 25)


def test_normalize_to_iso_monday_monday_is_unchanged():
    from modules.timetable.services import _normalize_to_iso_monday

    mon = date(2026, 5, 25)
    assert _normalize_to_iso_monday(mon) == date(2026, 5, 25)


def test_normalize_to_iso_monday_sunday_returns_previous_monday():
    from modules.timetable.services import _normalize_to_iso_monday

    sun = date(2026, 5, 31)
    assert _normalize_to_iso_monday(sun) == date(2026, 5, 25)


def test_build_weekly_response_buckets_periods_into_days():
    from modules.timetable.services import _build_weekly_response

    ay = SimpleNamespace(id="ay-1", name="2025-2026")
    week_start = date(2026, 5, 25)
    week_end = date(2026, 5, 31)

    period_a = SimpleNamespace(
        id="p-1",
        day_of_week=0,  # Monday
        period_number=1,
        start_time=time(9, 0),
        end_time=time(9, 45),
        subject_id="subj-1",
        subject_ref=SimpleNamespace(id="subj-1", name="Math"),
        class_id="c-1",
        class_ref=SimpleNamespace(id="c-1", name="V-A"),
        teacher_id="t-1",
        teacher_ref=SimpleNamespace(
            id="t-1",
            user=SimpleNamespace(name="Mr. Sharma"),
        ),
        room="R-101",
    )
    period_b = SimpleNamespace(
        id="p-2",
        day_of_week=2,  # Wednesday
        period_number=1,
        start_time=time(10, 0),
        end_time=time(10, 45),
        subject_id="subj-2",
        subject_ref=SimpleNamespace(id="subj-2", name="Science"),
        class_id="c-1",
        class_ref=SimpleNamespace(id="c-1", name="V-A"),
        teacher_id="t-1",
        teacher_ref=SimpleNamespace(
            id="t-1",
            user=SimpleNamespace(name="Mr. Sharma"),
        ),
        room=None,
    )

    out = _build_weekly_response(ay, week_start, week_end, [period_a, period_b])

    assert out["academic_year"]["id"] == "ay-1"
    assert out["week_start_date"] == "2026-05-25"
    assert out["week_end_date"] == "2026-05-31"
    assert len(out["days"]) == 7

    monday = out["days"][0]
    assert monday["day_of_week"] == 0
    assert monday["date"] == "2026-05-25"
    assert len(monday["periods"]) == 1
    assert monday["periods"][0]["subject"]["name"] == "Math"

    wednesday = out["days"][2]
    assert wednesday["day_of_week"] == 2
    assert len(wednesday["periods"]) == 1
    assert wednesday["periods"][0]["subject"]["name"] == "Science"

    # Other days have no periods
    assert out["days"][1]["periods"] == []
    assert out["days"][6]["periods"] == []
