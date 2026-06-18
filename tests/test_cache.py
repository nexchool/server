"""Unit tests for the fail-open Redis cache helper (core/cache.py).

No real Redis or DB needed: the Redis client is mocked, and the fail-open paths
are exercised by making ``_redis()`` return ``None``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from core import cache


def test_key_is_namespaced_and_versioned():
    assert cache.key("perms", "u-1") == "erp:cache:v1:perms:u-1"
    assert cache.key("plan", "t-9") == "erp:cache:v1:plan:t-9"


def test_disabled_cache_is_a_noop(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "false")
    with patch.object(cache, "_redis") as redis_factory:
        assert cache.get_json("erp:cache:v1:x") is None
        cache.set_json("erp:cache:v1:x", {"a": 1}, 60)
        redis_factory.assert_not_called()  # short-circuits before touching Redis


def test_fail_open_when_redis_unavailable():
    with patch.object(cache, "_redis", return_value=None):
        assert cache.get_json("k") is None      # miss, no exception
        cache.set_json("k", {"a": 1}, 60)        # no-op, no exception
        cache.delete("k")                        # no-op
        cache.delete_pattern("k:*")              # no-op


def test_get_or_set_falls_back_to_loader_when_redis_down():
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return ["student.read"]

    with patch.object(cache, "_redis", return_value=None):
        assert cache.get_or_set_json("k", 60, loader) == ["student.read"]
        assert cache.get_or_set_json("k", 60, loader) == ["student.read"]
        assert calls["n"] == 2  # Redis down -> always a miss -> loader runs each time


def test_get_set_roundtrip_with_mock_redis():
    store = {}
    fake = MagicMock()
    fake.get.side_effect = lambda k: store.get(k)
    fake.set.side_effect = lambda k, v, ex=None: store.__setitem__(k, v)
    with patch.object(cache, "_redis", return_value=fake), \
            patch.object(cache, "cache_enabled", return_value=True):
        cache.set_json("erp:cache:v1:perms:u-1", ["a", "b"], 120)
        assert cache.get_json("erp:cache:v1:perms:u-1") == ["a", "b"]
        assert store["erp:cache:v1:perms:u-1"] == '["a","b"]'  # JSON-serialised


def test_get_or_set_uses_cache_hit_without_calling_loader():
    store = {}
    fake = MagicMock()
    fake.get.side_effect = lambda k: store.get(k)
    fake.set.side_effect = lambda k, v, ex=None: store.__setitem__(k, v)
    loader = MagicMock(return_value=["fresh"])
    with patch.object(cache, "_redis", return_value=fake), \
            patch.object(cache, "cache_enabled", return_value=True):
        assert cache.get_or_set_json("k", 60, loader) == ["fresh"]  # miss -> loader
        loader.reset_mock()
        assert cache.get_or_set_json("k", 60, loader) == ["fresh"]  # hit -> no loader
        loader.assert_not_called()
