"""Writing down that a provider did something billable.

The one place the integration layer touches billing, and it touches it in one
direction: it records **what happened**. What that costs is billing's
question, answered later from a school's stored terms, and nothing in this
module imports a billing calculation.

    integration  →  usage  →  billing

never

    integration  →  billing calculation

A failure to record is deliberately not a failure to send. The message has
already gone; raising here would tell a caller the send failed when it did
not, and would invite a retry that sends a second one. So this logs loudly and
returns — an unbilled message is a smaller problem than a duplicated one.
"""

from __future__ import annotations

import logging
from typing import Optional

from .results import MessageSendResult

logger = logging.getLogger(__name__)


def record_provider_usage(
    *,
    tenant_id: str,
    capability: str,
    provider_key: str,
    result: MessageSendResult,
    purpose: str,
) -> Optional[object]:
    """Record one billable provider operation in the usage ledger.

    The provider's own message id becomes Phase 2's `external_reference`, so
    idempotency is the provider's identity rather than a second deduplication
    scheme invented here: a replayed delivery callback naming the same message
    cannot bill it twice.

    Where a provider returns no id, the operation id is used instead. That is
    a deliberate and weaker fallback — it is unique per call rather than per
    message, so it makes *this* write idempotent without making a provider's
    repeated report of the same send idempotent. A provider that returns no
    reference cannot have exactly-once billing, and saying so is better than
    implying otherwise.
    """
    from modules.billing.usage import UnknownService, record_usage

    reference = result.provider_message_id or result.operation_id

    try:
        record = record_usage(
            tenant_id=tenant_id,
            service_key=capability,
            provider_key=provider_key,
            quantity=result.billable_units,
            usage_type=purpose,
            source=f"integration:{provider_key}",
            external_reference=reference,
        )
    except UnknownService:
        # The school is routed to a provider it has no commercial terms for.
        # Real, and an operator has to fix it — but the message is already
        # sent, so this is reported rather than raised.
        logger.error(
            "provider usage could not be recorded: no %s service configured "
            "for this school (tenant=%s provider=%s operation=%s)",
            capability,
            tenant_id,
            provider_key,
            result.operation_id,
        )
        return None
    except Exception:  # noqa: BLE001 - never turn a sent message into a failure
        logger.exception(
            "provider usage could not be recorded (tenant=%s provider=%s operation=%s)",
            tenant_id,
            provider_key,
            result.operation_id,
        )
        return None

    if record is None:
        logger.info(
            "provider usage already recorded (tenant=%s provider=%s reference=%s)",
            tenant_id,
            provider_key,
            reference,
        )
    return record
