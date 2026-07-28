"""Department Routes

REST API for the per-tenant department catalogue. Every route requires tenant
context and an RBAC permission.
"""

from flask import g, request

from core.decorators import auth_required, require_permission, tenant_required
from modules.departments import departments_bp
from shared.helpers import error_response, not_found_response, success_response

from . import services

# Permissions — department.manage implies create/update/delete per RBAC hierarchy
PERM_READ = "department.read"
PERM_MANAGE = "department.manage"

_LIST_PARAMS = ("page", "per_page", "search", "status", "sort_by", "sort_dir")


def _is_duplicate_error(error: str) -> bool:
    """True for the duplicate-name/code messages services.py returns.

    Every conflict message create_department/update_department can return
    (own name check, own code check, or the IntegrityError race handler)
    contains this phrase; no validation-failure message does. Keying off it
    distinguishes 409 from 400 without adding an error-code field to
    services.py's return contract, which Tasks 5-7 already depend on.
    """
    return "already exists" in error


@departments_bp.route("/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission(PERM_READ)
def list_departments():
    """List departments for the current tenant (paginated envelope)."""
    params = {key: request.args.get(key) for key in _LIST_PARAMS}
    return success_response(data=services.list_departments(params, g.tenant_id))


@departments_bp.route("/stats", methods=["GET"])
@tenant_required
@auth_required
@require_permission(PERM_READ)
def department_stats():
    """Return the four dashboard card values."""
    return success_response(data=services.get_department_stats(g.tenant_id))


@departments_bp.route("/<department_id>", methods=["GET"])
@tenant_required
@auth_required
@require_permission(PERM_READ)
def get_department(department_id):
    """Get a single department by id."""
    department = services.get_department(department_id, g.tenant_id)
    if not department:
        return not_found_response("Department")
    return success_response(data=department)


@departments_bp.route("/", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission(PERM_MANAGE)
def create_department():
    """Create a department. Body: name (required), code, description,
    display_order, status."""
    result = services.create_department(
        request.get_json(silent=True) or {},
        g.tenant_id,
        user_id=g.current_user.id,
    )
    if not result["success"]:
        status = 409 if _is_duplicate_error(result["error"]) else 400
        return error_response("ValidationError", result["error"], status_code=status)
    return success_response(data=result["department"], status_code=201)


@departments_bp.route("/<department_id>", methods=["PATCH"])
@tenant_required
@auth_required
@require_permission(PERM_MANAGE)
def update_department(department_id):
    """Partially update a department."""
    result = services.update_department(
        department_id,
        request.get_json(silent=True) or {},
        g.tenant_id,
        user_id=g.current_user.id,
    )
    if not result["success"]:
        if result["error"] == "Department not found":
            return not_found_response("Department")
        status = 409 if _is_duplicate_error(result["error"]) else 400
        return error_response("ValidationError", result["error"], status_code=status)
    return success_response(data=result["department"])


@departments_bp.route("/<department_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_permission(PERM_MANAGE)
def delete_department(department_id):
    """Soft-delete a department. Refused (409) while teachers/classes reference it."""
    result = services.delete_department(department_id, g.tenant_id)
    if not result["success"]:
        if result["error"] == "Department not found":
            return not_found_response("Department")
        return error_response(
            "DEPARTMENT_IN_USE",
            result["error"],
            status_code=409,
            details=result.get("in_use"),
        )
    return "", 204
