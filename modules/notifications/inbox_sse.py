"""Server-Sent Events stream: Redis messages → SSE `event` + `data` frames."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Iterator, Tuple

from modules.notifications.realtime_pub import get_redis_url, notification_channel

logger = logging.getLogger(__name__)

_KEEPALIVE_SEC = 25.0


def _format_sse_frame(event: str, data: Dict[str, Any]) -> str:
    """One SSE event block (RFC 8895 style)."""
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def _parse_envelope(raw: str) -> Tuple[str, Dict[str, Any]]:
    """Return (event_name, data_payload) from Redis JSON envelope."""
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            ev = str(obj.get("event") or "message")
            inner = obj.get("data")
            data = inner if isinstance(inner, dict) else {}
            return ev, data
    except (json.JSONDecodeError, TypeError):
        pass
    return "message", {"raw": raw[:500]}


def inbox_sse_events(tenant_id: str, user_id: str) -> Iterator[str]:
    """
    Subscribe to this user's inbox channel; yield SSE frames.

    `system.*` events originate here; `inbox.*` events originate from Redis publish.
    """
    import redis as redis_lib

    connection_id = str(uuid.uuid4())
    channel = notification_channel(tenant_id, user_id)
    url = get_redis_url()
    client = redis_lib.from_url(url, decode_responses=True)
    pubsub = client.pubsub()
    try:
        pubsub.subscribe(channel)
        yield _format_sse_frame(
            "system.connected",
            {
                "connection_id": connection_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "channel": channel,
            },
        )
        last_keepalive = time.monotonic()
        while True:
            msg = pubsub.get_message(timeout=1.0, ignore_subscribe_messages=True)
            now = time.monotonic()
            if msg and msg.get("type") == "message":
                raw = msg.get("data")
                if isinstance(raw, str) and raw.strip():
                    event_name, data_payload = _parse_envelope(raw)
                    yield _format_sse_frame(event_name, data_payload)
            if now - last_keepalive >= _KEEPALIVE_SEC:
                yield _format_sse_frame("system.ping", {"t": int(now * 1000)})
                last_keepalive = now
    except Exception as e:
        logger.warning("inbox_sse_events ended channel=%s: %s", channel, e)
    finally:
        try:
            pubsub.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass
