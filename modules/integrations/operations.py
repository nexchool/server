"""Tying a provider call back to the request that caused it.

The repository documents an `X-Request-Id` convention and does not implement
it: nothing generates a request id, nothing logs one, and there is no logging
configuration at all. Building that is an observability project, and this
phase is not it.

So this is the smallest useful thing instead — an id minted per integration
operation, carried through the log lines and onto the usage record, so that
"which call produced this charge" has an answer. If a real correlation id
arrives later, this is one function to change.

Also here: how a phone number is written down. Which is to say, mostly not.
"""

from __future__ import annotations

import hashlib
import uuid


def new_operation_id() -> str:
    """A short id for one provider call. Not a secret, not a request id."""
    return f"op-{uuid.uuid4().hex[:16]}"


def redact_destination(destination: str) -> str:
    """A phone number, written so a log is useful and still not a phone book.

    Keeps the last two digits — enough for somebody reading a support ticket
    with the number in front of them to confirm they are looking at the right
    line — and hashes the rest for correlation.

    Deliberately **not** `hash_identifier` from the authentication events. That
    is an unsalted sha256, which is right for the email addresses it was built
    for and weak here: a mobile number has about ten billion candidates, so a
    bare digest of one is reversible by anybody who cares to try. The truncated
    digest below is a correlation key over a much smaller output space and is
    not offered as anonymisation; the real protection is that the full number
    never reaches a log at all.
    """
    if not destination:
        return "(none)"

    trimmed = destination.strip()
    digest = hashlib.sha256(trimmed.encode()).hexdigest()[:10]
    tail = trimmed[-2:] if len(trimmed) >= 2 else ""
    return f"…{tail}/{digest}"
