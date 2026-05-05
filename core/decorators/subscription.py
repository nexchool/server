"""
Subscription Enforcement Decorator

`@require_active_subscription` blocks write APIs when the tenant's
subscription is suspended, deleted, or has an expired trial. It is
deliberately separate from `@require_setup_complete`:

  - Setup gate runs once per tenant lifetime (the wizard).
  - Subscription gate runs continuously and reflects billing state.

Read APIs, auth and the school-setup flow are intentionally NOT
gated — admins must still be able to log in, finish setup, and review
the dashboard while suspended so they can take action.
"""

from datetime import datetime
from functools import wraps

from flask import jsonify, g

from core.database import db
from core.models import (
    Tenant,
    TENANT_STATUS_ACTIVE,
    TENANT_STATUS_TRIAL,
    TENANT_STATUS_SUSPENDED,
    TENANT_STATUS_DELETED,
)


def _subscription_state(tenant_id: str) -> dict:
    """
    Resolve a normalized subscription view for the current tenant.

    Returns a dict carrying:
      - status        : raw tenants.status value
      - allow_writes  : bool — what the decorator should enforce
      - reason        : machine code clients can branch on
      - message       : human-readable explanation
    """
    cached = getattr(g, "_subscription_state", None)
    if cached is not None and cached.get("tenant_id") == tenant_id:
        return cached

    row = (
        db.session.query(Tenant.status, Tenant.trial_ends_at)
        .filter(Tenant.id == tenant_id)
        .first()
    )
    if row is None:
        state = {
            "tenant_id": tenant_id,
            "status": None,
            "allow_writes": False,
            "reason": "TenantNotFound",
            "message": "Tenant not found.",
        }
        g._subscription_state = state
        return state

    status, trial_ends_at = row[0], row[1]

    if status == TENANT_STATUS_SUSPENDED:
        state = {
            "tenant_id": tenant_id,
            "status": status,
            "allow_writes": False,
            "reason": "SubscriptionSuspended",
            "message": (
                "Your subscription is suspended. Contact support to reactivate."
            ),
        }
    elif status == TENANT_STATUS_DELETED:
        state = {
            "tenant_id": tenant_id,
            "status": status,
            "allow_writes": False,
            "reason": "TenantDeleted",
            "message": "This tenant is closed.",
        }
    elif status == TENANT_STATUS_TRIAL:
        if trial_ends_at is not None and datetime.utcnow() > trial_ends_at:
            state = {
                "tenant_id": tenant_id,
                "status": status,
                "allow_writes": False,
                "reason": "TrialExpired",
                "message": "Your trial has ended. Upgrade to keep using the app.",
                "trial_ends_at": trial_ends_at.isoformat(),
            }
        else:
            state = {
                "tenant_id": tenant_id,
                "status": status,
                "allow_writes": True,
                "reason": "Trial",
                "message": "Trial active.",
                "trial_ends_at": (
                    trial_ends_at.isoformat() if trial_ends_at else None
                ),
            }
    elif status == TENANT_STATUS_ACTIVE:
        state = {
            "tenant_id": tenant_id,
            "status": status,
            "allow_writes": True,
            "reason": "Active",
            "message": "Active subscription.",
        }
    else:
        # Unknown / NULL status — fail closed.
        state = {
            "tenant_id": tenant_id,
            "status": status,
            "allow_writes": False,
            "reason": "SubscriptionUnknown",
            "message": "Subscription state is unknown. Contact support.",
        }

    g._subscription_state = state
    return state


def require_active_subscription(fn):
    """Block writes when the tenant subscription is not in good standing.

    Must come after @tenant_required and @auth_required so g.tenant_id is set.
    Returns 402 Payment Required for billing-driven blocks (suspended /
    trial-expired) so clients can route the user into the upgrade flow.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        tenant_id = getattr(g, "tenant_id", None)
        if not tenant_id:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "TenantContextMissing",
                        "message": "Tenant context is required.",
                    }
                ),
                400,
            )

        state = _subscription_state(tenant_id)
        if state["allow_writes"]:
            return fn(*args, **kwargs)

        # 402 for billing-side blocks; 403 for tenant-deletion / unknown.
        if state["reason"] in {"SubscriptionSuspended", "TrialExpired"}:
            status_code = 402
        else:
            status_code = 403

        body = {
            "success": False,
            "error": state["reason"],
            "message": state["message"],
        }
        if "trial_ends_at" in state:
            body["trial_ends_at"] = state["trial_ends_at"]
        return jsonify(body), status_code

    return wrapper


def get_subscription_state(tenant_id: str) -> dict:
    """Public helper used by /api/subscription/state and dashboards."""
    return _subscription_state(tenant_id)
