"""
Bulk teacher import API (Excel preview + import).
"""

from flask import request

from core.decorators import (
    auth_required,
    require_permission,
    tenant_required,
    require_plan_feature,
)
from modules.teachers import teachers_bp
from modules.teachers.bulk_teacher_import_service import run_import, run_preview
from shared.helpers import error_response, success_response, validation_error_response

PERM_CREATE = "teacher.create"


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


@teachers_bp.route(
    "/bulk-import/preview",
    methods=["POST", "OPTIONS"],
    strict_slashes=False,
)
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_CREATE)
def bulk_import_preview():
    """Validate Excel only; no inserts."""
    data, err = _read_xlsx_bytes()
    if err:
        return err

    try:
        result = run_preview(data)
        return success_response(data=result)
    except ValueError as e:
        return validation_error_response(str(e))
    except Exception as e:
        return error_response("BulkImportError", str(e), 400)


@teachers_bp.route(
    "/bulk-import",
    methods=["POST", "OPTIONS"],
    strict_slashes=False,
)
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_CREATE)
def bulk_import_execute():
    """Import validated rows from Excel."""
    send_email_raw = request.form.get("send_email", "true")
    if isinstance(send_email_raw, str):
        send_email = send_email_raw.lower() in ("1", "true", "yes", "on")
    else:
        send_email = bool(send_email_raw)

    data, err = _read_xlsx_bytes()
    if err:
        return err

    try:
        result = run_import(data, send_email)
        err_msg = result.get("error")
        if err_msg:
            if "limit" in (err_msg or "").lower():
                return error_response(
                    "Forbidden",
                    err_msg,
                    403,
                    details=result,
                )
            return error_response("BulkImportError", err_msg, 400, details=result)
        return success_response(data=result, message="Bulk import completed")
    except ValueError as e:
        return validation_error_response(str(e))
    except Exception as e:
        return error_response("BulkImportError", str(e), 400)
