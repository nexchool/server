"""
Subject Load Routes

Endpoints for managing subject weekly period loads per class:
  GET    /api/classes/<class_id>/subject-load
  POST   /api/classes/<class_id>/subject-load
  PUT    /api/classes/<class_id>/subject-load/<id>
  DELETE /api/classes/<class_id>/subject-load/<id>
"""

from flask import request
from backend.modules.classes import classes_bp
from backend.core.decorators import require_permission, auth_required, tenant_required, require_plan_feature
from backend.shared.helpers import (
    success_response,
    error_response,
    validation_error_response,
)
from . import subject_load_services as svc

PERM_MANAGE = "class.manage"


@classes_bp.route("/<class_id>/subject-load", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def list_subject_load(class_id):
    """List all subject load entries for a class."""
    items = svc.get_subject_loads(class_id)
    return success_response(data=items)


@classes_bp.route("/<class_id>/subject-load", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def create_subject_load(class_id):
    """Create a subject load entry for a class."""
    data = request.get_json() or {}
    subject_id = data.get("subject_id")
    weekly_periods = data.get("weekly_periods")

    if not subject_id or weekly_periods is None:
        return validation_error_response("subject_id and weekly_periods are required")

    result = svc.create_subject_load(class_id, subject_id, int(weekly_periods))
    if result["success"]:
        return success_response(data=result["subject_load"], message="Subject load created", status_code=201)
    return error_response("CreateError", result["error"], 400)


@classes_bp.route("/<class_id>/subject-load/<load_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def update_subject_load(class_id, load_id):
    """Update weekly_periods for a subject load entry."""
    data = request.get_json() or {}
    weekly_periods = data.get("weekly_periods")

    if weekly_periods is None:
        return validation_error_response("weekly_periods is required")

    result = svc.update_subject_load(load_id, int(weekly_periods))
    if result["success"]:
        return success_response(data=result["subject_load"], message="Subject load updated")
    return error_response("UpdateError", result["error"], 400)


@classes_bp.route("/<class_id>/subject-load/<load_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def delete_subject_load(class_id, load_id):
    """Delete a subject load entry."""
    result = svc.delete_subject_load(load_id)
    if result["success"]:
        return success_response(message="Subject load deleted")
    return error_response("DeleteError", result["error"], 400)
