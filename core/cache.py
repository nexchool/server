"""Redis-backed cache for frequently-read, rarely-changed data.

**Fail-open by design:** every operation degrades to a cache miss / no-op if
Redis is unavailable or errors, so a Redis outage can never break a request —
callers always fall back to the source of truth (usually the DB).

Keys are namespaced + versioned: ``erp:cache:v1:<...>``. Tenant-scoped data MUST
include the ``tenant_id`` in the key so two tenants never share an entry.

Disable globally with ``CACHE_ENABLED=false`` (instant kill switch).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_PREFIX = "erp:cache:v1"
_pool = None


def cache_enabled() -> bool:
    return os.getenv("CACHE_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def _redis():
    """Process-wide Redis client over a shared pool; ``None`` if unavailable."""
    global _pool
    try:
        import redis

        if _pool is None:
            from modules.notifications.realtime_pub import get_redis_url

            _pool = redis.ConnectionPool.from_url(
                get_redis_url(),
                decode_responses=True,
                max_connections=int(os.getenv("CACHE_REDIS_MAX_CONNECTIONS", "32")),
                health_check_interval=30,
            )
        return redis.Redis(connection_pool=_pool)
    except Exception:
        logger.debug("cache: redis unavailable", exc_info=True)
        return None


def redis_client():
    """The shared Redis client (over the process pool), or ``None`` if unavailable.

    For callers that need Redis primitives beyond the JSON cache helpers here
    (e.g. an atomic get-and-delete for one-time tokens). Still fail-open at the
    connection level — callers decide their own fail-open/closed policy.
    """
    return _redis()


def key(*parts: Any) -> str:
    """Build a namespaced cache key from parts: ``key('perms', user_id)``.

    **This does not scope to a tenant.** The one key in use, `perms:<user_id>`,
    is safe without one only because `users.id` is a UUID primary key — unique
    across the installation rather than within a school. That is an accident of
    the schema, not a property of this function, and `test_cache_edge_cases`
    pins it.

    Anything keyed by a value that is only unique *within* a tenant — a roll
    number, a per-tenant sequence, a class label — must use `tenant_key`, or
    two schools will share the entry.
    """
    return ":".join((_PREFIX, *(str(p) for p in parts)))


def tenant_key(*parts: Any) -> str:
    """A cache key scoped to the tenant this request is for.

    Use for anything whose identifier is not globally unique. Raises when there
    is no tenant, because a tenant-scoped value cached under a tenantless key
    is the cross-tenant leak this exists to prevent — failing is the safe
    answer.
    """
    from flask import g, has_request_context

    tenant_id = getattr(g, "tenant_id", None) if has_request_context() else None
    if not tenant_id:
        raise RuntimeError(
            "tenant_key() needs a resolved tenant; use key() only for "
            "identifiers that are unique across the whole installation"
        )
    return ":".join((_PREFIX, "t", str(tenant_id), *(str(p) for p in parts)))


def get_json(k: str) -> Optional[Any]:
    """Return the cached value for ``k``, or ``None`` on miss / disabled / error."""
    if not cache_enabled():
        return None
    r = _redis()
    if r is None:
        return None
    try:
        raw = r.get(k)
        return json.loads(raw) if raw is not None else None
    except Exception:
        logger.debug("cache get failed key=%s", k, exc_info=True)
        return None


def set_json(k: str, value: Any, ttl_seconds: int) -> None:
    """Cache ``value`` (JSON-serialised) under ``k`` for ``ttl_seconds``. No-op on error."""
    if not cache_enabled():
        return
    r = _redis()
    if r is None:
        return
    try:
        r.set(k, json.dumps(value, separators=(",", ":")), ex=max(1, int(ttl_seconds)))
    except Exception:
        logger.debug("cache set failed key=%s", k, exc_info=True)


def delete(*keys: str) -> None:
    """Delete one or more exact keys. No-op on error."""
    if not keys:
        return
    r = _redis()
    if r is None:
        return
    try:
        r.delete(*keys)
    except Exception:
        logger.debug("cache delete failed", exc_info=True)


#: How many keys one bulk invalidation will delete before giving up.
#:
#: `invalidate_all_permissions` runs on every role-permission change, and an
#: unbounded SCAN holds the connection for as long as the keyspace takes to
#: walk. Stopping early is safe *here specifically*: every cached value carries
#: a TTL, so anything missed expires on its own within two minutes. Running
#: without a bound is not.
MAX_PATTERN_DELETE_KEYS = 10_000


def delete_pattern(pattern: str) -> None:
    """Delete keys matching a glob pattern, up to `MAX_PATTERN_DELETE_KEYS`.

    SCAN-based — use sparingly, for rare bulk invalidations like a
    role-permission change. Truncation is logged rather than silent, because
    "some of them" and "all of them" are different answers and a reader of the
    logs should be able to tell which happened.
    """
    r = _redis()
    if r is None:
        return
    try:
        cursor = 0
        deleted = 0
        while True:
            cursor, batch = r.scan(cursor=cursor, match=pattern, count=200)
            if batch:
                r.delete(*batch)
                deleted += len(batch)
            if cursor == 0:
                break
            if deleted >= MAX_PATTERN_DELETE_KEYS:
                logger.warning(
                    "cache delete_pattern stopped at %s keys for pattern=%s; "
                    "the rest expire on their own TTL",
                    deleted, pattern,
                )
                break
    except Exception:
        logger.debug("cache delete_pattern failed pattern=%s", pattern, exc_info=True)


def get_or_set_json(k: str, ttl_seconds: int, loader: Callable[[], Any]) -> Any:
    """Return the cached value, or compute it via ``loader()``, cache it, and return it.

    ``loader()`` is the source of truth (e.g. a DB query). Non-``None`` results are
    cached; on any cache error the loader result is returned uncached (fail-open).
    """
    cached = get_json(k)
    if cached is not None:
        return cached
    value = loader()
    if value is not None:
        set_json(k, value, ttl_seconds)
    return value
