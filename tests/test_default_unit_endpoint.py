"""Tests for PATCH /me/default-unit handler — pure-Python, no Flask."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def test_default_unit_route_function_exists():
    """The handler is defined and registered."""
    from modules.users import routes
    assert callable(getattr(routes, "patch_default_unit", None))


def test_users_routes_imports_cleanly():
    """The routes module imports without error after the addition."""
    from modules.users import routes  # noqa: F401


def test_patch_default_unit_handler_validates_unit_belongs_to_tenant(monkeypatch):
    """When SchoolUnit.query.first() returns None, return 400 ValidationError."""
    from modules.users import routes

    fake_unit_query = MagicMock()
    fake_unit_query.filter_by.return_value = fake_unit_query
    fake_unit_query.filter.return_value = fake_unit_query
    fake_unit_query.first.return_value = None  # unit not found

    fake_school_unit = MagicMock()
    fake_school_unit.query = fake_unit_query
    fake_school_unit.deleted_at = MagicMock()
    fake_school_unit.deleted_at.is_ = lambda *a: True

    fake_user_query = MagicMock()
    fake_user = MagicMock()
    fake_user_query.filter_by.return_value = fake_user_query
    fake_user_query.first.return_value = fake_user

    fake_g = type("G", (), {"tenant_id": "t1", "current_user": type("U", (), {"id": "u1"})()})()
    fake_request = MagicMock()
    fake_request.get_json.return_value = {"default_unit_id": "ghost-unit"}

    error_response_calls = []
    def fake_error(error, message, status, details=None):
        error_response_calls.append((error, status))
        return ("error", status)

    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "request", fake_request)
    monkeypatch.setattr(routes, "error_response", fake_error)

    # Need to patch the imports inside the function. Easier: patch the modules from which they come.
    import modules.school_units.models as su_mod
    monkeypatch.setattr(su_mod, "SchoolUnit", fake_school_unit)

    handler = routes.patch_default_unit
    while hasattr(handler, "__wrapped__"):
        handler = handler.__wrapped__

    result = handler()

    assert error_response_calls and error_response_calls[0][1] == 400


def test_patch_default_unit_accepts_null(monkeypatch):
    """Setting default_unit_id to None should not validate against SchoolUnit."""
    from modules.users import routes
    from core.database import db

    fake_user = MagicMock(default_unit_id="prev-unit")
    fake_user_query = MagicMock()
    fake_user_query.filter_by.return_value = fake_user_query
    fake_user_query.first.return_value = fake_user

    # Patch User at the model module level (avoid Flask-SQLAlchemy descriptor access)
    import modules.auth.models as auth_mod
    fake_user_cls = MagicMock()
    fake_user_cls.query = fake_user_query
    monkeypatch.setattr(auth_mod, "User", fake_user_cls)

    fake_session = MagicMock()
    monkeypatch.setattr(db, "session", fake_session)

    fake_g = type("G", (), {"tenant_id": "t1", "current_user": type("U", (), {"id": "u1"})()})()
    fake_request = MagicMock()
    fake_request.get_json.return_value = {"default_unit_id": None}

    success_calls = []
    def fake_success(data=None, message=None, **kw):
        success_calls.append(data)
        return ("ok", 200)

    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "request", fake_request)
    monkeypatch.setattr(routes, "success_response", fake_success)

    handler = routes.patch_default_unit
    while hasattr(handler, "__wrapped__"):
        handler = handler.__wrapped__

    handler()

    assert fake_user.default_unit_id is None
    fake_session.commit.assert_called_once()
