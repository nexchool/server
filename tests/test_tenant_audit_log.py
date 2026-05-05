"""Tests for log_tenant_action — pure-Python, no DB, no Flask app."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def test_log_tenant_action_calls_db_session_add(monkeypatch):
    """log_tenant_action must call db.session.add with a TenantAuditLog instance."""
    from modules.audit import services
    from modules.audit.models import TenantAuditLog

    captured = []
    fake_session = MagicMock()
    fake_session.add.side_effect = lambda entry: captured.append(entry)
    monkeypatch.setattr(services.db, "session", fake_session)

    services.log_tenant_action(
        module="finance",
        action="fee_payment_recorded",
        resource_type="fee_invoice",
        description="Recorded ₹5,000 payment",
        tenant_id="tenant-1",
        actor_user_id="user-1",
        actor_name="Admin",
        actor_role="admin",
        resource_id="inv-123",
        meta={"amount": 5000},
    )

    assert len(captured) == 1
    entry = captured[0]
    assert isinstance(entry, TenantAuditLog)
    assert entry.module == "finance"
    assert entry.action == "fee_payment_recorded"
    assert entry.tenant_id == "tenant-1"
    assert entry.actor_user_id == "user-1"
    assert entry.actor_name == "Admin"
    assert entry.actor_role == "admin"
    assert entry.resource_type == "fee_invoice"
    assert entry.resource_id == "inv-123"
    assert entry.description == "Recorded ₹5,000 payment"
    assert entry.meta == {"amount": 5000}


def test_log_tenant_action_does_not_call_commit(monkeypatch):
    """log_tenant_action must NOT call db.session.commit — caller owns transaction."""
    from modules.audit import services

    fake_session = MagicMock()
    monkeypatch.setattr(services.db, "session", fake_session)

    services.log_tenant_action(
        module="students",
        action="student_enrolled",
        resource_type="student",
        description="Student enrolled",
        tenant_id="tenant-1",
    )

    fake_session.add.assert_called_once()
    fake_session.commit.assert_not_called()
    fake_session.flush.assert_not_called()


def test_log_tenant_action_defaults_actor_to_system(monkeypatch):
    """When actor_name/actor_role not given, default to 'System'/'system'."""
    from modules.audit import services

    captured = []
    fake_session = MagicMock()
    fake_session.add.side_effect = lambda entry: captured.append(entry)
    monkeypatch.setattr(services.db, "session", fake_session)

    services.log_tenant_action(
        module="setup",
        action="celery_purge",
        resource_type="audit_log",
        description="Auto-purged old audit logs",
        tenant_id="tenant-1",
    )

    entry = captured[0]
    assert entry.actor_name == "System"
    assert entry.actor_role == "system"
    assert entry.actor_user_id is None


def test_log_tenant_action_meta_can_be_none(monkeypatch):
    """Calling without meta should not error and entry.meta should be None."""
    from modules.audit import services

    captured = []
    fake_session = MagicMock()
    fake_session.add.side_effect = lambda entry: captured.append(entry)
    monkeypatch.setattr(services.db, "session", fake_session)

    services.log_tenant_action(
        module="setup",
        action="completed",
        resource_type="tenant",
        description="Setup completed",
        tenant_id="tenant-1",
    )

    assert captured[0].meta is None
