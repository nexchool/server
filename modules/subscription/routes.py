"""
Subscription Routes (tenant-facing)

  GET /api/subscription/state
      Lightweight view used by the admin-web to render the trial /
      suspended banner and the dashboard widgets. Combines the subscription
      decision (allow_writes, reason), the tenant's current pricing, and
      the latest usage snapshot.
"""

from flask import Blueprint, g

from core.database import db
from core.decorators import (
    auth_required,
    tenant_required,
    get_subscription_state,
)
from core.models import Tenant
from shared.helpers import error_response, success_response

from .usage import get_tenant_usage


subscription_bp = Blueprint("subscription", __name__)


def _bill_summary(tenant: Tenant, active_students: int):
    """Inline mini-bill: keeps the dashboard widget self-contained without
    re-running the platform billing service per dashboard hit."""
    from decimal import Decimal
    from datetime import date

    price = tenant.price_per_student_per_year or Decimal("0")
    base = (price * Decimal(active_students)).quantize(Decimal("0.01"))

    discount_pct = tenant.discount_percentage or Decimal("0")
    today = date.today()
    discount_active = False
    discount_amount = Decimal("0")
    if discount_pct > 0:
        start_ok = (
            tenant.discount_start_date is None
            or today >= tenant.discount_start_date
        )
        end_ok = (
            tenant.discount_end_date is None
            or today <= tenant.discount_end_date
        )
        if start_ok and end_ok:
            discount_active = True
            discount_amount = (
                base * discount_pct / Decimal("100")
            ).quantize(Decimal("0.01"))

    total = (base - discount_amount).quantize(Decimal("0.01"))
    return {
        "active_students": active_students,
        "price_per_student_per_year": float(price),
        "base_amount": float(base),
        "discount_percentage": float(discount_pct) if discount_pct else 0.0,
        "discount_active": discount_active,
        "discount_amount": float(discount_amount),
        "total": float(total),
        "currency": "INR",
    }


@subscription_bp.route("/state", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
def state():
    tenant_id = g.tenant_id
    tenant = db.session.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        return error_response("NotFound", "Tenant not found", 404)

    sub = get_subscription_state(tenant_id)
    usage = get_tenant_usage(tenant_id)
    bill = _bill_summary(tenant, usage.get("active_students_count", 0))

    return success_response(
        data={
            "subscription": {
                "status": sub.get("status"),
                "allow_writes": sub.get("allow_writes"),
                "reason": sub.get("reason"),
                "message": sub.get("message"),
                "trial_ends_at": sub.get("trial_ends_at"),
                "billing_cycle": tenant.billing_cycle,
            },
            "usage": usage,
            "billing": bill,
        }
    )
