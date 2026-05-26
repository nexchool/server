"""
SchoolUnit Routes

REST API for SchoolUnit (sub-school / campus) CRUD. Tenant + RBAC scoped.
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
from . import school_units_bp, services


PERM_READ = "school_unit.read"
PERM_MANAGE = "school_unit.manage"


@school_units_bp.route("/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def list_school_units():
    status = request.args.get("status")
    return success_response(
        data=services.list_school_units(g.tenant_id, status=status),
    )


@school_units_bp.route("/", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def create_school_unit():
    data = request.get_json() or {}
    if not data.get("name"):
        return validation_error_response({"message": "name is required"})
    if not data.get("code"):
        return validation_error_response({"message": "code is required"})

    result = services.create_school_unit(data, g.tenant_id)
    if result["success"]:
        return success_response(
            data=result["school_unit"],
            message="School unit created successfully",
            status_code=201,
        )
    return error_response("CreationError", result["error"], 400)


@school_units_bp.route("/<unit_id>", methods=["GET"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_school_unit(unit_id):
    unit = services.get_school_unit(unit_id, g.tenant_id)
    if not unit:
        return not_found_response("School unit")
    return success_response(data=unit)


@school_units_bp.route("/<unit_id>", methods=["PATCH", "PUT"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def update_school_unit(unit_id):
    data = request.get_json() or {}
    result = services.update_school_unit(unit_id, data, g.tenant_id)
    if result["success"]:
        return success_response(
            data=result["school_unit"],
            message="School unit updated successfully",
        )
    if result.get("error") == "School unit not found":
        return not_found_response("School unit")
    return error_response("UpdateError", result["error"], 400)


@school_units_bp.route("/<unit_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def delete_school_unit(unit_id):
    result = services.delete_school_unit(unit_id, g.tenant_id)
    if result["success"]:
        return success_response(message="School unit deleted successfully")
    if result.get("error") == "School unit not found":
        return not_found_response("School unit")
    return error_response("DeleteError", result["error"], 400)
