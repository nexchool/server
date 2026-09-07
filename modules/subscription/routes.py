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

from modules.billing.calculation import customer_facing
from modules.billing.services import tenant_service_components

from .usage import get_tenant_usage
from core.school_time import school_today


subscription_bp = Blueprint("subscription", __name__)


def _bill_summary(tenant: Tenant, active_students: int):
    """This school's own view of its bill.

    Was a hand-copied second implementation of the platform's billing
    arithmetic, with a docstring saying so. The copies had already drifted —
    this one never had `discount_window` — and two definitions of a discount
    window is one too many when both are money.

    The *question* is still this screen's own, and stays: it reads the usage
    snapshot the dashboard already has rather than recounting every student on
    every page load. That difference is deliberate and unchanged; only the sum
    is now shared.
    """
    from modules.billing.calculation import subscription_component

    component = subscription_component(tenant, active_students)
    return {
        "active_students": component["active_students"],
        "price_per_student_per_year": component["price_per_student_per_year"],
        "base_amount": component["base_amount"],
        "discount_percentage": component["discount_percentage"],
        "discount_active": component["discount_active"],
        "discount_amount": component["discount_amount"],
        "total": component["total"],
        "currency": component["currency"],
    }


#: What the school owes Nexchool is the school's business, not every
#: teacher's. Account *standing* stays unguarded — see `state()`.
PERM_READ_BILLING = "subscription.read"


@subscription_bp.route("/state", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
def state():
    tenant_id = g.tenant_id
    tenant = db.session.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        return error_response("NotFound", "Tenant not found", 404)

    sub = get_subscription_state(tenant_id)

    # Two audiences, one endpoint. **Standing** — is the account live, may it be
    # written to, is a trial ending — belongs to everybody: the banner that
    # carries it renders in `DashboardLayout` for every signed-in user, and a
    # teacher who cannot save attendance deserves to be told why.
    #
    # **Commercials** — headcount, price per student, discount, the total the
    # school owes Nexchool — do not. That was going to every teacher, which is
    # simply somebody else's contract.
    payload = {
        "subscription": {
            "status": sub.get("status"),
            "allow_writes": sub.get("allow_writes"),
            "reason": sub.get("reason"),
            "message": sub.get("message"),
            "trial_ends_at": sub.get("trial_ends_at"),
            "billing_cycle": tenant.billing_cycle,
        },
    }

    from modules.rbac.services import has_permission

    if has_permission(g.current_user.id, PERM_READ_BILLING):
        usage = get_tenant_usage(tenant_id)
        payload["usage"] = usage
        payload["billing"] = _bill_summary(
            tenant, usage.get("active_students_count", 0)
        )
        # Third-party services the school is signed up to, as separate line
        # items. `customer_facing` removes what NexSchool pays its providers —
        # a school is entitled to know what it is charged, not NexSchool's
        # margin — and it strips by field name wherever it appears, so a
        # component that later gains a cost field is still safe here.
        payload["services"] = customer_facing(tenant_service_components(tenant_id))

    return success_response(data=payload)
