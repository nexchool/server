"""Unit tests for the one-time login-handoff store (modules/auth/handoff.py).

Pure-Python: Redis is replaced with an in-memory fake that honors set(nx/ex)
and the atomic GET+DEL eval, so single-use / fail-closed semantics are
exercised without a live Redis.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


class FakeRedis:
    """Minimal Redis emulation: set(nx/ex) + the GET+DEL eval used by redeem."""

    def __init__(self):
        self.store = {}

    def set(self, k, v, ex=None, nx=False):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    def eval(self, script, numkeys, *keys):
        k = keys[0]
        v = self.store.get(k)
        if v is not None:
            del self.store[k]
        return v


def _patch_redis(fake):
    from core import cache

    return patch.object(cache, "redis_client", return_value=fake)


def test_issue_then_redeem_returns_payload():
    from modules.auth import handoff

    with _patch_redis(FakeRedis()):
        code = handoff.issue("admin-1", "tenant-1")
        assert code
        payload = handoff.redeem(code)
    assert payload == {"admin_id": "admin-1", "tenant_id": "tenant-1"}


def test_redeem_is_single_use():
    from modules.auth import handoff

    with _patch_redis(FakeRedis()):
        code = handoff.issue("admin-1", "tenant-1")
        first = handoff.redeem(code)
        second = handoff.redeem(code)
    assert first is not None
    assert second is None


def test_redeem_unknown_or_empty_code_returns_none():
    from modules.auth import handoff

    with _patch_redis(FakeRedis()):
        assert handoff.redeem("does-not-exist") is None
        assert handoff.redeem("") is None


def test_issue_fails_closed_when_redis_down():
    from modules.auth import handoff

    with _patch_redis(None):
        assert handoff.issue("admin-1", "tenant-1") is None


def test_redeem_fails_closed_when_redis_down():
    from modules.auth import handoff

    with _patch_redis(None):
        assert handoff.redeem("anything") is None


def test_code_is_stored_hashed_not_in_the_clear():
    from modules.auth import handoff

    fake = FakeRedis()
    with _patch_redis(fake):
        code = handoff.issue("admin-1", "tenant-1")
    # The stored key is the sha256 hash, namespaced — the raw code never appears.
    assert code is not None
    assert len(fake.store) == 1
    stored_key = next(iter(fake.store))
    assert stored_key.startswith("erp:handoff:v1:")
    assert code not in stored_key


def test_issue_sets_ttl_and_nx():
    from modules.auth import handoff

    captured = {}

    class RecordingRedis(FakeRedis):
        def set(self, k, v, ex=None, nx=False):
            captured["ex"] = ex
            captured["nx"] = nx
            return super().set(k, v, ex=ex, nx=nx)

    with _patch_redis(RecordingRedis()):
        handoff.issue("admin-1", "tenant-1", ttl_seconds=90)
    assert captured["ex"] == 90
    assert captured["nx"] is True
