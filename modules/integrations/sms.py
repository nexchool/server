"""Send an SMS, without knowing who sends it.

This is the surface a feature uses. Phase 4's OTP will call `send_sms` and
will never learn which company carried the message, what it cost, or how the
provider reports failure — that is the boundary the whole module exists to
draw.

What happens on the way through:

    resolve the school's provider   (resolver.py — the only place that picks)
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

from .capabilities import CAPABILITY_SMS
from .errors import IntegrationError
from .operations import new_operation_id, redact_destination
from .resolver import resolve_provider
from .results import MessageSendResult
from .usage_recorder import record_provider_usage

logger = logging.getLogger(__name__)


def send_sms(
    *,
    tenant_id: str,
    destination: str,
    message: str,
    purpose: str,
    idempotency_key: Optional[str] = None,
) -> MessageSendResult:
    """Ask this school's SMS provider to send one message.

    `purpose` is what the message is for — `login_otp`, `fee_reminder`. It
    becomes the usage record's `usage_type`, so a bill can be explained back
    to the feature that caused it.

    `idempotency_key` should be stable for a logical send: the same key
    retried must not produce a second message. Whether the provider honours it
    is the provider's own declaration (`supports_idempotency`), and where it
    does not, this function does not retry — see `errors.TIMEOUT`.

    Returns a result rather than raising, including when the school has no
    provider configured. A caller deciding whether to fall back to another
    channel should not have to catch an exception to find out.
    """
    operation_id = new_operation_id()

    try:
        resolved = resolve_provider(tenant_id=tenant_id, capability=CAPABILITY_SMS)
    except IntegrationError as exc:
        logger.warning(
            "sms not sent: %s (tenant=%s purpose=%s operation=%s)",
            exc.code,
            tenant_id,
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
        result = resolved.client.send(
            destination=destination,
            body=message,
            template_id=None,
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
        "sms %s via %s (tenant=%s purpose=%s to=%s operation=%s latency=%dms%s)",
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
            capability=CAPABILITY_SMS,
            provider_key=resolved.provider_key,
            result=result,
            purpose=purpose,
        )

    return result


def sms_health(tenant_id: str):
    """Whether this school's SMS integration looks usable.

    **Sends nothing.** Finding out whether an SMS integration works by sending
    an SMS charges the school and bothers whoever owns the number, so this
    reports configuration readiness and says plainly when delivery was not
    verified.
    """
    from .health import capability_health

    return capability_health(tenant_id=tenant_id, capability=CAPABILITY_SMS)
