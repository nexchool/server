"""Academic dashboard and health."""

from flask import g

from modules.academics import academics_bp
from core.decorators import auth_required, require_any_permission, tenant_required, require_plan_feature
from shared.helpers import error_response, success_response

from modules.academics.services import dashboards

PERM_READ = "academics.read"
PERM_MANAGE = "academics.manage"


@academics_bp.route("/dashboard", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE, "class.manage")
def academic_admin_dashboard():
    r = dashboards.admin_academic_dashboard(g.tenant_id)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r)


@academics_bp.route("/health", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("academics_advanced")
@require_any_permission(PERM_READ, PERM_MANAGE, "class.manage")
def academic_health():
    r = dashboards.health_report(g.tenant_id)
    return success_response(data=r)
