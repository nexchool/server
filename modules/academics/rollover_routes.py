"""Academic rollover endpoints — structure / timetable / holidays / teacher gaps."""

from flask import g, request

from core.decorators import auth_required, require_feature, require_permission, tenant_required
from core.tenant import get_tenant_id
from modules.academics import academics_bp
from modules.academics.services import (
    academic_structure_rollover,
    holiday_rollover,
    teacher_gaps,
    timetable_rollover,
)
from shared.helpers import error_response, success_response, validation_error_response

PERM_MANAGE = "academics.manage"


@academics_bp.route("/rollover/copy-structure", methods=["POST"])
@tenant_required
@auth_required
@require_feature("academics_advanced")
@require_permission(PERM_MANAGE)
def copy_academic_structure():
    data = request.get_json(silent=True) or {}
    class_mapping = data.get("class_mapping")
    if not isinstance(class_mapping, dict):
        return validation_error_response("class_mapping must be an object")

    result = academic_structure_rollover.rollover_academic_structure(
        class_mapping,
        user_id=g.current_user.id if getattr(g, "current_user", None) else None,
    )
    if not result.get("success"):
        return error_response("Error", result.get("error", "Rollover failed"), 400)

    return success_response(
        data={
            "class_subjects_created": result["class_subjects_created"],
            "subject_teachers_created": result["subject_teachers_created"],
            "class_teachers_created": result["class_teachers_created"],
            "skipped": result["skipped"],
        }
    )


@academics_bp.route("/rollover/copy-timetable", methods=["POST"])
@tenant_required
@auth_required
@require_feature("academics_advanced")
@require_permission(PERM_MANAGE)
def copy_timetable():
    data = request.get_json(silent=True) or {}
    class_mapping = data.get("class_mapping")
    if not isinstance(class_mapping, dict):
        return validation_error_response("class_mapping must be an object")

    result = timetable_rollover.rollover_timetables(
        class_mapping,
        user_id=g.current_user.id if getattr(g, "current_user", None) else None,
    )
    if not result.get("success"):
        return error_response("Error", result.get("error", "Rollover failed"), 400)

    return success_response(
        data={
            "versions_created": result["versions_created"],
            "entries_created": result["entries_created"],
            "skipped": result["skipped"],
        }
    )


@academics_bp.route("/rollover/copy-holidays", methods=["POST"])
@tenant_required
@auth_required
@require_feature("academics_advanced")
@require_permission(PERM_MANAGE)
def copy_holidays():
    data = request.get_json(silent=True) or {}
    from_year_id = (data.get("from_year_id") or "").strip()
    to_year_id = (data.get("to_year_id") or "").strip()
    if not from_year_id or not to_year_id:
        return validation_error_response("from_year_id and to_year_id are required")
    if from_year_id == to_year_id:
        return validation_error_response("from_year_id and to_year_id must differ")

    result = holiday_rollover.rollover_holidays(from_year_id, to_year_id)
    if not result.get("success"):
        return error_response("Error", result.get("error", "Rollover failed"), 400)
    return success_response(
        data={
            "holidays_created": result["holidays_created"],
            "skipped_existing": result["skipped_existing"],
        }
    )


@academics_bp.route("/rollover/teacher-gaps", methods=["GET"])
@tenant_required
@auth_required
@require_feature("academics_advanced")
@require_permission(PERM_MANAGE)
def get_teacher_gaps():
    academic_year_id = (request.args.get("academic_year_id") or "").strip()
    if not academic_year_id:
        return validation_error_response("academic_year_id is required")
    tenant_id = get_tenant_id()
    result = teacher_gaps.summarize_teacher_gaps(tenant_id, academic_year_id)
    if not result.get("success"):
        return error_response("Error", result.get("error", "Failed"), 400)
    return success_response(data=result["data"])
