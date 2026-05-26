"""Smoke tests for /api/school-setup/bulk-generate route registration."""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def test_bulk_generate_route_imports_cleanly():
    """The routes module imports without error after the addition."""
    from modules.school_setup import routes  # noqa: F401


def test_bulk_generate_route_function_is_defined():
    """`post_bulk_generate` is defined and callable on the routes module."""
    from modules.school_setup import routes
    assert callable(getattr(routes, "post_bulk_generate", None))


def test_bulk_generate_route_handler_wires_to_service(monkeypatch):
    """post_bulk_generate calls bulk_generate_classes with g.tenant_id and the payload."""
    import pytest
    from modules.school_setup import routes

    captured = {}

    def fake_service(tenant_id, payload):
        captured["tenant_id"] = tenant_id
        captured["payload"] = payload
        return {"success": True, "created": [], "skipped": [], "errors": [],
                "created_count": 0, "skipped_count": 0}

    monkeypatch.setattr(routes, "bulk_generate_classes", fake_service)

    # Stub Flask globals
    fake_g = type("G", (), {"tenant_id": "tenant-1"})()
    monkeypatch.setattr(routes, "g", fake_g)

    fake_request = type("R", (), {"get_json": staticmethod(lambda: {"academic_year_id": "y1", "cells": []})})()
    monkeypatch.setattr(routes, "request", fake_request)

    # Stub success_response so we don't depend on Flask response
    monkeypatch.setattr(routes, "success_response", lambda **kw: ("OK", kw))

    # Call the inner function (bypass the decorators)
    handler = routes.post_bulk_generate
    while hasattr(handler, "__wrapped__"):
        handler = handler.__wrapped__

    if handler is routes.post_bulk_generate:
        pytest.skip("decorators don't expose __wrapped__ — covered by Task 13 Playwright API tests")

    result = handler()

    assert captured["tenant_id"] == "tenant-1"
    assert captured["payload"] == {"academic_year_id": "y1", "cells": []}
