"""Redis holds three unrelated things, and only one of them may be evicted.

Production runs a single 100 MB Redis with `--maxmemory-policy allkeys-lru`,
and `.env.prod` points the cache, the Celery broker, the Celery result backend
**and** the rate limiter at the same database. Under memory pressure LRU
therefore deletes whichever key was touched least recently, with no regard for
what it was:

  * a **queued task message** — the email, notification or PDF simply never
    happens, and nothing anywhere reports it
  * a **login rate-limit counter** — the lockout quietly starts again from zero

The cache is the only one of the three that may be discarded, and it is
already written to survive that: every operation in `core/cache.py` swallows
its exception and falls back to the database.

Two things this file pins, both of which reduce what Redis has to hold:
results are not stored at all (nothing reads them), and the rate limiter can
be pointed at its own database instead of sharing the broker's.
"""

from __future__ import annotations

import pytest


def test_task_results_are_not_stored(flask_app):
    """Every dispatch is fire-and-forget, so a result backend is dead weight.

    Verified across the module: no `AsyncResult`, no blocking `.get(timeout=)`,
    and not one call site assigns what `.delay()` returns. Storing a result for
    each of them fills the same Redis the broker depends on, and Celery keeps
    them for a day by default.
    """
    from celery_app import make_celery

    celery = make_celery(flask_app)

    assert celery.conf.task_ignore_result is True, (
        "results nobody reads are the largest avoidable consumer of a Redis "
        "the broker shares"
    )


def test_the_rate_limiter_can_be_given_its_own_database(flask_app, monkeypatch):
    """`.env.prod` set RATELIMIT_STORAGE_URL, which nothing has ever read.

    Flask-Limiter's key is `RATELIMIT_STORAGE_URI`, and `core/extensions.py`
    only ever `setdefault`s it from `REDIS_URL` — so the intended separation
    never took effect and the limiter has been sharing database 0 with the
    broker all along.
    """
    from core.extensions import _configure_rate_limit_storage

    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "redis://redis:6379/3")
    config: dict = {}

    _configure_rate_limit_storage(config)

    assert config["RATELIMIT_STORAGE_URI"] == "redis://redis:6379/3"


def test_it_still_falls_back_to_the_shared_url(flask_app, monkeypatch):
    """Nothing breaks for an environment that has not separated them yet."""
    from core.extensions import _configure_rate_limit_storage

    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)
    config: dict = {}

    _configure_rate_limit_storage(config)

    assert config["RATELIMIT_STORAGE_URI"] == "redis://redis:6379/0"


def test_no_redis_leaves_the_limiter_in_memory(flask_app, monkeypatch):
    """A rate limiter should degrade, not take the API down with it."""
    from core.extensions import _configure_rate_limit_storage

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)
    config: dict = {}

    _configure_rate_limit_storage(config)

    assert "RATELIMIT_STORAGE_URI" not in config


def test_the_cache_survives_a_redis_that_refuses_writes(flask_app, monkeypatch):
    """`noeviction` answers OOM on write once full — that must not 500.

    This is what makes the eviction policy safe to change: the cache is the
    only tenant of Redis allowed to lose data, and it already treats every
    failure as a miss.
    """
    from core import cache

    class _Full:
        def get(self, *a, **k):
            raise RuntimeError("OOM command not allowed when used memory > 'maxmemory'")

        def set(self, *a, **k):
            raise RuntimeError("OOM command not allowed when used memory > 'maxmemory'")

    monkeypatch.setattr(cache, "_redis", lambda: _Full())
    monkeypatch.setattr(cache, "cache_enabled", lambda: True)

    cache.set_json("erp:cache:v1:probe", {"a": 1}, 60)          # must not raise
    assert cache.get_json("erp:cache:v1:probe") is None          # reads as a miss
