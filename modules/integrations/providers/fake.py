"""A provider that does nothing, predictably.

Tests need to see a rate limit, a timeout and a rejection without a network,
and every one of those is hard to arrange against a real vendor. This client
produces any of them on request.

**It cannot run in production.** `is_test_double` is True, and the resolver
refuses to hand out a test double unless the application is in testing or
debug mode — so an operator who configures a school onto this provider by
mistake gets a clean refusal rather than messages that vanish. That check is
in `resolver.py` and is tested.
"""

from __future__ import annotations

from typing import Optional

from .. import errors
from ..base import SmsProvider
from ..results import STATUS_ACCEPTED, ProviderHealth, MessageSendResult

#: Put in a school's `configuration` to choose what this provider does. A real
#: provider has no such knob, which is the point — it is visible in the row.
BEHAVIOUR_KEY = "fake_behaviour"

BEHAVIOUR_SUCCESS = "success"
BEHAVIOUR_TIMEOUT = "timeout"
BEHAVIOUR_RATE_LIMITED = "rate_limited"
BEHAVIOUR_REJECTED = "rejected"
BEHAVIOUR_UNAVAILABLE = "unavailable"
BEHAVIOUR_AUTHENTICATION = "authentication_error"

_FAILURES = {
    BEHAVIOUR_TIMEOUT: (errors.TIMEOUT, "The provider did not answer in time."),
    BEHAVIOUR_RATE_LIMITED: (errors.RATE_LIMITED, "Too many messages too quickly."),
    BEHAVIOUR_REJECTED: (errors.PROVIDER_REJECTED, "The provider declined this message."),
    BEHAVIOUR_UNAVAILABLE: (errors.PROVIDER_UNAVAILABLE, "The provider is unreachable."),
    BEHAVIOUR_AUTHENTICATION: (
        errors.AUTHENTICATION_ERROR,
        "The provider rejected our credentials.",
    ),
}


class FakeSmsProvider(SmsProvider):
    """Deterministic, offline, and refused outside a test."""

    key = "fake_sms"
    name = "Fake SMS (tests only)"
    supports_idempotency = True
    is_test_double = True
    required_credentials = ()

    def health(self, configuration: dict) -> ProviderHealth:
        return ProviderHealth(
            configured=True,
            credentials_present=True,
            provider_supported=True,
            provider_reachable=True,
            detail="A test double. It never contacts anything.",
        )

    def send(
        self,
        *,
        destination: str,
        message: str,
        configuration: dict,
        idempotency_key: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> MessageSendResult:
        behaviour = (configuration or {}).get(BEHAVIOUR_KEY, BEHAVIOUR_SUCCESS)

        if behaviour in _FAILURES:
            code, detail = _FAILURES[behaviour]
            return MessageSendResult(
                success=False,
                error_code=code,
                error_message=detail,
                retryable=errors.is_retryable(code),
                operation_id=operation_id,
                billable_units=0,
            )

        # A real provider returns its own id; this one derives a stable id from
        # the idempotency key when there is one, so a test can prove that the
        # same key produces the same reference.
        reference = idempotency_key or operation_id or "fake-message"
        return MessageSendResult(
            success=True,
            status=STATUS_ACCEPTED,
            provider_message_id=f"fake-{reference}",
            provider_status="queued",
            operation_id=operation_id,
            billable_units=1,
        )
