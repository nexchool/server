"""Tests for the notifications dispatcher's silent-skip behavior.

The dispatcher is the chokepoint: every caller (auth, fees, attendance,
transport, etc.) goes through it. When a tenant has the `notifications`
feature disabled, no caller should need to know — the dispatcher absorbs
the skip and returns False for every requested channel.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import core.feature_flags as ff_mod
import modules.notifications.services.dispatcher as dispatcher_mod


def _set_feature(monkeypatch, enabled: bool):
    """Patch is_feature_enabled at the import site the dispatcher reads."""
    monkeypatch.setattr(ff_mod, "is_feature_enabled", lambda _t, _k: enabled)


def test_dispatcher_silent_skip_when_notifications_disabled(monkeypatch):
    """No strategy should run; result is False per requested channel."""
    d = dispatcher_mod.NotificationDispatcher()
    fake_strategy = MagicMock()
    fake_strategy.send.side_effect = AssertionError("strategy invoked while disabled")
    d._strategies = {ch: fake_strategy for ch in d._strategies}

    _set_feature(monkeypatch, False)

    result = d.dispatch(
        user_id="user-1",
        tenant_id="tenant-1",
        notification_type="FEE_REMINDER",
        channels=["EMAIL", "SMS", "IN_APP"],
        title="Hi",
        body="body",
    )
    assert result == {"EMAIL": False, "SMS": False, "IN_APP": False}
    fake_strategy.send.assert_not_called()


def test_dispatcher_runs_when_notifications_enabled(monkeypatch):
    """Sanity: when feature is on, strategies are invoked."""
    d = dispatcher_mod.NotificationDispatcher()
    fake = MagicMock()
    fake.send.return_value = True
    d._strategies = {ch: fake for ch in d._strategies}

    _set_feature(monkeypatch, True)

    result = d.dispatch(
        user_id="user-1",
        tenant_id="tenant-1",
        notification_type="FEE_REMINDER",
        channels=["EMAIL"],
        title="Hi",
    )
    assert result == {"EMAIL": True}
    fake.send.assert_called_once()


def test_dispatcher_no_tenant_id_skips_feature_check(monkeypatch):
    """Dispatch with no tenant_id (rare; only platform-level admin emails)
    must not short-circuit. We test the contract."""
    d = dispatcher_mod.NotificationDispatcher()
    fake = MagicMock()
    fake.send.return_value = True
    d._strategies = {ch: fake for ch in d._strategies}

    # Even though feature is disabled, falsy tenant_id bypasses the gate.
    _set_feature(monkeypatch, False)

    result = d.dispatch(
        user_id="user-1",
        tenant_id="",
        notification_type="ADMIN_CREDENTIALS",
        channels=["EMAIL"],
        title="Hi",
    )
    assert result == {"EMAIL": True}


def test_dispatcher_strategy_exception_isolates_channels(monkeypatch):
    """If one strategy throws, others still run and return their own result."""
    d = dispatcher_mod.NotificationDispatcher()
    boom = MagicMock()
    boom.send.side_effect = RuntimeError("boom")
    ok = MagicMock()
    ok.send.return_value = True
    d._strategies = {"EMAIL": boom, "IN_APP": ok, "SMS": ok, "PUSH": ok}

    _set_feature(monkeypatch, True)

    result = d.dispatch(
        user_id="u",
        tenant_id="t",
        notification_type="X",
        channels=["EMAIL", "IN_APP"],
        title="Hi",
    )
    assert result == {"EMAIL": False, "IN_APP": True}
