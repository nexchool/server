"""
Sub-Admins routes (thin HTTP layer).

All routes are tenant-scoped and gated on ``subadmin.manage``. Business logic
and validation live in services; routes only parse input, call the service, and
map the result dict to the standard response envelope.
"""

from flask import g, request

from core.decorators import auth_required, require_permission, tenant_required
from core.tenant import get_tenant_id
from shared.helpers import error_response, success_response

from . import sub_admins_bp
from .catalog import get_catalog
from .services import (
    create_sub_admin,
    delete_sub_admin,
    get_sub_admin,
    list_sub_admins,
    reset_sub_admin_password,
    restore_sub_admin,
    suspend_sub_admin,
    update_sub_admin,
)

_PERMISSION = "subadmin.manage"


def _fail(result):
    """Map a service error dict to the standard error response."""
    return error_response(
        result.get("code", "Error"),
        result.get("error", "Request failed"),
        result.get("status_code", 400),
    )


@sub_admins_bp.route("", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission(_PERMISSION)
def list_sub_admins_route():
    """List sub-admins for the current tenant (paginated)."""
    result = list_sub_admins(
        tenant_id=get_tenant_id(),
        search=request.args.get("search"),
        status=request.args.get("status"),
        page=request.args.get("page", 1, type=int),
        per_page=request.args.get("per_page", 20, type=int),
    )
    return success_response(
        {
            "sub_admins": result["items"],
            "pagination": {
                "page": result["page"],
                "per_page": result["per_page"],
                "total": result["total"],
                "total_pages": result["total_pages"],
                "has_prev": result["has_prev"],
                "has_next": result["has_next"],
            },
        }
    )


@sub_admins_bp.route("/modules", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission(_PERMISSION)
def list_modules_route():
    """Return the SUBADMIN_MODULES catalog for the UI form."""
    return success_response({"modules": get_catalog()})


@sub_admins_bp.route("", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission(_PERMISSION)
def create_sub_admin_route():
    """Create a sub-admin with the selected module permissions."""
    data = request.get_json() or {}
    result = create_sub_admin(
        tenant_id=get_tenant_id(),
        tenant_name=getattr(getattr(g, "tenant", None), "name", "") or "",
        name=data.get("name"),
        email=data.get("email"),
        password=data.get("password"),
        modules=data.get("modules") or [],
    )
    if not result["success"]:
        return _fail(result)
    return success_response(
        result["sub_admin"], "Sub-admin created successfully", 201
    )


@sub_admins_bp.route("/<user_id>", methods=["GET"])
@tenant_required
@auth_required
@require_permission(_PERMISSION)
def get_sub_admin_route(user_id):
    """Get a sub-admin's detail (granted modules + status)."""
    result = get_sub_admin(get_tenant_id(), user_id)
    if not result["success"]:
        return _fail(result)
    return success_response(result["sub_admin"])


@sub_admins_bp.route("/<user_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_permission(_PERMISSION)
def update_sub_admin_route(user_id):
    """Edit a sub-admin's name and/or module permissions."""
    data = request.get_json() or {}
    result = update_sub_admin(
        tenant_id=get_tenant_id(),
        user_id=user_id,
        name=data.get("name"),
        modules=data.get("modules"),
    )
    if not result["success"]:
        return _fail(result)
    return success_response(result["sub_admin"], "Sub-admin updated successfully")


@sub_admins_bp.route("/<user_id>/suspend", methods=["POST"])
@tenant_required
@auth_required
@require_permission(_PERMISSION)
def suspend_sub_admin_route(user_id):
    """Suspend a sub-admin and revoke its sessions."""
    result = suspend_sub_admin(get_tenant_id(), user_id, g.current_user.id)
    if not result["success"]:
        return _fail(result)
    return success_response(message=result["message"])


@sub_admins_bp.route("/<user_id>/restore", methods=["POST"])
@tenant_required
@auth_required
@require_permission(_PERMISSION)
def restore_sub_admin_route(user_id):
    """Restore a suspended sub-admin."""
    result = restore_sub_admin(get_tenant_id(), user_id)
    if not result["success"]:
        return _fail(result)
    return success_response(message=result["message"])


@sub_admins_bp.route("/<user_id>/reset-password", methods=["POST"])
@tenant_required
@auth_required
@require_permission(_PERMISSION)
def reset_sub_admin_password_route(user_id):
    """Set a new admin-typed password for a sub-admin."""
    data = request.get_json() or {}
    result = reset_sub_admin_password(
        tenant_id=get_tenant_id(),
        tenant_name=getattr(getattr(g, "tenant", None), "name", "") or "",
        user_id=user_id,
        actor_id=g.current_user.id,
        password=data.get("password"),
    )
    if not result["success"]:
        return _fail(result)
    return success_response(message=result["message"])


@sub_admins_bp.route("/<user_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_permission(_PERMISSION)
def delete_sub_admin_route(user_id):
    """Soft-delete a sub-admin and revoke its sessions."""
    result = delete_sub_admin(get_tenant_id(), user_id, g.current_user.id)
    if not result["success"]:
        return _fail(result)
    return success_response(message=result["message"])
