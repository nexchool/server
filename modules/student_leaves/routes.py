"""HTTP routes for /api/student-leaves/*.

Task 6 of Slice 4.5. Routes are thin wrappers around the service layer;
authorization beyond role gating happens in services.py.
"""

from __future__ import annotations

from flask import g, request

from core.decorators import auth_required, require_permission, tenant_required
from modules.student_leaves import services, student_leaves_bp
from modules.student_leaves.permissions import (
    PERM_STUDENT_LEAVE_APPLY,
    PERM_STUDENT_LEAVE_APPROVE_ALL,
    PERM_STUDENT_LEAVE_APPROVE_CLASS,
    PERM_STUDENT_LEAVE_REQUEST_CANCEL,
)
from shared.helpers import (
    error_response,
    success_response,
    validation_error_response,
)


# --- Mutations ---------------------------------------------------------------

@student_leaves_bp.route("", methods=["POST"])
@tenant_required
@auth_required
@require_permission(PERM_STUDENT_LEAVE_APPLY)
def create_leave():
    payload = request.get_json() or {}
    try:
        leave = services.create_request(payload, actor_user_id=g.current_user.id)
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    return success_response(data=leave.to_dict(), status_code=201)


@student_leaves_bp.route("/<leave_id>/approve", methods=["POST"])
@tenant_required
@auth_required
def approve_leave(leave_id):
    try:
        leave = services.approve(leave_id, actor_user_id=g.current_user.id)
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    except services.AuthorizationError as e:
        return error_response("AuthorizationError", str(e), 403)
    except services.StateError as e:
        return error_response("StateError", str(e), 409)
    return success_response(data=leave.to_dict())


@student_leaves_bp.route("/<leave_id>/reject", methods=["POST"])
@tenant_required
@auth_required
def reject_leave(leave_id):
    payload = request.get_json() or {}
    reason = (payload.get("rejection_reason") or "").strip()
    try:
        leave = services.reject(
            leave_id, actor_user_id=g.current_user.id, rejection_reason=reason
        )
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    except services.AuthorizationError as e:
        return error_response("AuthorizationError", str(e), 403)
    except services.StateError as e:
        return error_response("StateError", str(e), 409)
    return success_response(data=leave.to_dict())


@student_leaves_bp.route("/<leave_id>/request-cancel", methods=["POST"])
@tenant_required
@auth_required
@require_permission(PERM_STUDENT_LEAVE_REQUEST_CANCEL)
def request_cancel_leave(leave_id):
    payload = request.get_json() or {}
    reason = payload.get("reason", "")
    try:
        leave = services.request_cancel(
            leave_id, actor_user_id=g.current_user.id, reason=reason
        )
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    except services.AuthorizationError as e:
        return error_response("AuthorizationError", str(e), 403)
    except services.StateError as e:
        return error_response("StateError", str(e), 409)
    return success_response(data=leave.to_dict())


@student_leaves_bp.route("/<leave_id>/approve-cancel", methods=["POST"])
@tenant_required
@auth_required
def approve_cancel_leave(leave_id):
    try:
        leave = services.approve_cancel(leave_id, actor_user_id=g.current_user.id)
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    except services.AuthorizationError as e:
        return error_response("AuthorizationError", str(e), 403)
    except services.StateError as e:
        return error_response("StateError", str(e), 409)
    return success_response(data=leave.to_dict())


@student_leaves_bp.route("/<leave_id>/reject-cancel", methods=["POST"])
@tenant_required
@auth_required
def reject_cancel_leave(leave_id):
    try:
        leave = services.reject_cancel(leave_id, actor_user_id=g.current_user.id)
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    except services.AuthorizationError as e:
        return error_response("AuthorizationError", str(e), 403)
    except services.StateError as e:
        return error_response("StateError", str(e), 409)
    return success_response(data=leave.to_dict())


# --- Queries -----------------------------------------------------------------

@student_leaves_bp.route("", methods=["GET"])
@tenant_required
@auth_required
def list_leaves():
    status = request.args.get("status")
    rows = services.list_visible_for_user(g.current_user, status=status)
    return success_response(data=[r.to_dict() for r in rows])


@student_leaves_bp.route("/queue/me", methods=["GET"])
@tenant_required
@auth_required
@require_permission(PERM_STUDENT_LEAVE_APPROVE_CLASS)
def queue_for_me():
    rows = services.teacher_queue(g.current_user)
    return success_response(data=[r.to_dict() for r in rows])


@student_leaves_bp.route("/queue/admin", methods=["GET"])
@tenant_required
@auth_required
@require_permission(PERM_STUDENT_LEAVE_APPROVE_ALL)
def queue_for_admin():
    rows = services.admin_fallback_queue(g.current_user)
    return success_response(data=[r.to_dict() for r in rows])


@student_leaves_bp.route("/<leave_id>", methods=["GET"])
@tenant_required
@auth_required
def get_leave(leave_id):
    try:
        leave = services.get_for_user(leave_id, g.current_user)
    except services.AuthorizationError as e:
        return error_response("AuthorizationError", str(e), 403)
    except services.ValidationError as e:
        return validation_error_response({"detail": str(e)})
    return success_response(data=leave.to_dict())
