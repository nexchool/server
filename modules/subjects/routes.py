"""
Subject Routes

REST API for subject CRUD. All routes require tenant context and RBAC permissions.
"""

from flask import request, g

from modules.subjects import subjects_bp
from core.decorators import (
    require_permission,
    require_any_permission,
    auth_required,
    tenant_required,
    require_feature,
)
from shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
)
from . import services

# Permissions — subject.manage implies create/update/delete per RBAC hierarchy
PERM_READ = "subject.read"
PERM_MANAGE = "subject.manage"


@subjects_bp.route("/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def list_subjects():
    """The subjects a school teaches, as a flat array.

    ⚠️ **Kept for the Expo client only** (`client/modules/subjects/services/
    subjectService.ts`). admin-web reads `subjects` and `subjectCatalogue` on
    GraphQL; the administrator's paginated catalogue that used to live behind
    this URL's query params is gone. Both transports call
    `list_subjects_filtered`, so there is one reader.

    Delete with the Expo release that moves the mobile app.
    """
    include_inactive = request.args.get("include_inactive", "false").lower() == "true"
    subjects = services.list_subjects_filtered(
        g.tenant_id, include_inactive=include_inactive
    )
    return success_response(data=subjects)


@subjects_bp.route("/mine", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission("academics.read")
def list_my_subjects():
    """List subjects scoped to the current user's role (admin/teacher/student)."""
    subjects = services.get_subjects_for_user(g.tenant_id, g.current_user)
    return success_response(data=subjects)


@subjects_bp.route("/", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def create_subject():
    """Create a new subject.

    Body: name (required), code, description, subject_type, is_active,
    class_ids[] (optional — atomically assign to these classes),
    weekly_periods (used with class_ids, default 1).

    class_ids additionally requires class_subject.manage — creating the
    ClassSubject rows here is the same action as POST /class-subjects/
    bulk-assign, so it must clear the same permission gate.
    """
    data = request.get_json() or {}
    if not data.get("name"):
        return validation_error_response("name is required")

    if data.get("class_ids"):
        from modules.rbac.services import has_permission

        if not has_permission(g.current_user.id, "class_subject.manage"):
            return error_response(
                "AuthorizationError",
                "class_subject.manage permission is required to assign classes",
                403,
            )

    tenant_id = g.tenant_id
    result = services.create_subject(data, tenant_id)

    if result["success"]:
        return success_response(
            data=result["subject"],
            message="Subject created successfully",
            status_code=201,
        )
    return error_response("CreationError", result["error"], 400)


@subjects_bp.route("/<subject_id>", methods=["GET"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_subject(subject_id):
    """Get subject by ID."""
    tenant_id = g.tenant_id
    subject = services.get_subject_by_id(subject_id, tenant_id)
    if not subject:
        return not_found_response("Subject")
    return success_response(data=subject)


@subjects_bp.route("/<subject_id>", methods=["PATCH", "PUT"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def update_subject(subject_id):
    """Update a subject (PATCH preferred; PUT kept for compatibility)."""
    data = request.get_json() or {}
    tenant_id = g.tenant_id
    result = services.update_subject(subject_id, data, tenant_id)

    if result["success"]:
        return success_response(
            data=result["subject"],
            message="Subject updated successfully",
        )
    if result.get("error") == "Subject not found":
        return not_found_response("Subject")
    return error_response("UpdateError", result["error"], 400)


@subjects_bp.route("/<subject_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def delete_subject(subject_id):
    """Delete a subject."""
    tenant_id = g.tenant_id
    result = services.delete_subject(subject_id, tenant_id)

    if result["success"]:
        return success_response(message="Subject deleted successfully")
    if result.get("error") == "Subject not found":
        return not_found_response("Subject")
    return error_response("DeleteError", result["error"], 400)
