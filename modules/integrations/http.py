"""One way to make an outbound call, with the timeouts already set.

The repository's three existing outbound calls each set `timeout=30` as a
copy-pasted literal, and the fourth — boto3 — sets nothing at all and inherits
unbounded retries. That is the failure this file exists to stop being possible:
a provider client written next year should not be able to forget a timeout,
because there is no way in here to omit one.

Deliberately thin. This is `urllib` with defaults and a normalized error, the
same standard-library device the push services already use — not a new HTTP
stack, not a session pool, not a circuit breaker. A provider layer that
shipped an abstraction nobody had asked for yet would be the wrong trade.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from typing import Dict, Optional, Tuple

from . import errors

logger = logging.getLogger(__name__)

#: Long enough for a slow provider on a bad day, short enough that a request
#: thread is not held for a minute. `urllib` has one timeout covering connect
#: and read; a client needing them separately should say so and get its own.
DEFAULT_TIMEOUT_SECONDS = 15

#: Nothing may hang longer than this, whatever a caller asks for. A provider
#: client that wants five minutes has a design problem, not a timeout problem.
MAX_TIMEOUT_SECONDS = 60


class HttpResponse:
    """A provider's answer, before anybody has interpreted it."""

    def __init__(self, status: int, body: str, headers: Dict[str, str]):
        self.status = status
        self.body = body
        self.headers = headers

    def json(self):
        try:
            return json.loads(self.body) if self.body else {}
        except ValueError:
            return {}


def post_json(
    url: str,
    payload: dict,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Tuple[Optional[HttpResponse], Optional[str]]:
    """POST some JSON. Returns `(response, normalized_error_code)`.

    Never raises for a network condition: a provider being down is an outcome,
    and a caller that has to wrap every call in a try block will eventually
    forget one. Exactly one of the two return values is set.

    Nothing here logs the payload or the headers. Headers carry the
    authorization; the payload, for SMS, carries the message.
    """
    timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT_SECONDS), MAX_TIMEOUT_SECONDS))
    body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (
                HttpResponse(
                    response.status,
                    response.read().decode("utf-8", errors="replace"),
                    dict(response.headers),
                ),
                None,
            )
    except urllib.error.HTTPError as exc:
        # An HTTP error is still an answer — the provider said something, and
        # the client is the one that knows what its status codes mean.
        return (
            HttpResponse(
                exc.code,
                exc.read().decode("utf-8", errors="replace"),
                dict(exc.headers or {}),
            ),
            None,
        )
    except socket.timeout:
        return None, errors.TIMEOUT
    except urllib.error.URLError as exc:
        # `URLError` wraps a timeout on some Python versions, so the reason is
        # checked rather than assumed — mistaking a timeout for an outage
        # would make it look retryable, which is the one thing it is not.
        if isinstance(getattr(exc, "reason", None), socket.timeout):
            return None, errors.TIMEOUT
        return None, errors.PROVIDER_UNAVAILABLE
    except Exception:  # noqa: BLE001 - normalized, never swallowed silently
        logger.exception("provider call failed in an unclassified way")
        return None, errors.UNKNOWN_PROVIDER_ERROR
    finally:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.debug("provider call finished in %dms", elapsed_ms)
