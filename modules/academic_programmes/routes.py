"""
AcademicProgramme Routes

REST API for academic programmes (board + optional medium). Mounted at /api/programmes.
"""

from flask import g, request

from core.decorators import (
    auth_required,
    tenant_required,
    require_feature,
    require_permission,
    require_any_permission,
)
from shared.helpers import (
    error_response,
    not_found_response,
    success_response,
    validation_error_response,
)
from . import academic_programmes_bp, services


PERM_READ = "programme.read"
PERM_MANAGE = "programme.manage"


@academic_programmes_bp.route("/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def list_programmes():
    status = request.args.get("status")
    return success_response(
        data=services.list_programmes(g.tenant_id, status=status),
    )


@academic_programmes_bp.route("/", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def create_programme():
    data = request.get_json() or {}
    for field in ("board", "code"):
        if not data.get(field):
            return validation_error_response({"message": f"{field} is required"})

    result = services.create_programme(data, g.tenant_id)
    if result["success"]:
        return success_response(
            data=result["programme"],
            message="Programme created successfully",
            status_code=201,
        )
    return error_response("CreationError", result["error"], 400)


@academic_programmes_bp.route("/<programme_id>", methods=["GET"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_programme(programme_id):
    programme = services.get_programme(programme_id, g.tenant_id)
    if not programme:
        return not_found_response("Programme")
    return success_response(data=programme)


@academic_programmes_bp.route("/<programme_id>", methods=["PATCH", "PUT"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def update_programme(programme_id):
    data = request.get_json() or {}
    result = services.update_programme(programme_id, data, g.tenant_id)
    if result["success"]:
        return success_response(
            data=result["programme"],
            message="Programme updated successfully",
        )
    if result.get("error") == "Programme not found":
        return not_found_response("Programme")
    return error_response("UpdateError", result["error"], 400)


@academic_programmes_bp.route("/<programme_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def delete_programme(programme_id):
    result = services.delete_programme(programme_id, g.tenant_id)
    if result["success"]:
        return success_response(message="Programme deleted successfully")
    if result.get("error") == "Programme not found":
        return not_found_response("Programme")
    return error_response("DeleteError", result["error"], 400)
