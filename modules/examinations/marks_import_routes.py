"""Uploading a marks sheet, and downloading the template for one.

REST rather than GraphQL, and not by preference: there is no upload scalar in
this schema, and binary transfer is the one case `graphql-conventions.md`
leaves to REST. The student importer established the shape — multipart in,
`file` field, `.xlsx` only — and this follows it rather than inventing a second.

**Nothing here decides anything.** Authority, the paper's lock, eligibility,
row validation and atomicity are all `marks_import`'s, which is in turn
`record_marks`'. These functions read a file off the request, hand it to the
service, and translate the answer.
"""

from flask import g, request

from core.decorators import auth_required, require_permission, tenant_required
from core.feature_flags import require_feature
from modules.examinations import examinations_bp
from modules.examinations import marks_import, marksheet_service
from core.uploads import SpreadsheetTooLarge, read_spreadsheet_bytes
from shared.helpers import error_response, success_response, validation_error_response

# The same key entering marks by hand needs. Importing is a way of marking, not
# a separate authority — and `marker_authority` inside the service still
# applies ADR-014 on top, so holding the key is not enough on its own.
PERM_ENTER = "assessment.enter"

# What a refusal means over HTTP. The service's own code travels in `details`
# so a client can tell a locked paper from a bad sheet without reading English.
_STATUS_FOR_CODE = {
    "PAPER_NOT_FOUND": 404,
    "NOT_FOUND": 404,
    "FORBIDDEN": 403,
    "NOT_THE_MARKER": 403,
    "PAPER_LOCKED": 409,
    "WRONG_STATUS": 409,
    "RESULT_NOT_PUBLISHED": 409,
}


# The same gate the GraphQL fields carry. These four endpoints are REST
# only because they move a spreadsheet or a PDF; nothing about the
# transport makes them a way in when the module is switched off.
FEATURE = "examinations"


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


def _refused(result):
    """One refusal shape for both calls, carrying the domain code through."""
    code = result.get("code") or "IMPORT_FAILED"
    status = _STATUS_FOR_CODE.get(code, 400)
    details = {"code": code}
    # A row-level report is the useful part of a refused import: the teacher
    # needs every problem in the sheet, not the first one.
    if "preview" in result:
        details["preview"] = result["preview"]
        details["summary"] = result["summary"]
    return error_response(code, result.get("error", "Import failed"), status, details)


@examinations_bp.route(
    "/papers/<paper_id>/marks/preview", methods=["POST"], strict_slashes=False
)
@tenant_required
@auth_required
@require_feature(FEATURE)
@require_permission(PERM_ENTER)
def preview_marks_sheet(paper_id):
    """Validate a sheet and report on every row. **Writes nothing.**"""
    data, err = _read_xlsx_bytes()
    if err:
        return err

    result = marks_import.preview_marks(
        g.tenant_id, paper_id, data, actor_user_id=g.current_user.id
    )
    if not result.get("success"):
        return _refused(result)
    return success_response(
        data={"preview": result["preview"], "summary": result["summary"]}
    )


@examinations_bp.route(
    "/papers/<paper_id>/marks/import", methods=["POST"], strict_slashes=False
)
@tenant_required
@auth_required
@require_feature(FEATURE)
@require_permission(PERM_ENTER)
def import_marks_sheet(paper_id):
    """Write a sheet's marks — all of them, or none of them."""
    data, err = _read_xlsx_bytes()
    if err:
        return err

    result = marks_import.import_marks(
        g.tenant_id, paper_id, data, actor_user_id=g.current_user.id
    )
    if not result.get("success"):
        return _refused(result)
    return success_response(
        data={"imported": result["imported"], "summary": result["summary"]},
        message=f"{result['imported']} marks imported",
    )


@examinations_bp.route(
    "/papers/<paper_id>/marks/template", methods=["GET"], strict_slashes=False
)
@tenant_required
@auth_required
@require_feature(FEATURE)
@require_permission(PERM_ENTER)
def marks_template_download(paper_id):
    """The register as an empty sheet, so nobody types forty admission numbers."""
    from flask import Response

    result = marks_import.marks_template(
        g.tenant_id, paper_id, actor_user_id=g.current_user.id
    )
    if not result.get("success"):
        return _refused(result)
    return Response(
        result["content"],
        mimetype=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{result["filename"]}"'
        },
    )


@examinations_bp.route(
    "/<examination_id>/students/<student_id>/marksheet",
    methods=["GET"],
    strict_slashes=False,
)
@tenant_required
@auth_required
@require_feature(FEATURE)
@require_permission(marksheet_service.PERM_READ)
def download_marksheet(examination_id, student_id):
    """The published result as a document.

    REST because it returns a file — the same split the import above follows.
    `?version=` reprints a specific published version; omitted, the latest
    published one is used. An unpublished revision is never rendered.
    """
    from flask import Response

    raw = request.args.get("version")
    try:
        version = int(raw) if raw else None
    except ValueError:
        return validation_error_response("version must be a number")

    built = marksheet_service.marksheet_model(
        examination_id, student_id, g.tenant_id, version=version
    )
    if not built.get("success"):
        return _refused(built)

    pdf = marksheet_service.render_marksheet_pdf(built["marksheet"])
    if pdf is None:
        # WeasyPrint needs native libraries that are absent on some machines.
        # Saying so beats a 500 that looks like a bug in the result.
        return error_response(
            "PDF_UNAVAILABLE",
            "PDF rendering is not available on this server",
            503,
            {"code": "PDF_UNAVAILABLE"},
        )

    version_label = built["marksheet"]["result"]["version"]
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="marksheet-{student_id}-v{version_label}.pdf"'
            )
        },
    )
