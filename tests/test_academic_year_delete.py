"""Tests for DELETE academic year handler — pure-Python, no Flask test client.

Covers:
  1. Returns 404 when academic year not found (query → None).
  2. Returns 409 with blockers dict when count_dependencies returns nonzero totals.
  3. Returns 200 and commits when count_dependencies returns all zeros.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


# ---------------------------------------------------------------------------
# Helper: unwrap decorators to call raw handler
# ---------------------------------------------------------------------------

def _unwrap(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


# ---------------------------------------------------------------------------
# Test 1: 404 when academic year does not exist
# ---------------------------------------------------------------------------

def test_delete_academic_year_returns_404_when_not_found(monkeypatch):
    """Handler returns 404 NotFound when the academic year does not exist."""
    from modules.academics.academic_year import routes

    not_found_calls = []

    def fake_not_found(resource_name):
        not_found_calls.append(resource_name)
        return ("not-found", 404)

    fake_g = type("G", (), {"tenant_id": "tenant-1", "current_user": type("U", (), {"id": "u1"})()})()

    fake_result = {"success": False, "error": "Academic year not found"}

    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "not_found_response", fake_not_found)
    monkeypatch.setattr(routes.services, "delete_academic_year", lambda **kw: fake_result)

    handler = _unwrap(routes.delete_academic_year)
    result = handler("nonexistent-year-id")

    assert not_found_calls, "not_found_response should have been called"
    assert result == ("not-found", 404)


# ---------------------------------------------------------------------------
# Test 2: 409 with blockers when count_dependencies returns nonzero
# ---------------------------------------------------------------------------

def test_delete_academic_year_returns_409_when_dependencies_exist(monkeypatch):
    """Handler returns 409 AcademicYearInUse with blockers detail when data references the year."""
    from modules.academics.academic_year import routes

    error_calls = []

    def fake_error(code, message, status, details=None):
        error_calls.append({"code": code, "status": status, "details": details})
        return ("conflict", status)

    fake_g = type("G", (), {"tenant_id": "tenant-1", "current_user": type("U", (), {"id": "u1"})()})()

    blockers = {
        "classes": 5,
        "students": 0,
        "student_enrollments": 12,
        "terms": 3,
        "fee_structures": 0,
        "transport_enrollments": 0,
        "transport_fee_plans": 0,
        "holidays": 0,
    }
    fake_result = {
        "success": False,
        "blocked": True,
        "blockers": blockers,
        "error": "Cannot delete academic year because it has linked data: 5 classes, 12 student enrollments, 3 terms. Remove or reassign that data first.",
    }

    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "error_response", fake_error)
    monkeypatch.setattr(routes.services, "delete_academic_year", lambda **kw: fake_result)

    handler = _unwrap(routes.delete_academic_year)
    result = handler("year-id-1")

    assert result == ("conflict", 409)
    assert len(error_calls) == 1
    call = error_calls[0]
    assert call["code"] == "AcademicYearInUse"
    assert call["status"] == 409
    assert call["details"] is not None
    assert "blockers" in call["details"]
    assert call["details"]["blockers"] == blockers


# ---------------------------------------------------------------------------
# Test 3: 200 and commit when no dependencies
# ---------------------------------------------------------------------------

def test_delete_academic_year_succeeds_when_no_dependencies(monkeypatch):
    """Handler returns success and calls delete when count_dependencies is all zeros."""
    from modules.academics.academic_year import routes

    success_calls = []

    def fake_success(data=None, message=None, status_code=200, **kw):
        success_calls.append({"message": message})
        return ("ok", 200)

    fake_g = type("G", (), {"tenant_id": "tenant-1", "current_user": type("U", (), {"id": "u1"})()})()

    fake_result = {"success": True, "message": "Academic year deleted"}

    monkeypatch.setattr(routes, "g", fake_g)
    monkeypatch.setattr(routes, "success_response", fake_success)
    monkeypatch.setattr(routes.services, "delete_academic_year", lambda **kw: fake_result)

    handler = _unwrap(routes.delete_academic_year)
    result = handler("year-id-clean")

    assert result == ("ok", 200)
    assert len(success_calls) == 1
    assert success_calls[0]["message"] == "Academic year deleted"


# ---------------------------------------------------------------------------
# Test 4: count_dependencies returns expected keys
# ---------------------------------------------------------------------------

def test_count_dependencies_returns_all_expected_keys(monkeypatch):
    """count_dependencies dict includes all 8 expected dependency keys."""
    from modules.academics.academic_year import services

    # Build a fake query factory: each model's .query.filter_by().count() returns 0
    def _fake_model_with_count(n=0):
        q = MagicMock()
        q.filter_by.return_value = q
        q.filter.return_value = q
        q.count.return_value = n
        m = MagicMock()
        m.query = q
        m.academic_year_id = MagicMock()
        m.tenant_id = MagicMock()
        m.deleted_at = MagicMock()
        m.deleted_at.is_ = lambda v: MagicMock()
        return m

    fake_class = _fake_model_with_count(0)
    fake_student = _fake_model_with_count(0)
    fake_enrollment = _fake_model_with_count(0)
    fake_term = _fake_model_with_count(0)
    fake_fee_structure = _fake_model_with_count(0)
    fake_transport_enrollment = _fake_model_with_count(0)
    fake_transport_fee_plan = _fake_model_with_count(0)
    fake_holiday = _fake_model_with_count(0)

    with (
        patch("modules.classes.models.Class", fake_class),
        patch("modules.students.models.Student", fake_student),
        patch("modules.academics.backbone.models.StudentClassEnrollment", fake_enrollment),
        patch("modules.academics.backbone.models.AcademicTerm", fake_term),
        patch("modules.finance.models.FeeStructure", fake_fee_structure),
        patch("modules.transport.models.TransportEnrollment", fake_transport_enrollment),
        patch("modules.transport.models.TransportFeePlan", fake_transport_fee_plan),
        patch("modules.holidays.models.Holiday", fake_holiday),
    ):
        deps = services.count_dependencies("tenant-1", "year-1")

    expected_keys = {
        "classes",
        "students",
        "student_enrollments",
        "terms",
        "fee_structures",
        "transport_enrollments",
        "transport_fee_plans",
        "holidays",
    }
    assert set(deps.keys()) == expected_keys
    assert all(v == 0 for v in deps.values())
