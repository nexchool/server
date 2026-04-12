"""
Dashboard Routes

GET /api/dashboard  —  Admin overview: one call, full system health.
"""

from flask import g

from modules.dashboard import dashboard_bp
from core.decorators import auth_required, tenant_required
from shared.helpers import success_response, error_response
from . import service


@dashboard_bp.route("/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
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
    except Exception as exc:  # noqa: BLE001
        return error_response("DashboardError", str(exc), 500)
