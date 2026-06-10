"""Tests for GET /api/dashboard error handling.

Pure-Python, no Flask test client — unwraps the handler and monkeypatches its
collaborators, in the same style as tests/test_audit_routes.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _unwrap(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def test_get_dashboard_does_not_leak_exception_text(monkeypatch):
    """A failure inside build_dashboard must NOT surface the raw exception text
    (which can contain DSNs / internals) to the client — it returns a generic
    message and logs the real error server-side."""
    from modules.dashboard import routes

    captured = {}

    def fake_error(code, message, status):
        captured.update(code=code, message=message, status=status)
        return (message, status)

    def boom():
        raise RuntimeError("postgres://user:pw@db-host:5432/secretdb timed out")

    monkeypatch.setattr(routes.service, "build_dashboard", boom)
    monkeypatch.setattr(routes, "error_response", fake_error)

    handler = _unwrap(routes.get_dashboard)
    handler()

    assert captured["status"] == 500
    assert captured["code"] == "DashboardError"
    assert "postgres://" not in captured["message"]
    assert "secretdb" not in captured["message"]


def test_get_dashboard_returns_data_on_success(monkeypatch):
    """Happy path returns the service payload via success_response."""
    from modules.dashboard import routes

    captured = {}

    def fake_success(data=None, **kw):
        captured["data"] = data
        return ("ok", 200)

    monkeypatch.setattr(routes.service, "build_dashboard", lambda: {"overview": {"x": 1}})
    monkeypatch.setattr(routes, "success_response", fake_success)

    handler = _unwrap(routes.get_dashboard)
    handler()

    assert captured["data"] == {"overview": {"x": 1}}
