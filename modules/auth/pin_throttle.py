"""How many times a PIN may be guessed, and by whom.

A six-digit PIN has a million values. Hashing it well protects it if the
database leaks; it does nothing at all against somebody typing guesses at the
login endpoint, and at a few hundred attempts a second a million values is an
afternoon. **The online limit is the entire security of the method**, which is
why this file exists and why it fails closed.

It is not a second throttle architecture. The Redis primitive, the keyed
hashing and the fail-closed policy all come from `otp_throttle`, which built
them for Phase 4; what is here is the PIN-shaped policy on top. One mechanism,
two sets of limits, because the two are defending against different things: an
OTP request costs money and rings a phone, while a PIN attempt costs nothing
and is trying to get in.

Three dimensions, each closing a hole the others leave:

    per (tenant, mobile)   one number cannot be ground through
    per IP                 one attacker cannot spread across numbers
    per tenant             a rotating-IP swarm cannot grind a whole school

The account lockout that already exists is deliberately *not* relied on. It is
keyed on an account row, and an enumeration-resistant login must count
attempts against numbers that resolve to no account at all — otherwise
guessing at a number nobody holds is free, and the difference between free and
throttled is itself the answer to "does this number exist here".
"""

from __future__ import annotations

import logging
from typing import Optional

from .otp_throttle import (  # the shared primitive, not a second copy of it
    ThrottleDecision,
    ThrottleUnavailable,
    _bump,
    _client,
    _peek,
    hash_value,
)

logger = logging.getLogger(__name__)

_PREFIX = "erp:pin:v1"

# --- the limits --------------------------------------------------------------
#
# Sized against the arithmetic rather than by feel. Ten guesses an hour at one
# number is 87,600 a year against a million values: a 9% chance of success
# after a year of uninterrupted attack on one child, and the per-IP and
# per-tenant ceilings mean an attacker cannot run that against a whole school
# in parallel.

#: Wrong PINs allowed against one number, per hour.
MAX_FAILURES_PER_MOBILE_HOUR = 10
#: And per day, so an attacker cannot simply wait out each hour.
MAX_FAILURES_PER_MOBILE_DAY = 25
#: Wrong PINs from one address, across all numbers, per hour.
MAX_FAILURES_PER_IP_HOUR = 30
#: A whole school's ceiling, the backstop against a distributed attack that
#: stays under every per-number limit.
MAX_FAILURES_PER_TENANT_HOUR = 500

_HOUR = 3600
_DAY = 86400

REASON_MOBILE_HOURLY = "pin_mobile_hourly_limit"
REASON_MOBILE_DAILY = "pin_mobile_daily_limit"
REASON_IP_HOURLY = "pin_ip_hourly_limit"
REASON_TENANT_HOURLY = "pin_tenant_hourly_limit"
REASON_UNAVAILABLE = "throttle_unavailable"


def _keys(tenant_id: str, mobile_hash: str, ip_address: Optional[str]):
    keys = [
        (f"{_PREFIX}:mob:h:{tenant_id}:{mobile_hash}", MAX_FAILURES_PER_MOBILE_HOUR, REASON_MOBILE_HOURLY, _HOUR),
        (f"{_PREFIX}:mob:d:{tenant_id}:{mobile_hash}", MAX_FAILURES_PER_MOBILE_DAY, REASON_MOBILE_DAILY, _DAY),
        (f"{_PREFIX}:tenant:h:{tenant_id}", MAX_FAILURES_PER_TENANT_HOUR, REASON_TENANT_HOURLY, _HOUR),
    ]
    if ip_address:
        keys.append(
            (
                f"{_PREFIX}:ip:h:{hash_value(ip_address)}",
                MAX_FAILURES_PER_IP_HOUR,
                REASON_IP_HOURLY,
                _HOUR,
            )
        )
    return keys


def check_attempt_allowed(
    *, tenant_id: str, mobile_hash: str, ip_address: Optional[str] = None
) -> ThrottleDecision:
    """May another PIN be tried, right now, against this number?

    Checked **before** the PIN is compared, so a blocked attacker learns
    nothing from how long the answer took or from whether the account exists.
    """
    try:
        client = _client()
    except ThrottleUnavailable:
        # Fail closed. A PIN check that cannot be counted is a free guess, and
        # free guesses are the one thing a six-digit secret cannot survive.
        logger.error("PIN attempt refused: the rate limiter is unreachable")
        return ThrottleDecision(allowed=False, reason=REASON_UNAVAILABLE)

    try:
        for key, limit, reason, ttl in _keys(tenant_id, mobile_hash, ip_address):
            if _peek(client, key) >= limit:
                return ThrottleDecision(
                    allowed=False, reason=reason, retry_after_seconds=ttl
                )
    except Exception:  # noqa: BLE001 - a limiter that half-works is not a limiter
        logger.error("PIN attempt refused: the rate limiter failed", exc_info=True)
        return ThrottleDecision(allowed=False, reason=REASON_UNAVAILABLE)

    return ThrottleDecision(allowed=True)


def record_failure(
    *, tenant_id: str, mobile_hash: str, ip_address: Optional[str] = None
) -> None:
    """Count one wrong PIN.

    Only failures are counted. A person who signs in correctly every morning
    should never approach a limit, and counting successes would eventually
    lock out the only people using the feature.
    """
    try:
        client = _client()
    except ThrottleUnavailable:
        logger.error("a wrong PIN went uncounted: the rate limiter is unreachable")
        return

    try:
        for key, _limit, _reason, ttl in _keys(tenant_id, mobile_hash, ip_address):
            _bump(client, key, ttl)
    except Exception:  # noqa: BLE001
        logger.error("a wrong PIN went uncounted: the rate limiter failed", exc_info=True)


def clear_failures(*, tenant_id: str, mobile_hash: str) -> None:
    """Forget the wrong guesses against one number, after a right one.

    Per-number only. The per-IP and per-tenant counters are deliberately left
    alone: one correct PIN somewhere in a school says nothing about the
    thousands of wrong ones an attacker is making elsewhere, and clearing them
    would hand that attacker a reset button.
    """
    try:
        client = _client()
    except ThrottleUnavailable:
        return
    try:
        client.delete(f"{_PREFIX}:mob:h:{tenant_id}:{mobile_hash}")
        client.delete(f"{_PREFIX}:mob:d:{tenant_id}:{mobile_hash}")
    except Exception:  # noqa: BLE001
        return


def clear_for_tests(
    *, tenant_id: str, mobile_hash: str = "", ip_address: Optional[str] = None
) -> None:
    """Forget every PIN counter for a school. Only ever called by tests."""
    try:
        client = _client()
    except ThrottleUnavailable:
        return
    try:
        for key, _limit, _reason, _ttl in _keys(tenant_id, mobile_hash, ip_address):
            client.delete(key)
    except Exception:  # noqa: BLE001
        return
