"""
Class-Subjects Routes

Mounted at /api/class-subjects. Currently exposes structured bulk
assignment of subjects to classes. The underlying logic lives in
modules.classes.bulk_services so all class-shaped logic stays
co-located.
"""

from flask import g, request

from core.decorators import (
    auth_required,
    tenant_required,
    require_feature,
    require_permission,
)
from shared.helpers import (
    error_response,
    success_response,
    validation_error_response,
)

from modules.classes.bulk_services import bulk_assign_class_subjects

from . import class_subjects_bp


PERM_CS_MANAGE = "class_subject.manage"


@class_subjects_bp.route("/bulk-assign", methods=["POST"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_CS_MANAGE)
def bulk_assign_subjects():
    """
    Bulk assign subjects to classes.

    Body:
        {
          "class_ids":   ["..."],
          "subject_ids": ["..."],
          "weekly_periods": 1
        }
    """
    payload = request.get_json() or {}
    if not isinstance(payload, dict):
        return validation_error_response({"message": "request body must be a JSON object"})

    result = bulk_assign_class_subjects(payload, g.tenant_id)
    if result["success"]:
        body = {
            "created": result["created"],
            "skipped": result["skipped"],
            "created_count": result["created_count"],
            "skipped_count": result["skipped_count"],
        }
        return success_response(
            data=body,
            message=(
                f"Assigned {result['created_count']} subject offering(s); "
                f"skipped {result['skipped_count']}."
            ),
            status_code=201,
        )
    return error_response("BulkAssignError", result["error"], 400)
