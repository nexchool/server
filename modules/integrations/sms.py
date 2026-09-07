"""Send an SMS, without knowing who sends it.

This is the surface a feature uses. Phase 4's OTP calls `send_sms` and never
learns which company carried the message, what it cost, or how the provider
reports failure. The resolve / template / call / normalize / record path
that boundary depends on now lives in `messaging.py`, shared with WhatsApp —
this file is a thin, named surface over it, so a caller that only ever means
"send an SMS" still gets to say exactly that.
"""

from __future__ import annotations

from typing import Optional

from .capabilities import CAPABILITY_SMS
from .results import MessageSendResult


def send_sms(
    *,
    tenant_id: str,
    destination: str,
    body: str,
    purpose: str,
    variables: list,
    idempotency_key: Optional[str] = None,
) -> MessageSendResult:
    """Send one SMS. A named surface over `messaging.send_message`.

    `idempotency_key` should be stable for a logical send: the same key
    retried must not produce a second message. Whether the provider honours it
    is the provider's own declaration (`supports_idempotency`), and where it
    does not, this function does not retry — see `errors.TIMEOUT`.

    Returns a result rather than raising, including when the school has no
    provider configured. A caller deciding whether to fall back to another
    channel should not have to catch an exception to find out.
    """
    from .messaging import send_message

    return send_message(
        tenant_id=tenant_id,
        channel=CAPABILITY_SMS,
        purpose=purpose,
        destination=destination,
        variables=variables,
        body=body,
        idempotency_key=idempotency_key,
    )


def sms_health(tenant_id: str):
    """Whether this school's SMS integration looks usable.

    **Sends nothing.** Finding out whether an SMS integration works by sending
    an SMS charges the school and bothers whoever owns the number, so this
    reports configuration readiness and says plainly when delivery was not
    verified. A named surface over `messaging.messaging_health`.
    """
    from .messaging import messaging_health

    return messaging_health(tenant_id, CAPABILITY_SMS)
