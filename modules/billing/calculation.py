"""What a school owes NexSchool. One definition of it.

Before this file the arithmetic existed three times: `calculate_tenant_billing`
in the platform service, `_bill_summary` in the tenant-facing subscription
route (whose own docstring admitted it was a copy), and
`revenue_yearly / 12` on the platform dashboard. Two of them could disagree
about the same school on the same day, because one counted students live and
the other read a snapshot that is refreshed on a best-effort basis.

The fix is not to make every caller ask the same question — they legitimately
ask different ones — but to make them all do the *sum* the same way. So the
money math lives here and takes its inputs explicitly. A caller that has a
live count passes a live count; a caller holding a snapshot passes the
snapshot. Neither has an opinion about how to apply a discount any more.

Two rules this module exists to keep:

**Provider cost never becomes customer price by accident.** They are computed
separately, from separate columns, and the only mode where they are equal is
the one named `pass_through`. `customer_facing` strips provider cost from a
component entirely, so a route that forgets is still safe.

**An estimate says it is an estimate.** Every annual figure carries the basis
it stands on — an operator's configured number, an annualisation of what was
actually recorded, or nothing at all. There is no path in this file that
produces an invoice, because NexSchool does not have invoices.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from core.school_time import school_today

from .constants import (
    COMPONENT_SUBSCRIPTION,
    DEFAULT_CURRENCY,
    ESTIMATE_BASIS_CONFIGURED,
    ESTIMATE_BASIS_NONE,
    ESTIMATE_BASIS_OBSERVED,
    PRICING_FIXED,
    PRICING_METERED,
    PRICING_PASS_THROUGH,
)

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0")

#: Days in the year an annual estimate projects over. A school year and a
#: calendar year differ, but an *estimate* that changed length by month would
#: be harder to explain than one that is honestly approximate.
DAYS_IN_YEAR = 365


def _money(value) -> Decimal:
    return (Decimal(str(value)) if value is not None else ZERO).quantize(TWO_PLACES)


# ---------------------------------------------------------------------------
# The NexSchool subscription itself
# ---------------------------------------------------------------------------

def subscription_component(
    tenant, active_students: int, *, on_date: Optional[date] = None
) -> Dict:
    """Headcount × the school's rate, less a discount if today is inside its window.

    The caller supplies the headcount. That is the whole point: the platform
    view counts students live and the school's own dashboard reads the usage
    snapshot, and both of those are defensible, but there is now exactly one
    place that decides what a discount window means and how the total rounds.
    """
    on_date = on_date or school_today()

    price = tenant.price_per_student_per_year or ZERO
    base = (Decimal(price) * Decimal(active_students)).quantize(TWO_PLACES)

    discount_pct = tenant.discount_percentage or ZERO
    discount_active = False
    discount_amount = ZERO
    if discount_pct > 0:
        starts_ok = (
            tenant.discount_start_date is None or on_date >= tenant.discount_start_date
        )
        ends_ok = tenant.discount_end_date is None or on_date <= tenant.discount_end_date
        if starts_ok and ends_ok:
            discount_active = True
            discount_amount = (base * Decimal(discount_pct) / Decimal("100")).quantize(
                TWO_PLACES
            )

    return {
        "component_key": COMPONENT_SUBSCRIPTION,
        "active_students": active_students,
        "price_per_student_per_year": float(price),
        "base_amount": float(base),
        "discount_percentage": float(discount_pct) if discount_pct else 0.0,
        "discount_active": discount_active,
        "discount_amount": float(discount_amount),
        "total": float((base - discount_amount).quantize(TWO_PLACES)),
        "currency": DEFAULT_CURRENCY,
    }


def monthly_run_rate(annual_total) -> float:
    """An annual figure spread evenly over twelve months.

    Named rather than written inline so that the platform dashboard's
    "monthly revenue" tile has somewhere to be argued with. It is a run rate,
    not a bill: nothing in NexSchool bills monthly (`BILLING_CYCLES` has one
    member), no proration exists, and a school that joins in November is
    counted here as if it had been paying all year. Kept exactly as it was so
    the number on the dashboard does not move; see the debt register.
    """
    total = _money(annual_total)
    return float((total / Decimal("12")).quantize(TWO_PLACES)) if total else 0.0


# ---------------------------------------------------------------------------
# Third-party services
# ---------------------------------------------------------------------------

def _effective(tenant_service, attribute: str):
    """The school's own value if it has one, otherwise the catalog's."""
    own = getattr(tenant_service, attribute, None)
    if own is not None:
        return own
    return getattr(tenant_service.service, attribute, None)


def annual_estimate(
    tenant_service,
    *,
    observed_quantity=None,
    observed_over_days: Optional[int] = None,
) -> Dict:
    """What this service will cost, roughly, over a year.

    Three numbers that must not be confused with each other: how much will be
    used, what NexSchool will pay its provider for it, and what the school
    will be charged. Each is computed from its own inputs.

    The quantity comes from whichever basis is available, most authoritative
    first: an operator's configured annual figure, then an annualisation of
    what has actually been recorded, then zero. The answer says which, because
    an estimate whose provenance is invisible gets read as a bill.
    """
    service = tenant_service.service
    mode = _effective(tenant_service, "pricing_mode") or PRICING_METERED

    quantity, basis = _estimated_quantity(
        tenant_service, observed_quantity, observed_over_days
    )

    provider_unit_cost = _effective(tenant_service, "provider_unit_cost") or ZERO
    provider_cost = (Decimal(quantity) * Decimal(provider_unit_cost)).quantize(TWO_PLACES)

    customer_charge = _customer_charge(tenant_service, mode, quantity, provider_cost)

    return {
        "component_key": f"service:{service.key}" if service else "service:unknown",
        "service_id": tenant_service.service_id,
        "service_key": service.key if service else None,
        "service_name": service.name if service else None,
        "provider_key": service.provider.key if service and service.provider else None,
        "unit": service.unit if service else None,
        "pricing_mode": mode,
        "is_enabled": bool(tenant_service.is_enabled),
        "estimated_annual_quantity": float(quantity),
        "estimate_basis": basis,
        # Internal. `customer_facing()` removes it; see this module's docstring.
        "estimated_annual_provider_cost": float(provider_cost),
        "estimated_annual_customer_charge": float(customer_charge),
        "currency": (service.currency if service else DEFAULT_CURRENCY),
    }


def _estimated_quantity(tenant_service, observed_quantity, observed_over_days):
    """How much, and on what grounds."""
    configured = tenant_service.estimated_annual_quantity
    if configured is not None:
        return Decimal(configured).quantize(TWO_PLACES), ESTIMATE_BASIS_CONFIGURED

    if observed_quantity is None or not observed_over_days or observed_over_days <= 0:
        return ZERO, ESTIMATE_BASIS_NONE

    observed = Decimal(str(observed_quantity))
    if observed <= 0:
        return ZERO, ESTIMATE_BASIS_NONE

    annualised = (
        observed * Decimal(DAYS_IN_YEAR) / Decimal(observed_over_days)
    ).quantize(TWO_PLACES)
    return annualised, ESTIMATE_BASIS_OBSERVED


def _customer_charge(tenant_service, mode: str, quantity: Decimal, provider_cost: Decimal):
    """What the school pays. Never inferred from cost except under pass-through."""
    if mode == PRICING_FIXED:
        return _money(tenant_service.customer_fixed_price)

    if mode == PRICING_PASS_THROUGH:
        # The one mode where the two are equal, and it is equal because the
        # school was told it would be.
        return provider_cost

    unit_price = _effective(tenant_service, "customer_unit_price") or ZERO
    return (quantity * Decimal(unit_price)).quantize(TWO_PLACES)


# ---------------------------------------------------------------------------
# Putting a school's whole year together
# ---------------------------------------------------------------------------

def annual_statement(subscription: Dict, service_components: Iterable[Dict]) -> Dict:
    """The subscription plus every third-party service, and what that adds to.

    Additive by construction: a school using no third-party service gets an
    empty component list and a total identical to its subscription, which is
    what keeps every existing tenant's bill exactly where it was.
    """
    components: List[Dict] = list(service_components)

    services_total = sum(
        (_money(c["estimated_annual_customer_charge"]) for c in components), ZERO
    )
    provider_total = sum(
        (_money(c.get("estimated_annual_provider_cost", 0)) for c in components), ZERO
    )
    subscription_total = _money(subscription["total"])

    return {
        "subscription": subscription,
        "services": components,
        "subscription_total": float(subscription_total),
        "services_total": float(services_total),
        # Internal: what NexSchool spends to serve this school.
        "provider_cost_total": float(provider_total),
        "estimated_annual_total": float(
            (subscription_total + services_total).quantize(TWO_PLACES)
        ),
        "currency": DEFAULT_CURRENCY,
        # Said in the payload, not only in a doc: nothing here is an invoice.
        "is_estimate": True,
    }


PROVIDER_COST_FIELDS = (
    "estimated_annual_provider_cost",
    "provider_cost_total",
    "provider_unit_cost",
)


def customer_facing(payload):
    """The same figures with NexSchool's own costs taken out.

    A school is entitled to know what it is charged. What NexSchool pays its
    vendor is a supplier negotiation, and a school that could read it would
    know NexSchool's margin on every service.

    This strips by field name, recursively, rather than rebuilding a payload
    field by field — a whitelist would be safer against a leak but would drop
    new fields silently, and this way a component that gains a harmless field
    keeps it while anything named as a cost is removed wherever it appears.
    """
    if isinstance(payload, dict):
        return {
            key: customer_facing(value)
            for key, value in payload.items()
            if key not in PROVIDER_COST_FIELDS
        }
    if isinstance(payload, list):
        return [customer_facing(item) for item in payload]
    return payload
