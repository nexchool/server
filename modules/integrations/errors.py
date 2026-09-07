"""What went wrong, said the same way whatever the vendor said it.

The point of this file is that a caller can decide what to do — retry, stop,
tell an operator to fix the configuration — **without parsing a vendor's
exception strings**. A provider that returns an HTTP 429 and one that raises
`ThrottledError` produce the same `RATE_LIMITED` here, and code upstream never
learns which happened.

The retryable classification is conservative on purpose, and the reason is in
`TIMEOUT` below: for a billable send, a retry can cost a customer real money.
"""

from __future__ import annotations

from typing import Optional

# --- the vocabulary ---------------------------------------------------------

#: Something is missing or wrong in how this school's integration is set up.
#: Nobody should retry; somebody should fix it.
CONFIGURATION_ERROR = "configuration_error"
#: The provider rejected our credentials.
AUTHENTICATION_ERROR = "authentication_error"
#: The provider says the request itself was wrong — a malformed number, a
#: message too long. Retrying the same request gets the same answer.
VALIDATION_ERROR = "validation_error"
#: We are going too fast. Retryable, but later and slower.
RATE_LIMITED = "rate_limited"
#: We never heard back. See the note below — this is the dangerous one.
TIMEOUT = "timeout"
#: The provider is down or unreachable.
PROVIDER_UNAVAILABLE = "provider_unavailable"
#: The provider understood us and declined — a blocked number, a blacklist.
PROVIDER_REJECTED = "provider_rejected"
#: Something we have not classified. Not retried, because guessing that an
#: unknown failure is safe to repeat is how duplicates happen.
UNKNOWN_PROVIDER_ERROR = "unknown_provider_error"

#: The school's integration has no template registered for this purpose.
#: A configuration problem, and specifically one that is cheaper to catch
#: here than to learn from a vendor's rejection.
TEMPLATE_NOT_CONFIGURED = "template_not_configured"

ERROR_CODES = (
    CONFIGURATION_ERROR,
    AUTHENTICATION_ERROR,
    VALIDATION_ERROR,
    RATE_LIMITED,
    TIMEOUT,
    PROVIDER_UNAVAILABLE,
    PROVIDER_REJECTED,
    UNKNOWN_PROVIDER_ERROR,
    TEMPLATE_NOT_CONFIGURED,
)

#: Errors where trying again could plausibly work.
#:
#: **`TIMEOUT` is deliberately absent.** A timeout means we do not know what
#: happened — the provider may well have accepted the request and sent the
#: message, and our retry would send a second one and charge the school twice.
#: A provider that supports idempotency keys makes a retry safe, so the retry
#: decision belongs with the provider that knows whether it does; see
#: `supports_idempotency` on the provider base class. This module will not
#: guess on a billable operation.
RETRYABLE_ERROR_CODES = (RATE_LIMITED, PROVIDER_UNAVAILABLE)

#: Errors that mean an operator has to do something. Reported differently from
#: weather, because a school waiting for a fix should not be told "try again".
CONFIGURATION_ERROR_CODES = (
    CONFIGURATION_ERROR,
    AUTHENTICATION_ERROR,
    TEMPLATE_NOT_CONFIGURED,
)


def is_retryable(error_code: Optional[str]) -> bool:
    return error_code in RETRYABLE_ERROR_CODES


def is_configuration_problem(error_code: Optional[str]) -> bool:
    return error_code in CONFIGURATION_ERROR_CODES


class IntegrationError(Exception):
    """A normalized failure, carrying its classification rather than a message
    somebody has to read.

    Raised where a caller cannot sensibly continue — an unknown capability, no
    integration configured. A *provider* failure is not raised: it comes back
    as a result, because "the SMS did not send" is an outcome a caller has to
    handle, not an exception it should be surprised by.
    """

    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message or code
        super().__init__(self.message)

    @property
    def retryable(self) -> bool:
        return is_retryable(self.code)


class UnknownCapability(IntegrationError):
    """Nothing in this build implements that capability."""

    def __init__(self, capability: str):
        super().__init__(
            CONFIGURATION_ERROR, f"'{capability}' is not a capability this build has."
        )


class NoIntegrationConfigured(IntegrationError):
    """This school has no enabled provider for that capability."""

    def __init__(self, capability: str):
        super().__init__(
            CONFIGURATION_ERROR,
            f"This school has no enabled {capability} provider.",
        )
