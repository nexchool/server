"""One-time login-handoff codes: platform super-admin → tenant admin-web session.

A platform admin creates a handoff from the super-admin panel
(``POST /api/platform/tenants/<id>/login-link``); admin-web redeems it at
``POST /api/auth/login-link/redeem`` to obtain a god-login session for that
tenant — no password re-entry.

Design:
- **Single use.** Redemption is an atomic Redis GET+DEL (Lua), so two concurrent
  redemptions can never both succeed — the code is burned on first use.
- **Short-lived.** Codes expire after ``DEFAULT_TTL_SECONDS`` (default 90s), so a
  leaked link is useless almost immediately.
- **Fail-closed.** If Redis is unavailable a code can neither be issued nor
  redeemed, so a session is never handed out without a live, single-use code.
- **Hashed at rest.** Only ``sha256(code)`` is stored, so a Redis dump never
  exposes a usable credential. The high-entropy code lives only in the URL the
  operator clicks.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from typing import Optional

_PREFIX = "erp:handoff:v1"
DEFAULT_TTL_SECONDS = 90

# Atomic get-and-delete so a code is redeemable at most once, even under a race.
_GETDEL_LUA = (
    "local v = redis.call('GET', KEYS[1]); "
    "if v then redis.call('DEL', KEYS[1]) end; "
    "return v"
)


def _hashed_key(code: str) -> str:
    return f"{_PREFIX}:{hashlib.sha256(code.encode()).hexdigest()}"


def issue(
    platform_admin_id: str,
    tenant_id: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> Optional[str]:
    """Mint a one-time handoff code for (platform_admin, tenant). None if Redis is down."""
    from core.cache import redis_client

    r = redis_client()
    if r is None:
        return None
    code = secrets.token_urlsafe(32)
    payload = json.dumps(
        {"admin_id": str(platform_admin_id), "tenant_id": str(tenant_id)},
        separators=(",", ":"),
    )
    try:
        r.set(_hashed_key(code), payload, ex=max(1, int(ttl_seconds)), nx=True)
    except Exception:
        return None
    return code


def redeem(code: str) -> Optional[dict]:
    """Atomically consume a handoff code, returning {admin_id, tenant_id} or None.

    Returns None if the code is empty, unknown, already used, expired, or Redis
    is unavailable — callers treat every None as an invalid link.
    """
    if not code:
        return None
    from core.cache import redis_client

    r = redis_client()
    if r is None:
        return None
    try:
        raw = r.eval(_GETDEL_LUA, 1, _hashed_key(code))
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not data.get("admin_id") or not data.get("tenant_id"):
        return None
    return data
