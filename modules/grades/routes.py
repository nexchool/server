"""
Grade Routes

REST API for the grade master list. Mounted at /api/grades.
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
from . import grades_bp, services


PERM_READ = "grade.read"
PERM_MANAGE = "grade.manage"


@grades_bp.route("/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def list_grades():
    return success_response(data=services.list_grades(g.tenant_id))


@grades_bp.route("/", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def create_grade():
    data = request.get_json() or {}
    if not data.get("name"):
        return validation_error_response({"message": "name is required"})

    result = services.create_grade(data, g.tenant_id)
    if result["success"]:
        return success_response(
            data=result["grade"],
            message="Grade created successfully",
            status_code=201,
        )
    return error_response("CreationError", result["error"], 400)


@grades_bp.route("/<grade_id>", methods=["GET"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_grade(grade_id):
    grade = services.get_grade(grade_id, g.tenant_id)
    if not grade:
        return not_found_response("Grade")
    return success_response(data=grade)


@grades_bp.route("/<grade_id>", methods=["PATCH", "PUT"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def update_grade(grade_id):
    data = request.get_json() or {}
    result = services.update_grade(grade_id, data, g.tenant_id)
    if result["success"]:
        return success_response(
            data=result["grade"],
            message="Grade updated successfully",
        )
    if result.get("error") == "Grade not found":
        return not_found_response("Grade")
    return error_response("UpdateError", result["error"], 400)


@grades_bp.route("/<grade_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def delete_grade(grade_id):
    result = services.delete_grade(grade_id, g.tenant_id)
    if result["success"]:
        return success_response(message="Grade deleted successfully")
    if result.get("error") == "Grade not found":
        return not_found_response("Grade")
    return error_response("DeleteError", result["error"], 400)
