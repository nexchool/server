"""
School Setup Routes

  GET  /api/school-setup/status              — per-module readiness
  POST /api/school-setup/complete            — mark tenant.is_setup_complete
  POST /api/school-setup/duplicate-structure — clone unit→unit / programme→programme
  POST /api/school-setup/promote-year        — clone classes into target year
  POST /api/school-setup/import              — Excel (.xlsx) bulk import
  POST /api/school-setup/import/parse-headers — return column headers from uploaded .xlsx
"""

import json

from flask import g, request

from core.decorators import (
    auth_required,
    tenant_required,
    require_feature,
    require_any_permission,
    require_permission,
)
from shared.helpers import error_response, success_response

from . import school_setup_bp
from .bulk_generator_service import bulk_generate_classes
from .duplicate_service import duplicate_structure
from . import import_service
from .promote_service import promote_year
from .services import (
    get_status_payload,
    run_complete_setup,
)


PERM_READ = "school_setup.read"
PERM_MANAGE = "school_setup.manage"


@school_setup_bp.route("/status", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_setup_status():
    """Per-module readiness payload for the dashboard."""
    return success_response(data=get_status_payload(g.tenant_id))


@school_setup_bp.route("/complete", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def complete_setup():
    """Mark the tenant's setup wizard as complete (atomic, race-safe)."""
    actor_user_id = getattr(getattr(g, "current_user", None), "id", None)
    result = run_complete_setup(g.tenant_id, actor_user_id=actor_user_id)
    if result["success"]:
        return success_response(
            data={"is_setup_complete": True},
            message="School setup marked complete.",
        )
    if result.get("code") == "NotFound":
        return error_response("NotFound", result["error"], 404)
    if result.get("code") == "ValidationError":
        from flask import jsonify
        return (
            jsonify(
                {
                    "success": False,
                    "error": "ValidationError",
                    "message": result["error"],
                    "details": result.get("details", {}),
                }
            ),
            400,
        )
    return error_response("UpdateError", result.get("error", "complete failed"), 400)


@school_setup_bp.route("/duplicate-structure", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def post_duplicate_structure():
    payload = request.get_json() or {}
    if not isinstance(payload, dict):
        return error_response("ValidationError", "request body must be a JSON object", 400)
    result = duplicate_structure(g.tenant_id, payload)
    if result.get("success"):
        return success_response(
            data={
                "created": result.get("created", []),
                "skipped": result.get("skipped", []),
                "created_count": result.get("created_count", 0),
                "skipped_count": result.get("skipped_count", 0),
            },
            message=result.get("message")
            or f"Duplicated {result.get('created_count', 0)}; skipped {result.get('skipped_count', 0)}.",
            status_code=201,
        )
    return error_response("DuplicateStructureError", result.get("error", "duplicate failed"), 400)


@school_setup_bp.route("/bulk-generate", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def post_bulk_generate():
    """Generate classes from a Unit × Programme × Grade × Sections matrix."""
    payload = request.get_json() or {}
    if not isinstance(payload, dict):
        return error_response("ValidationError", "request body must be a JSON object", 400)
    result = bulk_generate_classes(g.tenant_id, payload)
    if result.get("success"):
        return success_response(
            data={
                "created": result.get("created", []),
                "skipped": result.get("skipped", []),
                "errors": result.get("errors", []),
                "created_count": result.get("created_count", 0),
                "skipped_count": result.get("skipped_count", 0),
            },
            message=f"Generated {result.get('created_count', 0)} class(es); "
                    f"{result.get('skipped_count', 0)} already existed.",
            status_code=201,
        )
    return error_response(
        "BulkGenerateError",
        result.get("error", "bulk generate failed"),
        400,
        details={"errors": result.get("errors", [])},
    )


@school_setup_bp.route("/promote-year", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def post_promote_year():
    payload = request.get_json() or {}
    if not isinstance(payload, dict):
        return error_response("ValidationError", "request body must be a JSON object", 400)
    result = promote_year(g.tenant_id, payload)
    if result.get("success"):
        return success_response(
            data={
                "classes_created": result.get("classes_created", 0),
                "classes_skipped": result.get("classes_skipped", 0),
                "subject_links_created": result.get("subject_links_created", 0),
            },
            message=result.get("message")
            or f"Promoted {result.get('classes_created', 0)} class(es).",
            status_code=201,
        )
    return error_response("PromoteYearError", result.get("error", "promote failed"), 400)


@school_setup_bp.route("/import/parse-headers", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission(PERM_MANAGE)
def parse_import_headers():
    """Return the column headers from an uploaded .xlsx file."""
    file = request.files.get("file")
    if not file:
        return error_response("ValidationError", "No file uploaded", 400)
    try:
        headers = import_service.parse_headers(file.stream, file.filename or "")
    except import_service.UnsupportedFileType as e:
        return error_response("UnsupportedFileType", str(e), 400)
    return success_response(data={"headers": headers})


@school_setup_bp.route("/import", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def post_import_excel():
    file_storage = request.files.get("file")
    if file_storage is None:
        return error_response("ValidationError", "file is required (multipart/form-data field 'file')", 400)
    academic_year_id = (
        request.form.get("academic_year_id")
        or request.args.get("academic_year_id")
    )
    mapping = None
    raw_mapping = request.form.get("mapping")
    if raw_mapping:
        try:
            mapping = json.loads(raw_mapping)
        except (ValueError, TypeError):
            return error_response("ValidationError", "mapping must be a valid JSON object", 400)
    result = import_service.import_excel(
        g.tenant_id, file_storage, academic_year_id=academic_year_id, mapping=mapping
    )
    if result.get("success"):
        return success_response(
            data={
                "created": result.get("created", []),
                "skipped": result.get("skipped", []),
                "failed": result.get("failed", []),
                "created_count": result.get("created_count", 0),
                "skipped_count": result.get("skipped_count", 0),
                "failed_count": result.get("failed_count", 0),
                "subject_links_created": result.get("subject_links_created", 0),
                "subject_links_skipped": result.get("subject_links_skipped", 0),
            },
            message=(
                f"Imported {result.get('created_count', 0)} class(es); "
                f"{result.get('failed_count', 0)} row error(s)."
            ),
            status_code=201,
        )
    return error_response("ExcelImportError", result.get("error", "import failed"), 400)
