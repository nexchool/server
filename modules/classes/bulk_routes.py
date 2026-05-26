"""
Bulk class creation route — structured (UI-driven) input, NOT Excel.

  POST /api/classes/bulk-create
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

from . import classes_bp
from .bulk_services import bulk_create_classes


PERM_CLASS_CREATE = "class.create"


@classes_bp.route("/bulk-create", methods=["POST"])
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_CLASS_CREATE)
def bulk_create():
    """
    Structured bulk class creation.

    Body:
        {
          "school_unit_id": "...",
          "programme_id":   "...",
          "academic_year_id": "...",
          "structure": [
            {"grade_id": "...", "sections": ["A", "B", "C"]},
            ...
          ]
        }
    """
    payload = request.get_json() or {}
    if not isinstance(payload, dict):
        return validation_error_response({"message": "request body must be a JSON object"})

    result = bulk_create_classes(payload, g.tenant_id)
    if result["success"]:
        body = {
            "created": result["created"],
            "skipped": result["skipped"],
            "created_count": result["created_count"],
            "skipped_count": result["skipped_count"],
        }
        return success_response(
            data=body,
            message=f"Created {result['created_count']} class(es); skipped {result['skipped_count']}.",
            status_code=201,
        )
    return error_response("BulkCreateError", result["error"], 400)
