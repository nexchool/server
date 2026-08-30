"""Server-Sent Events stream: Redis messages → SSE `event` + `data` frames."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, Iterator, Tuple

from modules.notifications.realtime_pub import get_redis_url, notification_channel

logger = logging.getLogger(__name__)

# Keepalive doubles as dead-client detection: the worker thread only discovers a
# disconnected browser (e.g. after a page reload) when it next writes, so a lower
# value frees the thread sooner at the cost of slightly more idle traffic.
_KEEPALIVE_SEC = float(os.getenv("SSE_KEEPALIVE_SEC", "15"))


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


# ---------------------------------------------------------------------------
# Stream capacity
# ---------------------------------------------------------------------------
#
# An SSE response occupies one gunicorn thread for the life of the connection,
# and admin-web opens one for every signed-in user. Unbounded, that is a cap on
# *concurrent people* rather than on data: at `GUNICORN_THREADS` connected
# staff every thread is parked in the loop below and the API stops answering
# anything — the failure production already hit once and papered over by
# raising the thread count.
#
# So streams get a share of the worker's threads and no more. Past it the route
# answers 503, which the endpoint already does when Redis is down and the
# client already handles by falling back to manual refresh. Losing live
# notifications for some people beats losing the product for everybody.
#
# Per process, which is per worker — the accounting does not need to be shared
# because the threads it protects are not.

_slots_lock = threading.Lock()
_slots_limit: int = 0
_slots_in_use: int = 0


def default_stream_limit() -> int:
    """How many of this worker's threads streams may occupy.

    Read from the same variable gunicorn sizes itself with, so the two cannot
    drift apart: half the threads, leaving the rest for ordinary requests, and
    never below one so a single-threaded dev box still gets live notifications.
    """
    configured = os.getenv("SSE_MAX_CONNECTIONS")
    if configured and configured.isdigit() and int(configured) > 0:
        return int(configured)
    threads = int(os.getenv("GUNICORN_THREADS", "16") or 16)
    return max(1, threads // 2)


def reset_stream_slots(limit: int | None = None) -> None:
    """Re-arm the accounting. For tests, and for a worker re-forking."""
    global _slots_limit, _slots_in_use
    with _slots_lock:
        _slots_limit = default_stream_limit() if limit is None else limit
        _slots_in_use = 0


def acquire_stream_slot() -> bool:
    """Take a thread for a stream, or report that this worker is full."""
    global _slots_in_use, _slots_limit
    with _slots_lock:
        if _slots_limit <= 0:
            # First call in this process: size against the worker's threads.
            _slots_limit = default_stream_limit()
        if _slots_in_use >= _slots_limit:
            return False
        _slots_in_use += 1
        return True


def release_stream_slot() -> None:
    """Give the thread back. Never drops below zero — a double release would
    hand out more streams than the worker has threads to serve them."""
    global _slots_in_use
    with _slots_lock:
        if _slots_in_use > 0:
            _slots_in_use -= 1


def streams_in_use() -> int:
    with _slots_lock:
        return _slots_in_use


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
