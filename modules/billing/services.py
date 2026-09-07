"""Assembling a school's year, and keeping the catalog.

The one function everything else should call is `tenant_annual_statement`. It
is the authoritative answer to "what will this school pay over a year", and it
is additive: the NexSchool subscription, then one component per third-party
service the school uses. A school using none gets a total identical to its
subscription — which is what keeps every existing tenant's bill exactly where
it was before this module existed.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from core.database import db
from core.models import Tenant
from core.school_time import school_today

from . import calculation
from .constants import PRICING_MODES
from .models import ProviderService, ServiceProvider, TenantService
from .usage import observed_usage


class BillingConfigurationError(Exception):
    """The catalog or a school's configuration was asked for something invalid."""


# ---------------------------------------------------------------------------
# The statement
# ---------------------------------------------------------------------------

def tenant_annual_statement(
    tenant_id: str,
    *,
    active_students: int,
    on_date: Optional[date] = None,
) -> Optional[Dict]:
    """Everything this school is estimated to pay over a year.

    `active_students` is supplied by the caller rather than counted here,
    because the two existing callers legitimately differ: the platform view
    counts live, and the school's own dashboard reads the usage snapshot it
    already has. What they no longer differ about is the arithmetic.

    Returns None when the tenant does not exist, so the caller can 404.
    """
    tenant = db.session.get(Tenant, tenant_id)
    if tenant is None:
        return None

    subscription = calculation.subscription_component(
        tenant, active_students, on_date=on_date or school_today()
    )
    return calculation.annual_statement(subscription, tenant_service_components(tenant_id))


def tenant_service_components(tenant_id: str) -> List[Dict]:
    """One estimate per third-party service this school is signed up to.

    Disabled services are left out of the money but the configuration survives
    — a school that pauses SMS over the summer has not lost its rates.
    """
    configurations = (
        TenantService.query.filter(TenantService.tenant_id == tenant_id)
        .filter(TenantService.is_enabled.is_(True))
        .join(ProviderService, TenantService.service_id == ProviderService.id)
        .order_by(ProviderService.key)
        .all()
    )

    components = []
    for configuration in configurations:
        quantity, days = observed_usage(configuration.id, tenant_id=tenant_id)
        components.append(
            calculation.annual_estimate(
                configuration, observed_quantity=quantity, observed_over_days=days
            )
        )
    return components


# ---------------------------------------------------------------------------
# The catalog — what NexSchool buys, and from whom
# ---------------------------------------------------------------------------

def list_providers(*, include_inactive: bool = False) -> List[Dict]:
    query = ServiceProvider.query
    if not include_inactive:
        query = query.filter(ServiceProvider.is_active.is_(True))

    providers = query.order_by(ServiceProvider.key).all()
    return [
        {
            **provider.to_dict(),
            "services": [
                service.to_dict(include_provider_cost=True)
                for service in sorted(provider.services, key=lambda s: s.key)
            ],
        }
        for provider in providers
    ]


def upsert_provider(*, key: str, name: str, is_active: bool = True) -> ServiceProvider:
    """Add a vendor, or correct one. Keyed, so this is safe to re-run."""
    key = (key or "").strip().lower()
    if not key:
        raise BillingConfigurationError("A provider needs a key.")

    provider = ServiceProvider.query.filter_by(key=key).first()
    if provider is None:
        provider = ServiceProvider(key=key, name=name or key)
        db.session.add(provider)
    else:
        provider.name = name or provider.name
    provider.is_active = is_active
    db.session.flush()
    return provider


def upsert_service(
    *,
    provider_key: str,
    key: str,
    name: str,
    unit: str,
    pricing_mode: str,
    provider_unit_cost=None,
    is_active: bool = True,
) -> ProviderService:
    """Add or correct one thing a provider sells."""
    if pricing_mode not in PRICING_MODES:
        raise BillingConfigurationError(
            f"'{pricing_mode}' is not a pricing mode. Expected one of: "
            + ", ".join(PRICING_MODES)
        )

    provider = ServiceProvider.query.filter_by(key=(provider_key or "").strip().lower()).first()
    if provider is None:
        raise BillingConfigurationError(f"No provider with the key '{provider_key}'.")

    key = (key or "").strip().lower()
    if not key:
        raise BillingConfigurationError("A service needs a key.")
    if not (unit or "").strip():
        raise BillingConfigurationError("A service needs a unit — what one of it is.")

    service = ProviderService.query.filter_by(provider_id=provider.id, key=key).first()
    if service is None:
        service = ProviderService(provider_id=provider.id, key=key)
        db.session.add(service)

    service.name = name or key
    service.unit = unit.strip()
    service.pricing_mode = pricing_mode
    service.provider_unit_cost = provider_unit_cost
    service.is_active = is_active
    db.session.flush()
    return service


# ---------------------------------------------------------------------------
# A school's own configuration
# ---------------------------------------------------------------------------

def _catalog_service(service_key: str, provider_key: Optional[str]) -> ProviderService:
    """One catalog entry, named unambiguously.

    `ProviderService.key` is unique per provider, not globally — see
    `configure_tenant_service`. Two vendors selling `sms` is a legitimate
    state, and a lookup that silently took the first of them would attach a
    school to an arbitrary supplier's terms.
    """
    query = ProviderService.query.filter(
        ProviderService.key == (service_key or "").strip().lower()
    )
    if provider_key:
        query = query.join(
            ServiceProvider, ProviderService.provider_id == ServiceProvider.id
        ).filter(ServiceProvider.key == (provider_key or "").strip().lower())

    matches = query.order_by(ProviderService.id).all()
    if not matches:
        raise BillingConfigurationError(
            f"No service with the key '{service_key}'"
            + (f" from '{provider_key}'." if provider_key else ".")
        )
    if len(matches) > 1:
        raise BillingConfigurationError(
            f"More than one provider sells '{service_key}'. Name the provider."
        )
    return matches[0]

def configure_tenant_service(
    tenant_id: str,
    *,
    service_key: str,
    provider_key: Optional[str] = None,
    is_enabled: bool = True,
    pricing_mode: Optional[str] = None,
    customer_unit_price=None,
    customer_fixed_price=None,
    provider_unit_cost=None,
    estimated_annual_quantity=None,
) -> TenantService:
    """Sign a school up to a service, or change its terms.

    Every price is optional and falls back to the catalog. What is not
    negotiable is that the school's price and NexSchool's cost are set
    separately — there is no argument here that derives one from the other.

    `provider_key` names the vendor. A service key is unique per provider
    rather than globally, so two companies can both sell something keyed
    `sms`; naming one is optional while a school has a single supplier and
    required as soon as it has two. Ambiguity is refused rather than resolved
    by picking whichever row the database returned first.
    """
    if pricing_mode is not None and pricing_mode not in PRICING_MODES:
        raise BillingConfigurationError(
            f"'{pricing_mode}' is not a pricing mode. Expected one of: "
            + ", ".join(PRICING_MODES)
        )

    service = _catalog_service(service_key, provider_key)

    configuration = TenantService.query.filter_by(
        tenant_id=tenant_id, service_id=service.id
    ).first()
    if configuration is None:
        configuration = TenantService(tenant_id=tenant_id, service_id=service.id)
        db.session.add(configuration)

    configuration.is_enabled = is_enabled
    configuration.pricing_mode = pricing_mode
    configuration.customer_unit_price = customer_unit_price
    configuration.customer_fixed_price = customer_fixed_price
    configuration.provider_unit_cost = provider_unit_cost
    configuration.estimated_annual_quantity = estimated_annual_quantity
    db.session.flush()
    return configuration


def describe_tenant_services(tenant_id: str) -> List[Dict]:
    """A school's configured services, enabled or not, for an operator's screen."""
    configurations = (
        TenantService.query.filter(TenantService.tenant_id == tenant_id)
        .join(ProviderService, TenantService.service_id == ProviderService.id)
        .order_by(ProviderService.key)
        .all()
    )

    described = []
    for configuration in configurations:
        quantity, days = observed_usage(configuration.id, tenant_id=tenant_id)
        described.append(
            {
                **calculation.annual_estimate(
                    configuration, observed_quantity=quantity, observed_over_days=days
                ),
                "tenant_service_id": configuration.id,
                "recent_usage_quantity": float(quantity),
                "recent_usage_days": days,
                "customer_unit_price": (
                    float(configuration.customer_unit_price)
                    if configuration.customer_unit_price is not None
                    else None
                ),
                "customer_fixed_price": (
                    float(configuration.customer_fixed_price)
                    if configuration.customer_fixed_price is not None
                    else None
                ),
            }
        )
    return described
