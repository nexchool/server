"""How often a number may be asked for a code, and by whom.

OTP is the first authentication method that costs money to attempt, and that
changes what a rate limit is for. A wrong password wastes a request; a
requested OTP spends a school's money and rings a real person's phone. So the
limits here defend three different things at once:

    a victim         from having their phone rung all night
    a school         from a bill somebody else ran up
    an account       from being guessed at

None of the existing machinery could do this. `flask_limiter` is keyed on the
IP address alone, which is no defence against an attacker with a list of
addresses attacking one number. The database lockout is keyed on an account
row, so it cannot throttle requests for a number that resolves to no account —
and the pipeline's identifier-level counter deliberately handles only email.
So this is a new primitive, built on the Redis client the cache layer already
exposes for exactly this ("an atomic get-and-delete for one-time tokens").

**It fails closed.** The repository is split on this — `core/cache.py` fails
open because a missing cache entry is only slow, while `handoff.py` fails
closed because a sign-in code that cannot be tracked must not be issued. A
rate limit that stops working when Redis does is not a rate limit, and the
thing it stops protecting is somebody's phone bill, so this follows `handoff`.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

#: Own namespace, like `handoff.py`. Never shares keys with the JSON cache,
#: whose `delete_pattern` sweeps would otherwise reset a limit.
_PREFIX = "erp:otp:v1"

# --- the limits --------------------------------------------------------------
#
# Each is one sentence of policy, in one place, so a limit cannot be changed in
# one file and left alone in another.

#: A number may be sent this many codes in an hour. Above a handful, somebody
#: is not failing to receive a message; something else is happening.
MAX_REQUESTS_PER_MOBILE_HOUR = 5
#: And this many in a day, so an attacker cannot simply wait out the hour.
MAX_REQUESTS_PER_MOBILE_DAY = 10
#: One address may ask for codes for this many different numbers in an hour.
MAX_REQUESTS_PER_IP_HOUR = 20
#: A school's whole spend ceiling per hour — the backstop against a bill run up
#: by a distributed attack that stays under every per-number limit.
MAX_REQUESTS_PER_TENANT_HOUR = 200
#: How long after a code is sent before another may be asked for.
RESEND_COOLDOWN_SECONDS = 60

_HOUR = 3600
_DAY = 86400


class ThrottleUnavailable(Exception):
    """The limiter cannot be reached, so nothing may be spent."""


@dataclass(frozen=True)
class ThrottleDecision:
    """Whether this request may proceed, and why not.

    `reason` is for the audit record and the operator. It is deliberately not
    what the caller is told: a response that distinguished "this number is
    being throttled" from "this number is not a customer" would answer, for
    free, the question an enumeration attack is asking.
    """

    allowed: bool
    reason: Optional[str] = None
    retry_after_seconds: Optional[int] = None


REASON_COOLDOWN = "resend_cooldown"
REASON_MOBILE_HOURLY = "mobile_hourly_limit"
REASON_MOBILE_DAILY = "mobile_daily_limit"
REASON_IP_HOURLY = "ip_hourly_limit"
REASON_TENANT_HOURLY = "tenant_hourly_limit"
REASON_UNAVAILABLE = "throttle_unavailable"


def hash_value(value: str) -> str:
    """A key that identifies without revealing.

    Deliberately not `event_models.hash_identifier`. That is an unsalted
    sha256, which is sound for the email addresses it was built for and weak
    for a phone number: an Indian mobile has roughly ten billion candidates, so
    a bare digest of one can be reversed by anybody who cares to try. Here the
    digest is keyed with the application secret, which makes reversal require
    the secret as well as the effort.
    """
    from flask import current_app

    try:
        secret = current_app.config.get("SECRET_KEY") or ""
    except RuntimeError:
        secret = ""

    import hmac

    return hmac.new(
        secret.encode() or b"nexschool", (value or "").encode(), hashlib.sha256
    ).hexdigest()


def _client():
    """A Redis handle that has been proven to answer.

    `redis_client()` builds a client lazily and does not connect, so a handle
    that exists proves nothing — a host that resolves but refuses connections
    hands back a perfectly good object that raises on first use. Pinging here
    turns that into one `ThrottleUnavailable` at the top of the call rather
    than an unhandled `ConnectionError` in the middle of a sign-in.
    """
    from core.cache import redis_client

    client = redis_client()
    if client is None:
        raise ThrottleUnavailable("The rate limiter is unreachable.")
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001 - every redis failure is the same failure here
        raise ThrottleUnavailable("The rate limiter is unreachable.") from exc
    return client


def _bump(client, key: str, ttl: int) -> int:
    """Increment a counter and make sure it expires.

    The expiry is set in the same pipeline as the increment. A bare `INCR`
    whose process dies before its `EXPIRE` leaves a key with no lifetime, and
    the number it counts locked out for ever.
    """
    pipe = client.pipeline()
    pipe.incr(key)
    pipe.expire(key, ttl)
    count, _ = pipe.execute()
    return int(count)


def _peek(client, key: str) -> int:
    value = client.get(key)
    return int(value) if value else 0


def check_request_allowed(
    *, tenant_id: str, mobile_hash: str, ip_address: Optional[str]
) -> ThrottleDecision:
    """May a code be sent, right now, for this number?

    Reads every counter before incrementing any of them, so a request refused
    by one limit does not consume another. Ordered cheapest-blast-radius first:
    the cooldown affects one person, the tenant ceiling affects a school.
    """
    try:
        client = _client()
    except ThrottleUnavailable:
        logger.error("OTP refused: the rate limiter is unreachable")
        return ThrottleDecision(allowed=False, reason=REASON_UNAVAILABLE)

    try:
        cooldown_key = f"{_PREFIX}:cooldown:{tenant_id}:{mobile_hash}"
        remaining = client.ttl(cooldown_key)
        if remaining and remaining > 0:
            return ThrottleDecision(
                allowed=False, reason=REASON_COOLDOWN, retry_after_seconds=int(remaining)
            )
    except Exception:  # noqa: BLE001
        logger.error("OTP refused: the rate limiter failed mid-check", exc_info=True)
        return ThrottleDecision(allowed=False, reason=REASON_UNAVAILABLE)

    checks = (
        (f"{_PREFIX}:mob:h:{tenant_id}:{mobile_hash}", MAX_REQUESTS_PER_MOBILE_HOUR, REASON_MOBILE_HOURLY, _HOUR),
        (f"{_PREFIX}:mob:d:{tenant_id}:{mobile_hash}", MAX_REQUESTS_PER_MOBILE_DAY, REASON_MOBILE_DAILY, _DAY),
        (f"{_PREFIX}:tenant:h:{tenant_id}", MAX_REQUESTS_PER_TENANT_HOUR, REASON_TENANT_HOURLY, _HOUR),
    )
    if ip_address:
        checks = checks + (
            (
                f"{_PREFIX}:ip:h:{hash_value(ip_address)}",
                MAX_REQUESTS_PER_IP_HOUR,
                REASON_IP_HOURLY,
                _HOUR,
            ),
        )

    try:
        for key, limit, reason, ttl in checks:
            if _peek(client, key) >= limit:
                return ThrottleDecision(
                    allowed=False, reason=reason, retry_after_seconds=ttl
                )
    except Exception:  # noqa: BLE001 - a limiter that half-works is not a limiter
        logger.error("OTP refused: the rate limiter failed mid-check", exc_info=True)
        return ThrottleDecision(allowed=False, reason=REASON_UNAVAILABLE)

    return ThrottleDecision(allowed=True)


def record_request_sent(
    *, tenant_id: str, mobile_hash: str, ip_address: Optional[str]
) -> None:
    """Count a code that was actually sent, and start the cooldown.

    Called **after** the provider accepted the message, not before. A send that
    the provider refused cost the school nothing and rang nobody's phone, so
    counting it would let a broken integration lock a school out of its own
    sign-in.
    """
    try:
        client = _client()
    except ThrottleUnavailable:
        # The message is already gone. Refusing here would achieve nothing
        # except hiding that it happened.
        logger.error("OTP sent but not counted: the rate limiter is unreachable")
        return

    try:
        _bump(client, f"{_PREFIX}:mob:h:{tenant_id}:{mobile_hash}", _HOUR)
        _bump(client, f"{_PREFIX}:mob:d:{tenant_id}:{mobile_hash}", _DAY)
        _bump(client, f"{_PREFIX}:tenant:h:{tenant_id}", _HOUR)
        if ip_address:
            _bump(client, f"{_PREFIX}:ip:h:{hash_value(ip_address)}", _HOUR)

        client.set(
            f"{_PREFIX}:cooldown:{tenant_id}:{mobile_hash}",
            "1",
            ex=RESEND_COOLDOWN_SECONDS,
        )
    except Exception:  # noqa: BLE001 - the message is already gone
        logger.error("OTP sent but not counted: the rate limiter failed", exc_info=True)


def clear_for_tests(
    *, tenant_id: str, mobile_hash: str = "", ip_address: Optional[str] = None
) -> None:
    """Forget a school's counters. Only ever called by tests.

    `ip_address` matters more than it looks: every request from a test client
    arrives from `127.0.0.1`, so a suite that sends more than
    `MAX_REQUESTS_PER_IP_HOUR` codes throttles itself — and because the counter
    lives in a real Redis, it does so across runs, which looks like flakiness
    rather than the limiter working.
    """
    try:
        client = _client()
    except ThrottleUnavailable:
        return
    try:
        keys = [
            f"{_PREFIX}:tenant:h:{tenant_id}",
            f"{_PREFIX}:mob:h:{tenant_id}:{mobile_hash}",
            f"{_PREFIX}:mob:d:{tenant_id}:{mobile_hash}",
            f"{_PREFIX}:cooldown:{tenant_id}:{mobile_hash}",
        ]
        if ip_address:
            keys.append(f"{_PREFIX}:ip:h:{hash_value(ip_address)}")
        for key in keys:
            client.delete(key)
    except Exception:  # noqa: BLE001
        return
