"""
Bulk student import API (Excel preview + import).
"""

from flask import g, request

from core.decorators import (
    auth_required,
    require_permission,
    tenant_required,
    require_plan_feature,
)
from modules.students import students_bp
from modules.students.bulk_student_import_service import run_import, run_preview
from shared.helpers import error_response, success_response, validation_error_response

PERM_CREATE = "student.create"


def _read_xlsx_bytes():
    """Returns (bytes, None) or (None, error_response)."""
    f = request.files.get("file")
    if not f or not getattr(f, "filename", ""):
        return None, validation_error_response("file is required (xlsx)")
    name = (f.filename or "").lower()
    if not name.endswith(".xlsx"):
        return None, validation_error_response("Only .xlsx files are accepted")
    data = f.read()
    if not data:
        return None, validation_error_response("File is empty")
    return data, None


@students_bp.route(
    "/bulk-import/preview",
    methods=["POST", "OPTIONS"],
    strict_slashes=False,
)
@tenant_required
@auth_required
@require_plan_feature("student_management")
@require_permission(PERM_CREATE)
def bulk_import_preview():
    """Validate Excel only; no inserts."""
    raw = request.form.get("academic_year_id") or request.args.get("academic_year_id")
    if not raw:
        return validation_error_response("academic_year_id is required")

    data, err = _read_xlsx_bytes()
    if err:
        return err

    try:
        result = run_preview(data, raw.strip())
        return success_response(data=result)
    except ValueError as e:
        return validation_error_response(str(e))
    except Exception as e:
        return error_response("BulkImportError", str(e), 400)


@students_bp.route(
    "/bulk-import",
    methods=["POST", "OPTIONS"],
    strict_slashes=False,
)
@tenant_required
@auth_required
@require_plan_feature("student_management")
@require_permission(PERM_CREATE)
def bulk_import_execute():
    """Import validated rows from Excel."""
    academic_year_id = request.form.get("academic_year_id") or request.args.get(
        "academic_year_id"
    )
    if not academic_year_id:
        return validation_error_response("academic_year_id is required")

    send_email_raw = request.form.get("send_email", "true")
    if isinstance(send_email_raw, str):
        send_email = send_email_raw.lower() in ("1", "true", "yes", "on")
    else:
        send_email = bool(send_email_raw)

    data, err = _read_xlsx_bytes()
    if err:
        return err

    try:
        result = run_import(data, academic_year_id.strip(), send_email)
        err = result.get("error")
        if err:
            if "limit" in (err or "").lower():
                return error_response(
                    "Forbidden",
                    err,
                    403,
                    details=result,
                )
            return error_response("BulkImportError", err, 400, details=result)
        return success_response(data=result, message="Bulk import completed")
    except ValueError as e:
        return validation_error_response(str(e))
    except Exception as e:
        return error_response("BulkImportError", str(e), 400)
