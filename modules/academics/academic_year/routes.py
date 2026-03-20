"""Academic year API routes - /api/academics/academic-years."""

import logging
from flask import request, g

from backend.modules.academics import academics_bp
from backend.core.decorators import (
    require_permission,
    auth_required,
    tenant_required,
    require_plan_feature,
)
from backend.core.decorators.rbac import require_any_permission
from backend.shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
)

# Academic years are used by classes, students, finance - allow class.manage (academics hub)
PERM_READ = "class.read"
PERM_MANAGE = "class.manage"

from . import services


@academics_bp.route("/academic-years", methods=["GET"])
@tenant_required
@auth_required
def list_academic_years():
    """GET /api/academics/academic-years"""
    active_only = request.args.get("active_only", "false").lower() == "true"
    data = services.list_academic_years(active_only=active_only)
    return success_response(data={"academic_years": data})


@academics_bp.route("/academic-years", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_permission(PERM_MANAGE)
def create_academic_year():
    """POST /api/academics/academic-years"""
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    if not name or not start_date or not end_date:
        missing = [k for k, v in [("name", name), ("start_date", start_date), ("end_date", end_date)] if not v]
        logging.warning("Academic year create validation failed: missing %s, body keys=%s", missing, list(data.keys()))
        return error_response(
            "ValidationError",
            f"Missing required fields: {', '.join(missing)}",
            400,
            details={"name": "Required", "start_date": "Required", "end_date": "Required"},
        )
    result = services.create_academic_year(
        name=name,
        start_date=start_date,
        end_date=end_date,
        is_active=data.get("is_active", True),
        user_id=g.current_user.id if g.current_user else None,
    )
    if result["success"]:
        return success_response(data=result, message="Academic year created", status_code=201)
    return error_response("AcademicsError", result["error"], 400)


@academics_bp.route("/academic-years/<year_id>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_academic_year(year_id):
    """GET /api/academics/academic-years/<id>"""
    data = services.get_academic_year(year_id)
    if not data:
        return not_found_response("Academic year")
    return success_response(data=data)


@academics_bp.route("/academic-years/<year_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_permission(PERM_MANAGE)
def update_academic_year(year_id):
    """PUT /api/academics/academic-years/<id>"""
    data = request.get_json() or {}
    result = services.update_academic_year(
        year_id=year_id,
        name=data.get("name"),
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        is_active=data.get("is_active"),
        user_id=g.current_user.id if g.current_user else None,
    )
    if result["success"]:
        return success_response(data=result)
    if "not found" in result.get("error", "").lower():
        return not_found_response("Academic year")
    return error_response("AcademicsError", result["error"], 400)


@academics_bp.route("/academic-years/<year_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_permission(PERM_MANAGE)
def delete_academic_year(year_id):
    """DELETE /api/academics/academic-years/<id>"""
    result = services.delete_academic_year(
        year_id=year_id,
        user_id=g.current_user.id if g.current_user else None,
    )
    if result["success"]:
        return success_response(data=result)
    if "not found" in result.get("error", "").lower():
        return not_found_response("Academic year")
    return error_response("AcademicsError", result["error"], 400)
