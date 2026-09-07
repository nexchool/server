"""Recording what a school actually consumed.

Separate from `modules/subscription/usage.py` on purpose, and the difference
is worth stating because the names are similar. That module answers "how many
students does this school have right now" — one number per school, overwritten
in place, no history. This one is a **ledger**: every consumption event is its
own row, kept, and answerable between two dates. A metered service cannot be
billed from a counter that forgets.

Nothing in NexSchool emits usage yet. This is the mechanism a future
integration will call — when OTP is built it will record `sms_otp_sent` here
and stop, and this module will do the arithmetic. The authentication code will
never multiply a rate by a quantity.

There is deliberately **no HTTP endpoint** for writing usage. Usage is written
by NexSchool's own subsystems inside a request that is already authenticated
and already tenant-scoped; an endpoint would be a way to write billing data
from outside, and nothing needs one yet.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from core.database import db
from core.school_time import utc_now

from .models import ServiceUsageRecord, TenantService

logger = logging.getLogger(__name__)


class UnknownService(Exception):
    """This school is not configured for that service."""


def record_usage(
    *,
    tenant_id: str,
    service_key: str,
    quantity,
    usage_type: str,
    provider_key: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    source: Optional[str] = None,
    external_reference: Optional[str] = None,
) -> Optional[ServiceUsageRecord]:
    """Write down one consumption event. Returns None if it was already written.

    **The same provider event never becomes two rows.** When the caller can
    name the event — a provider's message id, a webhook delivery id — that
    name is stored and a second attempt with it is a no-op. The check is a
    unique index, not a read-then-write, so two workers racing on the same
    retry still produce one row.

    What this deliberately does *not* do is deduplicate rows that merely look
    alike. Two OTPs sent to two parents in the same second with quantity 1 are
    two real messages; treating them as one would lose usage a provider is
    going to charge for. An event with no reference is simply not deduplicable,
    and is recorded.

    `provider_key` names which vendor did the work. It is optional because a
    school with one supplier of a service does not need to say, and required
    in practice as soon as it has two — see `_service_for`.
    """
    configuration = _service_for(tenant_id, service_key, provider_key=provider_key)

    record = ServiceUsageRecord(
        tenant_id=tenant_id,
        tenant_service_id=configuration.id,
        quantity=Decimal(str(quantity)),
        # Copied, not referenced: a catalog that later changes its unit must
        # not silently reinterpret what was already recorded.
        unit=configuration.service.unit,
        usage_type=usage_type,
        occurred_at=occurred_at or utc_now(),
        source=source,
        external_reference=external_reference,
    )

    try:
        with db.session.begin_nested():
            db.session.add(record)
    except IntegrityError:
        # The index did its job. A replayed webhook is an ordinary event, not
        # an error, so this is reported by returning None rather than raising.
        logger.info(
            "usage event already recorded (tenant=%s service=%s)",
            tenant_id,
            service_key,
        )
        return None

    return record


class AmbiguousService(Exception):
    """This school buys that service from more than one vendor."""


def _service_for(
    tenant_id: str, service_key: str, *, provider_key: Optional[str] = None
) -> TenantService:
    """This school's configuration for a service, by the service's key.

    A service key is unique per *provider*, not globally — two vendors may
    both sell something keyed `sms`. So a school that buys SMS from two
    companies has two rows here, and a lookup by key alone has two answers.

    Written originally with `.first()` and no provider filter, which was
    harmless while nothing could route a school to a second vendor and stopped
    being harmless the moment per-tenant provider selection existed: usage
    would have been billed against whichever row the database happened to
    return, at whichever vendor's rates. Now the caller names the provider
    when it knows one, and genuine ambiguity is **refused rather than guessed**
    — a charge against an arbitrary supplier is worse than a charge that fails
    loudly.
    """
    from .models import ProviderService, ServiceProvider

    query = TenantService.query.join(
        ProviderService, TenantService.service_id == ProviderService.id
    ).filter(
        TenantService.tenant_id == tenant_id,
        ProviderService.key == service_key,
    )

    if provider_key:
        query = query.join(
            ServiceProvider, ProviderService.provider_id == ServiceProvider.id
        ).filter(ServiceProvider.key == provider_key)

    matches = query.order_by(TenantService.id).all()

    if not matches:
        raise UnknownService(
            f"This school is not configured for the service '{service_key}'"
            + (f" from '{provider_key}'." if provider_key else ".")
        )
    if len(matches) > 1:
        raise AmbiguousService(
            f"This school buys '{service_key}' from more than one provider. "
            "Name the provider when recording usage."
        )
    return matches[0]


def usage_total(
    tenant_service_id: str,
    *,
    tenant_id: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> Decimal:
    """How much of this service the school used, between two moments.

    Scoped by tenant explicitly as well as by the ORM's own tenant filter —
    belt and suspenders, because this number becomes money.
    """
    query = db.session.query(func.coalesce(func.sum(ServiceUsageRecord.quantity), 0)).filter(
        ServiceUsageRecord.tenant_id == tenant_id,
        ServiceUsageRecord.tenant_service_id == tenant_service_id,
    )
    if since is not None:
        query = query.filter(ServiceUsageRecord.occurred_at >= since)
    if until is not None:
        query = query.filter(ServiceUsageRecord.occurred_at <= until)

    return Decimal(str(query.scalar() or 0))


#: How far back an annualisation looks when nobody configured an estimate.
#: Long enough to smooth a quiet week, short enough that a school's usage
#: pattern from last year does not dominate this year's projection.
OBSERVATION_WINDOW_DAYS = 90


def observed_usage(tenant_service_id: str, *, tenant_id: str, now=None):
    """Recent usage and the number of days it was spread over.

    Returned as a pair so the caller can annualise it and *say* that it did.
    The window is the shorter of `OBSERVATION_WINDOW_DAYS` and the time since
    the first record, so a service switched on last Tuesday is not projected
    as if it had been idle for three months.
    """
    now = now or utc_now()
    window_start = now - timedelta(days=OBSERVATION_WINDOW_DAYS)

    first_seen = (
        db.session.query(func.min(ServiceUsageRecord.occurred_at))
        .filter(
            ServiceUsageRecord.tenant_id == tenant_id,
            ServiceUsageRecord.tenant_service_id == tenant_service_id,
        )
        .scalar()
    )
    if first_seen is None:
        return Decimal("0"), 0

    since = max(window_start, first_seen)
    quantity = usage_total(tenant_service_id, tenant_id=tenant_id, since=since, until=now)

    days = max((now - since).days, 1)
    return quantity, days
