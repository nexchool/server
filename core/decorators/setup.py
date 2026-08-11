"""
Setup-Completion Decorator

Gates write APIs that depend on the structured school-setup data
(units, programmes, grades, classes). Until the tenant has marked setup
complete, those endpoints return 403 with a stable error code so the
frontend can redirect the admin into the wizard.

Read endpoints stay open so the dashboard remains usable.
"""

from functools import wraps

from flask import jsonify, g

from core.database import db
from core.models import Tenant


def is_setup_complete(tenant_id: str) -> bool:
    """Whether this school has finished the setup wizard.

    Single column read, cached on the request so several gates in one request
    ask the database once. Shared by the REST decorator below and the GraphQL
    permission of the same name, so the two transports cannot come to
    different conclusions about when a school may start working.
    """
    cached = getattr(g, "_is_setup_complete", None)
    if cached is not None:
        return cached

    row = (
        db.session.query(Tenant.is_setup_complete)
        .filter(Tenant.id == tenant_id)
        .first()
    )
    complete = bool(row[0]) if row is not None else False
    g._is_setup_complete = complete
    return complete


def require_setup_complete(fn):
    """Block the route until tenant.is_setup_complete is true.

    Must come after @tenant_required and @auth_required so g.tenant_id is set.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Platform super-admins (god-login) may use the app while the tenant's
        # school setup is still incomplete — bypass the gate entirely.
        current_user = getattr(g, "current_user", None)
        if current_user is not None and getattr(
            current_user, "is_platform_admin", False
        ):
            return fn(*args, **kwargs)

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

        if not is_setup_complete(tenant_id):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "SetupIncomplete",
                        "message": (
                            "Complete school setup before using this feature."
                        ),
                    }
                ),
                403,
            )
        return fn(*args, **kwargs)

    return wrapper
