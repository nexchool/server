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
from .template_models import SubjectTemplateGroup, SubjectTemplateItem
from . import apply_subjects_service
from . import seed_service


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


@school_setup_bp.route("/import/template", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission(PERM_MANAGE)
def download_import_template():
    """Return a pre-formatted xlsx skeleton with the import column headers."""
    from io import BytesIO
    from openpyxl import Workbook
    from flask import send_file

    wb = Workbook()
    ws = wb.active
    ws.title = "Classes"
    ws.append(["unit_code", "programme_code", "grade", "section", "subject", "periods"])
    # one example row to clarify format
    ws.append(["MN", "CBSE-ENG", "Grade 1", "A", "", ""])
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return send_file(
        bio,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="class-import-template.xlsx",
    )


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


@school_setup_bp.route("/templates/", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission(PERM_MANAGE)
def list_templates():
    """List active SubjectTemplateGroup rows (board templates)."""
    groups = (
        SubjectTemplateGroup.query
        .filter_by(is_active=True)
        .order_by(SubjectTemplateGroup.name)
        .all()
    )
    return success_response(data=[g.to_dict() for g in groups])


@school_setup_bp.route(
    "/templates/<group_id>/items/", methods=["GET"], strict_slashes=False
)
@tenant_required
@auth_required
@require_permission(PERM_MANAGE)
def list_template_items(group_id):
    """List SubjectTemplateItem rows for a given template group."""
    group = SubjectTemplateGroup.query.get(group_id)
    if not group:
        return error_response("NotFound", "Template not found", 404)
    items = (
        SubjectTemplateItem.query
        .filter_by(template_group_id=group_id)
        .order_by(SubjectTemplateItem.grade_number, SubjectTemplateItem.sort_order)
        .all()
    )
    return success_response(data=[i.to_dict() for i in items])


@school_setup_bp.route(
    "/apply-subject-offerings", methods=["POST"], strict_slashes=False
)
@tenant_required
@auth_required
@require_permission(PERM_MANAGE)
def apply_subject_offerings_route():
    """Seed class_subjects for every active Subject × Class in the given academic year."""
    payload = request.get_json(silent=True) or {}
    academic_year_id = payload.get("academic_year_id")
    if not academic_year_id:
        return error_response("ValidationError", "academic_year_id required", 400)
    result = apply_subjects_service.apply_subject_offerings(
        tenant_id=g.tenant_id, academic_year_id=academic_year_id
    )
    return success_response(data=result)


def _active_subdomain(tenant_id):
    """Subdomain of the tenant the request operates in (config-vs-tenant guard)."""
    from core.models import Tenant

    t = Tenant.query.filter_by(id=tenant_id).first()
    return t.subdomain if t else None


@school_setup_bp.route("/seed/preview", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_permission(PERM_MANAGE)
def post_seed_preview():
    """Parse an uploaded .yaml/.json onboarding config; return a read-only diff (no writes)."""
    file = request.files.get("file")
    if file is None:
        return error_response(
            "ValidationError", "file is required (multipart field 'file')", 400
        )
    try:
        config = seed_service.parse_config_bytes(file.filename or "", file.read())
    except seed_service.UnsupportedConfigType as e:
        return error_response("UnsupportedFileType", str(e), 400)
    except Exception:
        return error_response(
            "ParseError", "Could not parse the file. Ensure it is valid YAML or JSON.", 400
        )
    preview = seed_service.preview_seed(
        g.tenant_id, config, active_subdomain=_active_subdomain(g.tenant_id)
    )
    return success_response(data=preview)


@school_setup_bp.route("/seed/apply", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("class_management")
@require_permission(PERM_MANAGE)
def post_seed_apply():
    """Apply an uploaded .yaml/.json onboarding config to the active tenant (real seed)."""
    file = request.files.get("file")
    if file is None:
        return error_response(
            "ValidationError", "file is required (multipart field 'file')", 400
        )
    try:
        config = seed_service.parse_config_bytes(file.filename or "", file.read())
    except seed_service.UnsupportedConfigType as e:
        return error_response("UnsupportedFileType", str(e), 400)
    except Exception:
        return error_response(
            "ParseError", "Could not parse the file. Ensure it is valid YAML or JSON.", 400
        )

    # The upload always applies to the tenant the operator is in (g.tenant_id).
    # config.tenant.subdomain is advisory only — the preview surfaces a mismatch
    # so a wrong file is caught before Confirm & apply, but a template config
    # (e.g. example.yaml) still applies cleanly to the current school.
    try:
        result = seed_service.seed_school(
            g.tenant_id, config, dry_run=False, complete=True
        )
    except seed_service.SeedValidationError as e:
        from flask import jsonify

        return (
            jsonify(
                {
                    "success": False,
                    "error": "ValidationError",
                    "message": "Config validation failed.",
                    "details": {"errors": e.errors},
                }
            ),
            400,
        )

    return success_response(
        data=result,
        message=(
            f"Seeded {result['classes']['created']} class(es) and "
            f"{result['class_subjects']['created']} subject link(s). "
            f"Setup complete: {result['setup_complete']}."
        ),
        status_code=201,
    )
