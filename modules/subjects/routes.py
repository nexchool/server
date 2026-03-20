"""
Subject Routes

REST API for subject CRUD. All routes require tenant context and RBAC permissions.
"""

from flask import request, g

from backend.modules.subjects import subjects_bp
from backend.core.decorators import (
    require_permission,
    auth_required,
    tenant_required,
    require_plan_feature,
)
from backend.shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
)
from . import services

# Permissions
PERM_READ = "subject.read"
PERM_CREATE = "subject.create"
PERM_UPDATE = "subject.update"
PERM_DELETE = "subject.delete"


@subjects_bp.route("/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_permission(PERM_READ)
def list_subjects():
    """List all subjects for the current tenant."""
    tenant_id = g.tenant_id
    subjects = services.get_subjects(tenant_id)
    return success_response(data=subjects)


@subjects_bp.route("/", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_permission(PERM_CREATE)
def create_subject():
    """Create a new subject."""
    data = request.get_json() or {}
    if not data.get("name"):
        return validation_error_response("name is required")

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
@require_plan_feature("class_management")
@require_permission(PERM_READ)
def get_subject(subject_id):
    """Get subject by ID."""
    tenant_id = g.tenant_id
    subject = services.get_subject_by_id(subject_id, tenant_id)
    if not subject:
        return not_found_response("Subject")
    return success_response(data=subject)


@subjects_bp.route("/<subject_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_permission(PERM_UPDATE)
def update_subject(subject_id):
    """Update a subject."""
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
@require_plan_feature("class_management")
@require_permission(PERM_DELETE)
def delete_subject(subject_id):
    """Delete a subject."""
    tenant_id = g.tenant_id
    result = services.delete_subject(subject_id, tenant_id)

    if result["success"]:
        return success_response(message="Subject deleted successfully")
    if result.get("error") == "Subject not found":
        return not_found_response("Subject")
    return error_response("DeleteError", result["error"], 400)
