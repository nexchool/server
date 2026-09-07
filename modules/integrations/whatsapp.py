"""Send a WhatsApp template message, without knowing who sends it.

The WhatsApp mirror of `sms.py` — a thin, named surface over
`messaging.send_message`. There is no body to pass: Meta will not carry an
authentication-category message except through a template approved in
advance, so a send here names a purpose and supplies that template's
variables, and nothing else.
"""

from __future__ import annotations

from typing import Optional

from .capabilities import CAPABILITY_WHATSAPP
from .results import MessageSendResult


def send_whatsapp(
    *,
    tenant_id: str,
    destination: str,
    purpose: str,
    variables: list,
    idempotency_key: Optional[str] = None,
) -> MessageSendResult:
    """Send one WhatsApp template message. A named surface over
    `messaging.send_message`.

    Returns a result rather than raising, including when the school has no
    provider configured. A caller deciding whether to fall back to another
    channel should not have to catch an exception to find out.
    """
    from .messaging import send_message

    return send_message(
        tenant_id=tenant_id,
        channel=CAPABILITY_WHATSAPP,
        purpose=purpose,
        destination=destination,
        variables=variables,
        idempotency_key=idempotency_key,
    )


def whatsapp_health(tenant_id: str):
    """Whether this school's WhatsApp integration looks usable.

    **Sends nothing**, for the same reason `sms_health` sends nothing. A
    named surface over `messaging.messaging_health`.
    """
    from .messaging import messaging_health

    return messaging_health(tenant_id, CAPABILITY_WHATSAPP)
