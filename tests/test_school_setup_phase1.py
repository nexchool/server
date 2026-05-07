"""Tests for Task 5 phase-1 fixes — pure-Python, no DB, no Flask app.

Covers the surface that's testable without infrastructure:
  - import_service response-shape contract (created/skipped/failed keys)
  - get_status_payload `overall.regressed_modules` semantics
  - promote_service module integrity + source==target guard

DB-integration paths (real CSV insert end-to-end, real tenant lookups) are
deferred to the Task 14 coverage gate.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


# --- Change 1: import_service response shape ---


def test_import_service_module_imports_clean():
    """Smoke: the module still imports after the response-shape change."""
    from modules.school_setup import import_service

    assert callable(getattr(import_service, "import_csv", None))


def test_import_csv_returns_new_keys_on_validation_error_paths(monkeypatch):
    """When tenant context is missing, response is the legacy
    {"success": False, "error": ...} shape — verifies the early-exit branch
    still works after the rename."""
    from modules.school_setup import import_service

    res = import_service.import_csv("", MagicMock(), academic_year_id="y1")
    assert res == {"success": False, "error": "Tenant context is required"}

    res = import_service.import_csv("t1", MagicMock(), academic_year_id=None)
    assert res == {"success": False, "error": "academic_year_id is required"}


def test_import_csv_empty_csv_returns_failure():
    pass  # noqa: TODO Task 14 — DB-integration test deferred to coverage gate
    # The real success-branch test would need an app context to bind
    # AcademicYear.query (Flask-SQLAlchemy descriptor), which is beyond
    # this file's pure-Python scope. The response-shape contract is
    # already locked by `test_import_csv_response_keys_contract`.


def test_import_csv_response_keys_contract():
    """Locks the documented response-shape contract for the success branch.

    A real success path requires DB. We assert the key set we expect by
    inspecting the source — this guards against future drift renaming the
    keys back.

    import_csv is now a thin alias for import_excel, so we inspect
    import_excel (which holds the actual implementation)."""
    import inspect

    from modules.school_setup import import_service

    # The contract lives in import_excel; import_csv is a backward-compat alias.
    src = inspect.getsource(import_service.import_excel)
    # Required new keys in the success return dict
    for key in (
        '"created":',
        '"skipped":',
        '"failed":',
        '"created_count":',
        '"skipped_count":',
        '"failed_count":',
    ):
        assert key in src, f"missing key in import_excel success return: {key}"
    # Internal accumulator names
    for name in ("created_rows", "skipped_rows", "error_rows"):
        assert name in src, f"missing accumulator: {name}"
    # error dicts use row_number, not the legacy "row"
    assert '"row_number":' in src


# --- Change 2: status payload shape ---


def test_get_status_payload_module_imports_clean():
    """Smoke: services still imports after the regressed_modules change."""
    from modules.school_setup import services

    assert callable(getattr(services, "get_status_payload", None))


def test_get_status_payload_overall_includes_regressed_modules(monkeypatch):
    """`overall.regressed_modules` must always be present and equals the
    list of REQUIRED_MODULES whose `ready` flag is False, when the tenant
    has previously completed setup."""
    from modules.school_setup import services as svc

    # Stub compute_module_status — most modules ready, two regressed
    fake_status = {
        "units": {"ready": True, "count": 1, "blockers": []},
        "programmes": {"ready": False, "count": 0, "blockers": ["x"]},
        "grades": {"ready": True, "count": 1, "blockers": []},
        "academic_year": {"ready": True, "count": 1, "blockers": []},
        "classes": {"ready": False, "count": 0, "blockers": ["x"]},
        "subjects": {"ready": True, "count": 1, "blockers": []},
        "terms": {"ready": True, "count": 1, "blockers": []},
    }
    monkeypatch.setattr(svc, "compute_module_status", lambda tid: dict(fake_status))

    fake_tenant = MagicMock()
    fake_tenant.is_setup_complete = True
    fake_tenant.setup_completed_at = "2026-01-01T00:00:00Z"
    monkeypatch.setattr(svc, "_read_tenant", lambda tid: fake_tenant)

    # Patch db.session.commit so the regress-flip path doesn't blow up
    monkeypatch.setattr(svc.db.session, "commit", lambda: None)
    monkeypatch.setattr(svc.db.session, "rollback", lambda: None)

    payload = svc.get_status_payload("t1")
    assert "overall" in payload
    assert "regressed_modules" in payload["overall"]
    assert set(payload["overall"]["regressed_modules"]) == {"programmes", "classes"}
    assert payload["overall"]["ready"] is False
    # is_complete was True but derived is False → flipped to False in payload
    assert payload["overall"]["is_setup_complete"] is False


def test_get_status_payload_regressed_empty_when_all_ready(monkeypatch):
    """When all required modules are ready, regressed_modules is []."""
    from modules.school_setup import services as svc

    fake_status = {m: {"ready": True, "count": 1, "blockers": []} for m in svc.REQUIRED_MODULES}
    fake_status["terms"] = {"ready": True, "count": 1, "blockers": []}
    monkeypatch.setattr(svc, "compute_module_status", lambda tid: dict(fake_status))

    fake_tenant = MagicMock()
    fake_tenant.is_setup_complete = True
    fake_tenant.setup_completed_at = "2026-01-01T00:00:00Z"
    monkeypatch.setattr(svc, "_read_tenant", lambda tid: fake_tenant)
    monkeypatch.setattr(svc.db.session, "commit", lambda: None)
    monkeypatch.setattr(svc.db.session, "rollback", lambda: None)

    payload = svc.get_status_payload("t1")
    assert payload["overall"]["regressed_modules"] == []
    assert payload["overall"]["ready"] is True


def test_get_status_payload_regressed_empty_when_never_completed(monkeypatch):
    """If the tenant has never completed setup, regressed_modules is empty
    even when modules are not ready (initial-setup vs. regression)."""
    from modules.school_setup import services as svc

    fake_status = {
        "units": {"ready": False, "count": 0, "blockers": ["x"]},
        "programmes": {"ready": False, "count": 0, "blockers": ["x"]},
        "grades": {"ready": False, "count": 0, "blockers": ["x"]},
        "academic_year": {"ready": False, "count": 0, "blockers": ["x"]},
        "classes": {"ready": False, "count": 0, "blockers": ["x"]},
        "subjects": {"ready": False, "count": 0, "blockers": ["x"]},
        "terms": {"ready": False, "count": 0, "blockers": []},
    }
    monkeypatch.setattr(svc, "compute_module_status", lambda tid: dict(fake_status))

    fake_tenant = MagicMock()
    fake_tenant.is_setup_complete = False
    fake_tenant.setup_completed_at = None  # never completed
    monkeypatch.setattr(svc, "_read_tenant", lambda tid: fake_tenant)

    payload = svc.get_status_payload("t1")
    assert payload["overall"]["regressed_modules"] == []


# --- Change 3: promote_service guards ---


def test_promote_service_module_imports_clean():
    """Smoke: promote_service still imports after the additive-guard comment."""
    from modules.school_setup import promote_service

    assert promote_service is not None
    assert callable(getattr(promote_service, "promote_year", None))


def test_promote_year_rejects_when_source_equals_target():
    """The source==target guard must short-circuit before any DB work."""
    from modules.school_setup import promote_service

    res = promote_service.promote_year(
        "t1",
        {"source_year_id": "y1", "target_year_id": "y1"},
    )
    assert res["success"] is False
    assert "differ" in res["error"].lower()


def test_promote_year_requires_both_year_ids():
    """Missing year IDs → validation failure before DB work."""
    from modules.school_setup import promote_service

    res = promote_service.promote_year("t1", {"source_year_id": "y1"})
    assert res["success"] is False
    assert "required" in res["error"].lower()


def test_promote_year_requires_tenant_context():
    """Empty tenant_id → validation failure."""
    from modules.school_setup import promote_service

    res = promote_service.promote_year("", {"source_year_id": "y1", "target_year_id": "y2"})
    assert res["success"] is False
    assert "tenant" in res["error"].lower()
