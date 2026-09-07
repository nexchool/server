"""Send an SMS, without knowing who sends it.

This is the surface a feature uses. `otp._deliver` calls
`messaging.send_message` directly (it has to: the message can go down SMS or
WhatsApp depending on the school's chosen channel, and this file only ever
means SMS), never learns which company carried the message, what it cost, or
how the provider reports failure. The resolve / template / call / normalize
/ record path that boundary depends on lives in `messaging.py`, shared with
WhatsApp — this file is a thin, named surface over it, so a caller that only
ever means "send an SMS" still gets to say exactly that.

`send_sms` and `whatsapp.py`'s `send_whatsapp` currently have no production
caller — the one place that sends anything (`otp._deliver`) reads the
school's channel first and calls `messaging.send_message` itself rather than
branching to one of these. They exist anyway, deliberately, as the
per-channel surfaces a caller that already knows its channel is meant to
use, and as the shape a future non-OTP messaging feature reaches for first.
Do not delete them for being unreached; delete `messaging.send_message`'s
direct callers into one of these once one exists, if that consolidation
turns out to be worth it.
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
