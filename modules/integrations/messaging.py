"""Send a message on any channel, without knowing who carries it.

This is the surface `sms.py` and `whatsapp.py` are thin names over. A feature
asks one of those for a channel it already knows it wants — SMS, WhatsApp —
and neither of those files does anything but hand the call here with its
channel filled in, so that whichever vendor actually carries the message is
never something the feature learns.

What happens on the way through:

    resolve the school's provider   (resolver.py — the only place that picks)
            ↓
    find the registered template    (templates.py — no channel sends free text)
            ↓
    call it, with a timeout         (the client, over http.py)
            ↓
    normalize the result            (results.py — no vendor shapes escape)
            ↓
    record what happened            (Phase 2's usage ledger)

**It records what happened. It does not work out what that costs.** Billing
reads the ledger and applies a school's terms; nothing here multiplies a rate
by a quantity, and nothing here imports a billing calculation.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .capabilities import CAPABILITY_SMS, MESSAGING_CAPABILITIES
from .errors import IntegrationError, UnknownCapability
from .operations import new_operation_id, redact_destination
from .resolver import resolve_provider
from .results import MessageSendResult, ProviderHealth
from .templates import template_for
from .usage_recorder import record_provider_usage

logger = logging.getLogger(__name__)


def send_message(
    *,
    tenant_id: str,
    channel: str,
    purpose: str,
    destination: str,
    variables: list,
    body: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> MessageSendResult:
    """Ask this school's provider for `channel` to send one message.

    `purpose` is what the message is for — `authentication_otp`, `fee_reminder`. It
    selects the registered template and becomes the usage record's
    `usage_type`, so a bill can be explained back to the feature that caused
    it.

    `body` is the rendered text, needed by SMS and ignored by WhatsApp, which
    takes only the template name and the variables.

    Returns a result rather than raising, including when the school has no
    provider and when it has no template. A caller deciding whether to tell
    somebody to wait should not have to catch an exception to find out.
    """
    operation_id = new_operation_id()

    if channel not in MESSAGING_CAPABILITIES:
        raise UnknownCapability(channel)

    try:
        resolved = resolve_provider(tenant_id=tenant_id, capability=channel)
        template = template_for(resolved.configuration, purpose)
    except IntegrationError as exc:
        logger.warning(
            "message not sent: %s (tenant=%s channel=%s purpose=%s operation=%s)",
            exc.code,
            tenant_id,
            channel,
            purpose,
            operation_id,
        )
        return MessageSendResult(
            success=False,
            error_code=exc.code,
            error_message=exc.message,
            retryable=exc.retryable,
            operation_id=operation_id,
            billable_units=0,
        )

    started = time.monotonic()
    try:
        if channel == CAPABILITY_SMS:
            result = resolved.client.send(
                destination=destination,
                body=body or "",
                template_id=template,
                configuration=resolved.configuration,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
            )
        else:
            result = resolved.client.send(
                destination=destination,
                template_name=template,
                variables=list(variables or []),
                configuration=resolved.configuration,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
            )
    except Exception:  # noqa: BLE001 - a client bug must not become a 500
        logger.exception(
            "provider %s raised while sending (tenant=%s operation=%s)",
            resolved.provider_key,
            tenant_id,
            operation_id,
        )
        return MessageSendResult(
            success=False,
            error_code="unknown_provider_error",
            error_message="The provider could not be reached.",
            operation_id=operation_id,
            billable_units=0,
        )

    result.operation_id = operation_id
    result.latency_ms = int((time.monotonic() - started) * 1000)

    # Everything a support engineer needs and nothing they must not have: no
    # message body — for OTP that *is* the secret — no credential, and the
    # destination reduced to a correlation key with two digits on it.
    logger.info(
        "%s %s via %s (tenant=%s purpose=%s to=%s operation=%s latency=%dms%s)",
        channel,
        "accepted" if result.success else "failed",
        resolved.provider_key,
        tenant_id,
        purpose,
        redact_destination(destination),
        operation_id,
        result.latency_ms or 0,
        f" error={result.error_code}" if result.error_code else "",
    )

    if result.is_billable:
        record_provider_usage(
            tenant_id=tenant_id,
            capability=channel,
            provider_key=resolved.provider_key,
            result=result,
            purpose=purpose,
        )

    return result


def messaging_health(tenant_id: str, channel: str) -> ProviderHealth:
    """Whether this school's provider for that channel looks usable.

    **Sends nothing**, for the reason `health.py` gives at length.
    """
    from .health import capability_health

    return capability_health(tenant_id=tenant_id, capability=channel)
