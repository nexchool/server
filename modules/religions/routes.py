"""
Religion Routes

REST API for the tenant-scoped religion master. Mounted at /api/religions.
"""

from flask import g, request

from core.decorators import (
    auth_required,
    tenant_required,
    require_permission,
    require_any_permission,
)
from shared.helpers import (
    error_response,
    not_found_response,
    success_response,
    validation_error_response,
)
from . import religions_bp, services


PERM_READ = "religion.read"
PERM_MANAGE = "religion.manage"


@religions_bp.route("/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_any_permission(PERM_READ, PERM_MANAGE)
def list_religions():
    return success_response(data=services.list_religions(g.tenant_id))


@religions_bp.route("/", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission(PERM_MANAGE)
def create_religion():
    data = request.get_json() or {}
    if not data.get("name"):
        return validation_error_response({"message": "name is required"})

    result = services.create_religion(data, g.tenant_id)
    if result["success"]:
        return success_response(
            data=result["religion"],
            message="Religion created successfully",
            status_code=201,
        )
    return error_response("CreationError", result["error"], 400)


@religions_bp.route("/<religion_id>", methods=["GET"])
@tenant_required
@auth_required
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_religion(religion_id):
    religion = services.get_religion(religion_id, g.tenant_id)
    if not religion:
        return not_found_response("Religion")
    return success_response(data=religion)


@religions_bp.route("/<religion_id>", methods=["PATCH", "PUT"])
@tenant_required
@auth_required
@require_permission(PERM_MANAGE)
def update_religion(religion_id):
    data = request.get_json() or {}
    result = services.update_religion(religion_id, data, g.tenant_id)
    if result["success"]:
        return success_response(
            data=result["religion"],
            message="Religion updated successfully",
        )
    if result.get("error") == "Religion not found":
        return not_found_response("Religion")
    return error_response("UpdateError", result["error"], 400)


@religions_bp.route("/<religion_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_permission(PERM_MANAGE)
def delete_religion(religion_id):
    result = services.delete_religion(religion_id, g.tenant_id)
    if result["success"]:
        return success_response(message="Religion deleted successfully")
    if result.get("error") == "Religion not found":
        return not_found_response("Religion")
    return error_response("DeleteError", result["error"], 400)
