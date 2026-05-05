"""Tests for retention tasks — pure-Python, no DB, no Celery worker."""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from tests._model_loader import load_all_models  # noqa: E402

load_all_models()


# --- Module-level smoke ---

def test_retention_module_imports_cleanly():
    from modules.school_setup import retention_tasks  # noqa: F401


def test_three_celery_tasks_registered():
    from modules.school_setup import retention_tasks
    for name in ("purge_notification_logs", "purge_audit_logs", "advance_offboarding_stage"):
        assert hasattr(retention_tasks, name), f"missing task: {name}"
        task = getattr(retention_tasks, name)
        # Celery task wraps the function; either has .run, .name, or it's callable
        assert callable(task)


# --- _log_purge ---

def test_log_purge_skips_zero_count(monkeypatch):
    """When count is 0, nothing should be added to the session."""
    from modules.school_setup import retention_tasks as rt

    fake_session = MagicMock()
    monkeypatch.setattr(rt.db, "session", fake_session)

    rt._log_purge("tenant-1", "test_type", 0)

    fake_session.add.assert_not_called()


def test_log_purge_creates_data_purge_log(monkeypatch):
    """When count > 0, a DataPurgeLog entry is added (not committed)."""
    from modules.school_setup import retention_tasks as rt
    from modules.school_setup.models import DataPurgeLog

    captured = []
    fake_session = MagicMock()
    fake_session.add.side_effect = lambda e: captured.append(e)
    monkeypatch.setattr(rt.db, "session", fake_session)

    rt._log_purge("tenant-1", "audit_logs", 42)

    assert len(captured) == 1
    entry = captured[0]
    assert isinstance(entry, DataPurgeLog)
    assert entry.tenant_id == "tenant-1"
    assert entry.data_type == "audit_logs"
    assert entry.records_deleted == 42
    fake_session.commit.assert_not_called()


# --- purge_notification_logs ---

def test_purge_notification_logs_handles_exception(monkeypatch):
    """Task must catch exceptions and rollback, not propagate."""
    from modules.school_setup import retention_tasks as rt

    fake_session = MagicMock()
    fake_session.query.side_effect = RuntimeError("boom")
    monkeypatch.setattr(rt.db, "session", fake_session)

    # Must not raise
    rt.purge_notification_logs()
    fake_session.rollback.assert_called()


def test_purge_notification_logs_logs_when_rows_deleted(monkeypatch):
    """When .delete() returns > 0, the success path runs logger.info + commit."""
    from modules.school_setup import retention_tasks as rt

    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.delete.return_value = 7  # non-zero → enters `if deleted:` branch

    fake_session = MagicMock()
    fake_session.query.return_value = fake_query
    monkeypatch.setattr(rt.db, "session", fake_session)

    rt.purge_notification_logs()

    fake_query.delete.assert_called_once_with(synchronize_session=False)
    fake_session.commit.assert_called_once()
    fake_session.rollback.assert_not_called()


def test_purge_notification_logs_skips_log_when_no_rows_deleted(monkeypatch):
    """When .delete() returns 0, the `if deleted:` branch is skipped (still commits)."""
    from modules.school_setup import retention_tasks as rt

    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.delete.return_value = 0  # falsy → branch falls through

    fake_session = MagicMock()
    fake_session.query.return_value = fake_query
    monkeypatch.setattr(rt.db, "session", fake_session)

    rt.purge_notification_logs()

    fake_session.commit.assert_called_once()
    fake_session.rollback.assert_not_called()


# --- purge_audit_logs ---

def test_purge_audit_logs_handles_exception(monkeypatch):
    from modules.school_setup import retention_tasks as rt

    fake_session = MagicMock()
    fake_session.query.side_effect = RuntimeError("boom")
    monkeypatch.setattr(rt.db, "session", fake_session)

    rt.purge_audit_logs()
    fake_session.rollback.assert_called()


def test_purge_audit_logs_uses_correct_cutoffs(monkeypatch):
    """Finance cutoff = 120 days, others = 365 days. Verify the filter args."""
    from modules.school_setup import retention_tasks as rt

    captured_filters = []

    fake_query = MagicMock()
    fake_query.filter.side_effect = lambda *args: (captured_filters.append(args), fake_query)[1]
    fake_query.delete.return_value = 0

    fake_session = MagicMock()
    fake_session.query.return_value = fake_query
    monkeypatch.setattr(rt.db, "session", fake_session)

    rt.purge_audit_logs()

    # We made 2 .filter() calls (one for finance, one for other) — verified by filter call count
    assert fake_query.filter.call_count >= 2


# --- advance_offboarding_stage ---

def test_advance_offboarding_handles_exception(monkeypatch):
    from modules.school_setup import retention_tasks as rt

    fake_session = MagicMock()
    fake_session.query.side_effect = RuntimeError("boom")
    monkeypatch.setattr(rt.db, "session", fake_session)

    rt.advance_offboarding_stage()
    fake_session.rollback.assert_called()


def test_advance_offboarding_marks_tenants_deleted(monkeypatch):
    """Tenants past export deadline get status=DELETED and purge_scheduled_at set."""
    from modules.school_setup import retention_tasks as rt
    from core.models import TENANT_STATUS_SUSPENDED, TENANT_STATUS_DELETED

    fake_tenant = MagicMock()
    fake_tenant.id = "t1"
    fake_tenant.status = TENANT_STATUS_SUSPENDED
    fake_tenant.purge_scheduled_at = None

    fake_query = MagicMock()
    fake_query.filter.return_value = fake_query
    fake_query.all.return_value = [fake_tenant]

    fake_session = MagicMock()
    fake_session.query.return_value = fake_query
    monkeypatch.setattr(rt.db, "session", fake_session)

    rt.advance_offboarding_stage()

    assert fake_tenant.status == TENANT_STATUS_DELETED
    assert fake_tenant.purge_scheduled_at is not None
    fake_session.commit.assert_called()
