"""
Bulk teacher import API (Excel preview + import).
"""
from shared.safe_error import safe_error

from flask import request

from core.decorators import (
    auth_required,
    require_permission,
    tenant_required,
    require_feature,
)
from modules.teachers import teachers_bp
from modules.teachers.bulk_teacher_import_service import run_import, run_preview
from core.uploads import SpreadsheetTooLarge, read_spreadsheet_bytes
from shared.helpers import error_response, success_response, validation_error_response

PERM_CREATE = "teacher.create"


def _read_xlsx_bytes():
    """Returns (bytes, None) or (None, error_response).

    Delegates to `core.uploads`, which measures the upload before reading it:
    an xlsx is a zip and openpyxl expands it in the worker's own memory, so an
    oversized file has to be refused rather than loaded and then reported on.
    """
    try:
        return read_spreadsheet_bytes(request.files.get("file")), None
    except SpreadsheetTooLarge as too_big:
        return None, error_response(
            "FileTooLarge",
            f"Spreadsheet must be {too_big.limit // (1024 * 1024)} MB or smaller",
            413,
        )
    except ValueError as bad:
        return None, validation_error_response(str(bad))


@teachers_bp.route(
    "/bulk-import/preview",
    methods=["POST", "OPTIONS"],
    strict_slashes=False,
)
@tenant_required
@auth_required
@require_feature("teacher_management")
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
        return error_response("BulkImportError", safe_error(e), 400)


@teachers_bp.route(
    "/bulk-import",
    methods=["POST", "OPTIONS"],
    strict_slashes=False,
)
@tenant_required
@auth_required
@require_feature("teacher_management")
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
        return error_response("BulkImportError", safe_error(e), 400)
