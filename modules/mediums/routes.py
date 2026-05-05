"""REST API for mediums — /api/mediums."""

from flask import g, request

from core.decorators import (
    auth_required,
    tenant_required,
    require_feature,
    require_any_permission,
)
from shared.helpers import (
    error_response,
    not_found_response,
    success_response,
    validation_error_response,
)

from . import mediums_bp, services


PERM_READ = "school_setup.read"
PERM_MANAGE = "school_setup.manage"
PERM_CS = "class_subject.manage"


def _actor_id():
    user = getattr(g, "current_user", None)
    return getattr(user, "id", None) if user is not None else None


@mediums_bp.route("/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE, PERM_CS)
def list_mediums():
    include_inactive = request.args.get("include_inactive", "").lower() in (
        "1",
        "true",
        "yes",
    )
    return success_response(
        data=services.list_mediums(g.tenant_id, include_inactive=include_inactive)
    )


@mediums_bp.route("/", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_MANAGE, PERM_CS)
def create_medium():
    data = request.get_json() or {}
    if not (data.get("name") or "").strip():
        return validation_error_response({"message": "name is required"})
    result = services.create_medium(g.tenant_id, data, actor_user_id=_actor_id())
    if result["success"]:
        return success_response(
            data=result["medium"], message="Medium created", status_code=201
        )
    return error_response("MediumError", result["error"], 400)


@mediums_bp.route("/<medium_id>", methods=["PATCH"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_MANAGE, PERM_CS)
def update_medium(medium_id):
    data = request.get_json() or {}
    result = services.update_medium(
        medium_id, g.tenant_id, data, actor_user_id=_actor_id()
    )
    if result["success"]:
        return success_response(data=result["medium"], message="Medium updated")
    if result.get("error") == "Medium not found":
        return not_found_response("Medium")
    return error_response("MediumError", result["error"], 400)


@mediums_bp.route("/<medium_id>", methods=["DELETE"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_MANAGE, PERM_CS)
def delete_medium(medium_id):
    result = services.delete_medium(medium_id, g.tenant_id)
    if result["success"]:
        return success_response(data={}, message="Medium deleted")
    if result.get("error") == "Medium not found":
        return not_found_response("Medium")
    return error_response("MediumError", result["error"], 400)
