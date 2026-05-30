"""Unit tests for POST /api/auth/password/change (nexchool Slice 4).

Same unit-mock pattern as tests/timetable/test_weekly_endpoints.py: invoke the
route's underlying function via __wrapped__ to bypass decorators, with patched
g, request, and the services module.
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


def _call_route(
    *,
    body,
    service_side_effect=None,
    service_return=None,
    current_user_id="u-1",
    tenant_id="t-1",
):
    from modules.auth import routes as auth_routes

    fake_g = SimpleNamespace(
        current_user=SimpleNamespace(id=current_user_id),
        tenant_id=tenant_id,
    )
    fake_request = SimpleNamespace(get_json=lambda *args, **kwargs: body)

    captured = {}

    def fake_success(data=None, message=None, status_code=200):
        captured["data"] = data
        captured["message"] = message
        captured["status_code"] = status_code
        return ("ok", status_code)

    def fake_error(error=None, message=None, status_code=400, details=None):
        captured["error"] = error
        captured["message"] = message
        captured["status_code"] = status_code
        return ("err", status_code)

    # Build a fake `services` module with PasswordChangeError + change_password
    class FakePasswordChangeError(Exception):
        def __init__(self, code, message=""):
            super().__init__(message or code)
            self.code = code

    fake_services = MagicMock()
    fake_services.PasswordChangeError = FakePasswordChangeError
    if service_side_effect is not None:
        fake_services.change_password = MagicMock(
            side_effect=service_side_effect
        )
    else:
        fake_services.change_password = MagicMock(
            return_value=service_return or {"revoked_sessions": 0}
        )

    inner = _unwrap(auth_routes.change_password)

    with (
        patch.object(auth_routes, "g", fake_g, create=True),
        patch.object(auth_routes, "request", fake_request),
        patch.object(auth_routes, "success_response", fake_success),
        patch.object(auth_routes, "error_response", fake_error),
        patch.object(auth_routes, "services", fake_services, create=True),
    ):
        inner()

    return captured, fake_services, FakePasswordChangeError


def test_change_password_endpoint_exists():
    from modules.auth import routes as auth_routes

    assert hasattr(auth_routes, "change_password"), \
        "change_password view function not found in modules.auth.routes"


def test_change_password_happy_path_returns_200():
    captured, fake_services, _ = _call_route(
        body={
            "current_password": "OldPass12",
            "new_password": "NewPass34",
        },
    )

    assert captured["status_code"] == 200
    assert captured["data"] == {"revoked_sessions": 0}
    fake_services.change_password.assert_called_once()
    kwargs = fake_services.change_password.call_args.kwargs
    assert kwargs["user_id"] == "u-1"
    assert kwargs["current_password"] == "OldPass12"
    assert kwargs["new_password"] == "NewPass34"


def test_change_password_wrong_current_returns_401():
    def boom(**_):
        from modules.auth import routes as auth_routes
        raise auth_routes.services.PasswordChangeError("current_password_invalid")

    captured, _, _ = _call_route(
        body={"current_password": "wrong", "new_password": "NewPass34"},
        service_side_effect=boom,
    )

    assert captured["status_code"] == 401
    assert captured.get("error") == "current_password_invalid"


def test_change_password_weak_new_returns_422():
    def boom(**_):
        from modules.auth import routes as auth_routes
        raise auth_routes.services.PasswordChangeError("password_weak")

    captured, _, _ = _call_route(
        body={"current_password": "OldPass12", "new_password": "short"},
        service_side_effect=boom,
    )

    assert captured["status_code"] == 422
    assert captured.get("error") == "password_weak"


def test_change_password_same_as_current_returns_422():
    def boom(**_):
        from modules.auth import routes as auth_routes
        raise auth_routes.services.PasswordChangeError("password_unchanged")

    captured, _, _ = _call_route(
        body={"current_password": "OldPass12", "new_password": "OldPass12"},
        service_side_effect=boom,
    )

    assert captured["status_code"] == 422
    assert captured.get("error") == "password_unchanged"
