"""Subscription enforcement decorator (`require_active_subscription`).

Pure-logic tests for `_subscription_state`. The decorator and its cache key
off `g`, but the resolver itself is the part that decides allow/block — so
that's what we cover. `Tenant.query` is monkeypatched away from the real
SQLAlchemy session to avoid Flask app-context.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import core.decorators.subscription as subscription_module


def _install_tenant_lookup(monkeypatch, status, trial_ends_at):
    """Stub `db.session.query(Tenant.status, Tenant.trial_ends_at)` to
    return (status, trial_ends_at) — or None if status is `None`."""
    row = (status, trial_ends_at) if status is not None or trial_ends_at is not None else None
    fake_query = MagicMock()
    fake_query.filter.return_value.first.return_value = row
    fake_session = MagicMock()
    fake_session.query.return_value = fake_query
    monkeypatch.setattr(subscription_module.db, "session", fake_session)


def test_active_tenant_allows_writes(monkeypatch):
    _install_tenant_lookup(monkeypatch, "active", None)
    monkeypatch.setattr(subscription_module, "g", SimpleNamespace())
    state = subscription_module.get_subscription_state("t1")
    assert state["allow_writes"] is True
    assert state["reason"] == "Active"


def test_trial_within_window_allows_writes(monkeypatch):
    future = datetime.utcnow() + timedelta(days=5)
    _install_tenant_lookup(monkeypatch, "trial", future)
    monkeypatch.setattr(subscription_module, "g", SimpleNamespace())
    state = subscription_module.get_subscription_state("t1")
    assert state["allow_writes"] is True
    assert state["reason"] == "Trial"
    assert state["trial_ends_at"] is not None


def test_trial_with_no_end_date_allows_writes(monkeypatch):
    _install_tenant_lookup(monkeypatch, "trial", None)
    monkeypatch.setattr(subscription_module, "g", SimpleNamespace())
    state = subscription_module.get_subscription_state("t1")
    assert state["allow_writes"] is True
    assert state["reason"] == "Trial"


def test_trial_expired_blocks_writes(monkeypatch):
    past = datetime.utcnow() - timedelta(days=1)
    _install_tenant_lookup(monkeypatch, "trial", past)
    monkeypatch.setattr(subscription_module, "g", SimpleNamespace())
    state = subscription_module.get_subscription_state("t1")
    assert state["allow_writes"] is False
    assert state["reason"] == "TrialExpired"
    assert "trial_ends_at" in state


def test_suspended_tenant_blocks_writes(monkeypatch):
    _install_tenant_lookup(monkeypatch, "suspended", None)
    monkeypatch.setattr(subscription_module, "g", SimpleNamespace())
    state = subscription_module.get_subscription_state("t1")
    assert state["allow_writes"] is False
    assert state["reason"] == "SubscriptionSuspended"


def test_deleted_tenant_blocks_writes(monkeypatch):
    _install_tenant_lookup(monkeypatch, "deleted", None)
    monkeypatch.setattr(subscription_module, "g", SimpleNamespace())
    state = subscription_module.get_subscription_state("t1")
    assert state["allow_writes"] is False
    assert state["reason"] == "TenantDeleted"


def test_tenant_not_found_blocks_writes(monkeypatch):
    _install_tenant_lookup(monkeypatch, None, None)
    monkeypatch.setattr(subscription_module, "g", SimpleNamespace())
    state = subscription_module.get_subscription_state("missing")
    assert state["allow_writes"] is False
    assert state["reason"] == "TenantNotFound"


def test_unknown_status_fails_closed(monkeypatch):
    _install_tenant_lookup(monkeypatch, "weird-status", None)
    monkeypatch.setattr(subscription_module, "g", SimpleNamespace())
    state = subscription_module.get_subscription_state("t1")
    assert state["allow_writes"] is False
    assert state["reason"] == "SubscriptionUnknown"


def test_state_cached_on_g(monkeypatch):
    """Same tenant_id within a request → DB only hit once."""
    _install_tenant_lookup(monkeypatch, "active", None)
    monkeypatch.setattr(subscription_module, "g", SimpleNamespace())
    s1 = subscription_module.get_subscription_state("t1")
    # Flip the stub to "suspended" — cached result must still win.
    _install_tenant_lookup(monkeypatch, "suspended", None)
    s2 = subscription_module.get_subscription_state("t1")
    assert s1 is s2  # same dict object → cached
