"""What came back, said in our words rather than the vendor's.

A provider's own response shape stops here. Nothing above this line ever sees
a vendor's JSON, its status strings or its exception types — that is what lets
NexSchool change provider without touching a feature.

The care in this file is mostly about **not claiming more than the provider
gave us**. See `MessageSendResult.status`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# --- how far a message actually got -----------------------------------------
#
# The distinction that matters: a provider accepting an API request is not a
# handset receiving a message, and a layer that called the first one
# "delivered" would be lying in a way nobody could catch later.

#: The provider took the request. This is all most providers tell you
#: synchronously, and it is what a successful send means here.
STATUS_ACCEPTED = "accepted"
#: The provider says it handed the message to a carrier.
STATUS_SENT = "sent"
#: The provider says it reached the handset. Only ever set from a delivery
#: receipt, never inferred.
STATUS_DELIVERED = "delivered"
#: It did not work.
STATUS_FAILED = "failed"

SEND_STATUSES = (STATUS_ACCEPTED, STATUS_SENT, STATUS_DELIVERED, STATUS_FAILED)


@dataclass
class MessageSendResult:
    """The outcome of asking a provider to send one message, on any channel.

    `status` is the honest one. A provider that only acknowledges receipt gets
    `accepted`, and nothing in this codebase may upgrade that to `delivered`
    without a delivery receipt to stand on.

    `provider_message_id` is the vendor's own id for the send. It is the
    idempotency key for the usage ledger (Phase 2's `external_reference`), so
    a provider that returns one gets exactly-once billing for free and one
    that does not is documented as not having it.
    """

    success: bool
    status: str = STATUS_FAILED
    #: The vendor's id for this message, when it gives one.
    provider_message_id: Optional[str] = None
    #: The vendor's own status string, kept for support to read. Never parsed.
    provider_status: Optional[str] = None
    #: Our normalized code from `errors.py`, not the vendor's.
    error_code: Optional[str] = None
    #: Safe to show an operator. Never contains a credential or a message body.
    error_message: Optional[str] = None
    retryable: bool = False
    #: How many billable units the provider says this cost. A long message may
    #: be several. Defaults to one because that is what one send usually is.
    billable_units: float = 1.0
    #: Ties this call to the request that caused it. See `operations.py`.
    operation_id: Optional[str] = None
    latency_ms: Optional[int] = None

    @property
    def is_billable(self) -> bool:
        """Whether this send should reach the usage ledger.

        A provider that accepted the request will charge for it whether or not
        the handset ever sees it, so acceptance is the billable moment — not
        delivery, which may never be reported.
        """
        return self.success and self.billable_units > 0


@dataclass
class ProviderHealth:
    """Whether an integration looks usable, without spending anything.

    Deliberately not a delivery test. Sending a real message to find out
    whether configuration works costs the school money and, for SMS,
    inconveniences whoever owns the number.
    """

    configured: bool
    #: Whether credential material was found where the configuration says.
    credentials_present: bool
    #: Whether this build has a client for the named provider.
    provider_supported: bool
    #: Only set when the provider offers a free, non-sending check.
    provider_reachable: Optional[bool] = None
    detail: str = ""
    checks: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.configured and self.credentials_present and self.provider_supported
