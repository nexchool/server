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
from .errors import CONFIGURATION_ERROR, IntegrationError, UnknownCapability
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
        if channel == CAPABILITY_SMS:
            values = list(variables or [])
            if len(values) != len(template.variables):
                # Zipping without this check would silently truncate to the
                # shorter side — an SMS reading "your code is" — and the only
                # way to learn that would be a vendor's rejection or, worse,
                # the message a person actually received. CONFIGURATION_ERROR
                # because a school's own template registration is what is
                # wrong (too few — or, for a vendor like MSG91 that has no
                # free-text field at all, too many — named slots), not the
                # request: the same request will fail identically until an
                # operator fixes the template, so it is not retryable and it
                # belongs in the same operator-facing bucket as a missing
                # template rather than in the vendor-weather bucket a 4xx
                # would otherwise land in.
                raise IntegrationError(
                    CONFIGURATION_ERROR,
                    f"This school's '{purpose}' SMS template names "
                    f"{len(template.variables)} variable(s) but {len(values)} "
                    "were supplied.",
                )
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
            # Named, not positional: MSG91's Flow API (Task 8b) matches a
            # flow's placeholders by name. The count is already proven equal
            # above, so this zip loses nothing.
            result = resolved.client.send(
                destination=destination,
                body=body or "",
                template_id=template.id,
                configuration=resolved.configuration,
                variables=dict(zip(template.variables, variables or [])),
                idempotency_key=idempotency_key,
                operation_id=operation_id,
            )
        else:
            result = resolved.client.send(
                destination=destination,
                template_name=template.id,
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

    if resolved.client.is_test_double and result.success:
        from .outbox import record

        record(
            tenant_id=tenant_id,
            channel=channel,
            destination=destination,
            body=body or " | ".join(str(v) for v in (variables or [])),
            purpose=purpose,
        )

    return result


def messaging_health(tenant_id: str, channel: str) -> ProviderHealth:
    """Whether this school's provider for that channel looks usable.

    **Sends nothing**, for the reason `health.py` gives at length.
    """
    from .health import capability_health

    return capability_health(tenant_id=tenant_id, capability=channel)
