"""
Redis pub/sub for per-user inbox SSE (schema versioned channel name).

Publishing is best-effort and uses a process-wide connection pool. Payloads are
JSON envelopes consumed by inbox_sse.py and turned into proper SSE frames
(`event:` + `data:`).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

logger = logging.getLogger(__name__)

# Bump if channel semantics change (multi-worker deployments).
CHANNEL_PREFIX = "erp:v1:inbox"


class InboxRealtimeEvent:
    """Event names published to Redis (mirrored in admin-web SSE client)."""

    INBOX_CREATED = "inbox.created"
    INBOX_READ = "inbox.read"
    INBOX_READ_ALL = "inbox.read_all"


def notification_channel(tenant_id: str, user_id: str) -> str:
    return f"{CHANNEL_PREFIX}:{tenant_id}:{user_id}"


def get_redis_url() -> str:
    try:
        from flask import current_app

        return (
            current_app.config.get("REDIS_URL")
            or os.environ.get("REDIS_URL")
            or "redis://localhost:6379/0"
        )
    except Exception:
        return os.environ.get("REDIS_URL") or "redis://localhost:6379/0"


_pool = None


def _connection_pool():
    global _pool
    if _pool is None:
        import redis

        _pool = redis.ConnectionPool.from_url(
            get_redis_url(),
            decode_responses=True,
            max_connections=64,
            health_check_interval=30,
        )
    return _pool


def publish_inbox_event(
    tenant_id: str,
    user_ids: Sequence[str],
    event: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Publish a structured event to each user's inbox channel."""
    if not tenant_id or not user_ids or not event:
        return
    uids = [u for u in dict.fromkeys(user_ids) if u]
    if not uids:
        return
    envelope = {
        "event": event,
        "data": data if isinstance(data, dict) else {},
        "ts": datetime.now(timezone.utc).isoformat(),
        "id": str(uuid.uuid4()),
    }
    payload = json.dumps(envelope, separators=(",", ":"))
    try:
        import redis

        r = redis.Redis(connection_pool=_connection_pool())
        pipe = r.pipeline()
        for uid in uids:
            pipe.publish(notification_channel(tenant_id, uid), payload)
        pipe.execute()
    except Exception:
        logger.debug("publish_inbox_event failed", exc_info=True)

