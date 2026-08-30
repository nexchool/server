"""
Dashboard Routes

GET /api/dashboard  —  Admin overview: one call, full system health.
"""

import logging

from flask import g

from modules.dashboard import dashboard_bp
from core.decorators import auth_required, require_permission, tenant_required
from shared.helpers import success_response, error_response
from . import service

logger = logging.getLogger(__name__)

# The overview crosses every module and includes the school's finance position,
# so it answers to a key of its own rather than to any one module's. Without
# this the route was gated on nothing but a valid login, and `build_dashboard`
# performs no authorization of its own — a pupil's account read the school's
# outstanding fees.
PERM_READ = "dashboard.read"


@dashboard_bp.route("/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission(PERM_READ)
def get_dashboard():
    """
    GET /api/dashboard

    Returns a single aggregated payload covering:
      overview, today's operations, alerts, finance, transport, and pending actions.
    """
    try:
        data = service.build_dashboard()
        if "error" in data:
            return error_response("DashboardError", data["error"], 500)
        return success_response(data=data)
    except Exception:  # noqa: BLE001
        logger.exception("Dashboard build failed")
        return error_response(
            "DashboardError", "Failed to load the dashboard. Please try again.", 500
        )
