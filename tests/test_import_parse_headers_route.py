"""Tests for POST /import/parse-headers route handler — pure-Python, no Flask app.

Uses the same __wrapped__ / monkeypatch pattern as test_default_unit_endpoint.py
to bypass auth/tenant decorators and call the handler directly.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _get_inner_handler(routes, handler_name: str):
    """Unwrap all decorators from the named handler."""
    fn = getattr(routes, handler_name)
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _make_xlsx_bytes(rows: list[list]) -> bytes:
    """Build a minimal .xlsx in memory and return raw bytes."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# parse_import_headers
# ---------------------------------------------------------------------------


def test_parse_import_headers_route_exists():
    """The parse_import_headers handler is defined and registered."""
    from modules.school_setup import routes

    assert callable(getattr(routes, "parse_import_headers", None))


def test_parse_import_headers_returns_headers_for_valid_xlsx(monkeypatch):
    """Returns 200 with headers list for a valid .xlsx upload."""
    from modules.school_setup import routes, import_service

    xlsx_bytes = _make_xlsx_bytes([
        ["unit_code", "programme_code", "grade", "section"],
        ["U1", "P1", "G1", "A"],
    ])

    fake_file = MagicMock()
    fake_file.filename = "classes.xlsx"
    fake_file.stream = BytesIO(xlsx_bytes)

    fake_request = MagicMock()
    fake_request.files.get.return_value = fake_file

    fake_g = type("G", (), {"tenant_id": "t1"})()

    success_calls = []

    def fake_success(data=None, message=None, **kw):
        success_calls.append(data)
        return ("ok", 200)

    monkeypatch.setattr(routes, "request", fake_request)
    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "success_response", fake_success)

    handler = _get_inner_handler(routes, "parse_import_headers")
    result = handler()

    assert result == ("ok", 200)
    assert len(success_calls) == 1
    assert success_calls[0]["headers"] == [
        "unit_code", "programme_code", "grade", "section"
    ]


def test_parse_import_headers_returns_400_when_no_file(monkeypatch):
    """Returns 400 ValidationError when no file is in the request."""
    from modules.school_setup import routes

    fake_request = MagicMock()
    fake_request.files.get.return_value = None

    fake_g = type("G", (), {"tenant_id": "t1"})()

    error_calls = []

    def fake_error(error, message, status, **kw):
        error_calls.append((error, status))
        return ("error", status)

    monkeypatch.setattr(routes, "request", fake_request)
    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "error_response", fake_error)

    handler = _get_inner_handler(routes, "parse_import_headers")
    result = handler()

    assert result == ("error", 400)
    assert error_calls[0] == ("ValidationError", 400)


def test_parse_import_headers_returns_400_for_non_xlsx(monkeypatch):
    """Returns 400 UnsupportedFileType when filename is not .xlsx."""
    from modules.school_setup import routes

    fake_file = MagicMock()
    fake_file.filename = "data.csv"
    fake_file.stream = BytesIO(b"unit_code,grade\nU1,G1\n")

    fake_request = MagicMock()
    fake_request.files.get.return_value = fake_file

    fake_g = type("G", (), {"tenant_id": "t1"})()

    error_calls = []

    def fake_error(error, message, status, **kw):
        error_calls.append((error, status))
        return ("error", status)

    monkeypatch.setattr(routes, "request", fake_request)
    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "error_response", fake_error)

    handler = _get_inner_handler(routes, "parse_import_headers")
    result = handler()

    assert result == ("error", 400)
    assert error_calls[0] == ("UnsupportedFileType", 400)


def test_parse_import_headers_propagates_headers_list(monkeypatch):
    """The returned headers list matches the first row of the uploaded file exactly."""
    from modules.school_setup import routes, import_service

    expected_headers = ["School Unit", "Programme", "Year Level", "Section", "Subject"]
    xlsx_bytes = _make_xlsx_bytes([expected_headers, ["U1", "P1", "Y1", "A", "Math"]])

    fake_file = MagicMock()
    fake_file.filename = "custom_columns.xlsx"
    fake_file.stream = BytesIO(xlsx_bytes)

    fake_request = MagicMock()
    fake_request.files.get.return_value = fake_file

    fake_g = type("G", (), {"tenant_id": "t1"})()

    captured = {}

    def fake_success(data=None, message=None, **kw):
        captured["data"] = data
        return ("ok", 200)

    monkeypatch.setattr(routes, "request", fake_request)
    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "success_response", fake_success)

    handler = _get_inner_handler(routes, "parse_import_headers")
    handler()

    assert captured["data"]["headers"] == expected_headers
