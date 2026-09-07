"""What NexSchool buys from other people, and what it charges schools for it.

Four tables, in the order the money moves:

    ServiceProvider   — the vendor. An SMS company.
    ProviderService   — the thing NexSchool buys from them. SMS. Transactional
                        email. One provider may sell several.
    TenantService     — this school uses that service, at these prices.
    ServiceUsageRecord— this much of it was actually consumed, this once.

The first two are a **global catalog**: they describe the world, not a school,
so they are plain `db.Model` and carry no tenant. The last two are a school's
own business and inherit `TenantBaseModel`, which is what applies the query
scope — a model holding tenant data that does not inherit it is simply
unscoped, however it is annotated.

Two things are deliberately kept apart everywhere below.

**Provider cost and customer price are separate columns and never derived from
each other.** NexSchool may absorb a cost, mark it up, charge a flat fee, or
change provider without changing what a school pays. A model that stored one
number and a margin would make each of those a migration.

**Secrets are not here.** An API key is not billing data. Provider credentials
live where the integration that uses them lives; this module never needs one,
so it has nowhere to put one.
"""

from __future__ import annotations

import uuid

from core.database import db
from core.models import TenantBaseModel
from core.school_time import utc_now

from .constants import DEFAULT_CURRENCY, PRICING_METERED, PRICING_MODES


def _new_id() -> str:
    return str(uuid.uuid4())


class ServiceProvider(db.Model):
    """An outside company NexSchool buys something from.

    Global on purpose: which vendor NexSchool uses is NexSchool's business
    decision, not a per-school setting, and two schools on the same SMS
    provider should not produce two rows that can disagree about its name.
    """

    __tablename__ = "service_providers"

    id = db.Column(db.String(36), primary_key=True, default=_new_id)
    #: How code names this provider. Stable; the display name may be edited.
    key = db.Column(db.String(60), nullable=False, unique=True)
    name = db.Column(db.Text, nullable=False)
    #: Retiring a provider must not delete the history of what it cost, so
    #: this is a flag rather than a delete.
    is_active = db.Column(
        db.Boolean, nullable=False, default=True, server_default=db.text("true")
    )

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    services = db.relationship(
        "ProviderService", back_populates="provider", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "is_active": self.is_active,
        }

    def __repr__(self):
        return f"<ServiceProvider {self.key}>"


class ProviderService(db.Model):
    """One thing a provider sells, in the unit it sells it by.

    `unit` is what makes a quantity mean something — 1,000 of a service is
    1,000 messages or 1,000 emails or 1,000 verifications, and a usage record
    that did not carry its unit would be a number nobody could price.

    `provider_unit_cost` is the catalog rate: what the provider charges
    NexSchool. It is the default a school's configuration may override, and it
    is **never** shown to a school (see `billing/calculation.py`).
    """

    __tablename__ = "provider_services"

    id = db.Column(db.String(36), primary_key=True, default=_new_id)
    provider_id = db.Column(
        db.String(36),
        db.ForeignKey("service_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key = db.Column(db.String(60), nullable=False)
    name = db.Column(db.Text, nullable=False)
    #: "sms", "email", "verification" — the thing one unit of quantity is.
    unit = db.Column(db.String(30), nullable=False)
    pricing_mode = db.Column(
        db.String(30),
        nullable=False,
        default=PRICING_METERED,
        server_default=PRICING_METERED,
    )
    #: What the provider charges NexSchool per unit. Internal.
    provider_unit_cost = db.Column(db.Numeric(12, 4), nullable=True)
    currency = db.Column(
        db.String(3), nullable=False, default=DEFAULT_CURRENCY,
        server_default=DEFAULT_CURRENCY,
    )
    is_active = db.Column(
        db.Boolean, nullable=False, default=True, server_default=db.text("true")
    )

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    provider = db.relationship("ServiceProvider", back_populates="services")

    __table_args__ = (
        db.UniqueConstraint("provider_id", "key", name="uq_provider_services_key"),
        db.CheckConstraint(
            "pricing_mode IN " + str(tuple(PRICING_MODES)),
            name="ck_provider_services_pricing_mode",
        ),
    )

    def to_dict(self, *, include_provider_cost: bool = False):
        """The catalog entry.

        `include_provider_cost` defaults to **False**, and that default is the
        safety property: what NexSchool pays its vendor is not something a
        school is entitled to see, and a serializer that included it by
        accident would leak it everywhere at once.
        """
        payload = {
            "id": self.id,
            "provider_id": self.provider_id,
            "provider_key": self.provider.key if self.provider else None,
            "key": self.key,
            "name": self.name,
            "unit": self.unit,
            "pricing_mode": self.pricing_mode,
            "currency": self.currency,
            "is_active": self.is_active,
        }
        if include_provider_cost:
            payload["provider_unit_cost"] = (
                float(self.provider_unit_cost)
                if self.provider_unit_cost is not None
                else None
            )
        return payload

    def __repr__(self):
        return f"<ProviderService {self.key} per {self.unit}>"


class TenantService(TenantBaseModel):
    """This school uses that service, at these prices.

    Every price here is nullable and every one falls back to the catalog,
    because the common case is a school on standard rates and the interesting
    case is the one school that negotiated something. What is *not* nullable
    is the distinction: `provider_unit_cost` is what NexSchool pays, and
    `customer_unit_price` / `customer_fixed_price` are what the school pays.
    Neither is ever computed from the other unless `pass_through` says so, and
    `pass_through` says so out loud.
    """

    __tablename__ = "tenant_services"

    id = db.Column(db.String(36), primary_key=True, default=_new_id)
    service_id = db.Column(
        db.String(36),
        db.ForeignKey("provider_services.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    #: A school can stop using a service without losing what it already spent.
    is_enabled = db.Column(
        db.Boolean, nullable=False, default=True, server_default=db.text("true")
    )
    #: Overrides the catalog mode when this school is on different terms.
    pricing_mode = db.Column(db.String(30), nullable=True)
    #: What this school pays per unit, when metered.
    customer_unit_price = db.Column(db.Numeric(12, 4), nullable=True)
    #: What this school pays per year, when fixed.
    customer_fixed_price = db.Column(db.Numeric(12, 2), nullable=True)
    #: What the provider charges NexSchool for this school, if not the catalog rate.
    provider_unit_cost = db.Column(db.Numeric(12, 4), nullable=True)
    #: How much an operator expects this school to use in a year. When set, it
    #: is what the annual estimate stands on; when not, the estimate says it is
    #: annualising observed usage instead.
    estimated_annual_quantity = db.Column(db.Numeric(14, 2), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    service = db.relationship("ProviderService")

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "service_id", name="uq_tenant_services_service"),
        db.Index("idx_tenant_services_tenant_id", "tenant_id"),
    )

    def __repr__(self):
        return f"<TenantService tenant={self.tenant_id} service={self.service_id}>"


class ServiceUsageRecord(TenantBaseModel):
    """This much was consumed, this once.

    A ledger, not a counter. `tenant_usage` — the only usage NexSchool tracked
    before this — holds one row per school and overwrites it, so there is no
    record of what was true last month and no way to bill for a past period.
    Metered services cannot work that way: the whole question is how much was
    used *between two dates*.

    `external_reference` is the idempotency key and the reason this is safe to
    point at a webhook. A provider that reports the same delivery twice — a
    retry, a replayed batch — must not turn one message into two, and the way
    to prevent that is to record *which* event this row is, not to notice that
    two rows look alike. Two genuinely separate SMS sent in the same second
    with the same quantity are two rows, and must stay two rows.
    """

    __tablename__ = "service_usage_records"

    id = db.Column(db.String(36), primary_key=True, default=_new_id)
    tenant_service_id = db.Column(
        db.String(36),
        db.ForeignKey("tenant_services.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: How much. Fractional units are allowed because some providers meter that
    #: way (a long SMS is billed as several); a school reading it sees a count.
    quantity = db.Column(db.Numeric(14, 4), nullable=False)
    #: Copied from the service at write time. A catalog that later changes its
    #: unit must not silently reinterpret history.
    unit = db.Column(db.String(30), nullable=False)
    #: What produced this. "sms_otp_sent", "invoice_email" — the emitting
    #: feature, so a bill can be explained back to the thing that caused it.
    usage_type = db.Column(db.String(60), nullable=False)
    occurred_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    #: Who says so — the subsystem that recorded it.
    source = db.Column(db.String(60), nullable=True)
    #: The provider's own id for this event. Unique per school and service; see
    #: the class docstring.
    external_reference = db.Column(db.String(120), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    tenant_service = db.relationship("TenantService")

    __table_args__ = (
        db.Index("idx_service_usage_tenant_service", "tenant_id", "tenant_service_id"),
        db.Index("idx_service_usage_occurred_at", "tenant_id", "occurred_at"),
        # Partial, so the many rows with no provider id do not collide with
        # each other — an event with no reference is simply not deduplicable,
        # and pretending otherwise would drop real usage.
        db.Index(
            "uq_service_usage_external_reference",
            "tenant_id",
            "tenant_service_id",
            "external_reference",
            unique=True,
            postgresql_where=db.text("external_reference IS NOT NULL"),
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_service_id": self.tenant_service_id,
            "quantity": float(self.quantity),
            "unit": self.unit,
            "usage_type": self.usage_type,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "source": self.source,
            "external_reference": self.external_reference,
        }

    def __repr__(self):
        return f"<ServiceUsageRecord {self.quantity} {self.unit}>"
