"""
Academic Calendar Routes — /api/academics/calendar

    GET    /calendar?academic_year_id=…       — calendar state for a year (null if not started)
    POST   /calendar                          — create/fetch the draft for a year
    PATCH  /calendar/<id>                     — update wizard step / weekly-holiday config
    GET    /calendar/<id>/summary             — review + dashboard stats
    GET    /calendar/<id>/days                — per-day classification feed (whole year)
    POST   /calendar/<id>/publish             — validate everything and publish

    GET    /calendar/exam-windows?academic_year_id=…
    POST   /calendar/exam-windows
    PUT    /calendar/exam-windows/<id>
    DELETE /calendar/exam-windows/<id>

    GET    /calendar/events?academic_year_id=…
    POST   /calendar/events
    PUT    /calendar/events/<id>
    DELETE /calendar/events/<id>
"""

from io import BytesIO

from flask import g, request, send_file

from core.decorators import (
    auth_required,
    require_feature,
    require_permission,
    tenant_required,
)
from core.decorators.rbac import require_any_permission
from modules.academics import academics_bp
from shared.helpers import (
    error_response,
    not_found_response,
    success_response,
    validation_error_response,
)

from . import export_services, import_services, services
from .activity import resolve_user_names
from .services import CalendarValidationError

# Granular per-action permissions. `manage` is a superset of every
# `academic_calendar.*` (rbac.services.has_permission), so a holder of
# `academic_calendar.manage` (the Admin role) passes all of these routes.
PERM_READ = "academic_calendar.read"        # View
PERM_MANAGE = "academic_calendar.manage"    # superset
PERM_CREATE = "academic_calendar.create"
PERM_EDIT = "academic_calendar.edit"
PERM_DELETE = "academic_calendar.delete"
PERM_ARCHIVE = "academic_calendar.archive"
PERM_EXPORT = "academic_calendar.export"
PERM_IMPORT = "academic_calendar.import"
PERM_PRINT = "academic_calendar.print"
PERM_SETTINGS = "academic_calendar.settings"


def _require_year_id():
    academic_year_id = (request.args.get("academic_year_id") or "").strip()
    if not academic_year_id:
        return None, validation_error_response(
            {"academic_year_id": "academic_year_id query parameter is required."}
        )
    return academic_year_id, None


# ---------------------------------------------------------------------------
# Calendar state
# ---------------------------------------------------------------------------

@academics_bp.route("/calendar", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_calendar_state():
    academic_year_id, err = _require_year_id()
    if err:
        return err
    cal = services.get_calendar_for_year(academic_year_id)
    return success_response(data=cal.to_dict() if cal else None)


@academics_bp.route("/calendar", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_CREATE)
def create_calendar_draft():
    data = request.get_json() or {}
    academic_year_id = (data.get("academic_year_id") or "").strip()
    if not academic_year_id:
        return validation_error_response(
            {"academic_year_id": "academic_year_id is required."}
        )
    try:
        cal = services.get_or_create_calendar(academic_year_id)
    except CalendarValidationError as e:
        return validation_error_response(e.errors)
    return success_response(
        data=cal.to_dict(), message="Calendar draft ready", status_code=201
    )


@academics_bp.route("/calendar/<calendar_id>", methods=["PATCH"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_EDIT)
def update_calendar_state(calendar_id):
    cal = services.get_calendar(calendar_id)
    if not cal:
        return not_found_response("Calendar not found")
    try:
        cal = services.update_calendar(cal, request.get_json() or {})
    except CalendarValidationError as e:
        return validation_error_response(e.errors)
    return success_response(data=cal.to_dict(), message="Calendar updated")


@academics_bp.route("/calendar/<calendar_id>/summary", methods=["GET"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_calendar_summary(calendar_id):
    cal = services.get_calendar(calendar_id)
    if not cal:
        return not_found_response("Calendar not found")
    try:
        return success_response(data=services.compute_summary(cal))
    except CalendarValidationError as e:
        return validation_error_response(e.errors)


@academics_bp.route("/calendar/<calendar_id>/days", methods=["GET"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_calendar_days(calendar_id):
    cal = services.get_calendar(calendar_id)
    if not cal:
        return not_found_response("Calendar not found")
    try:
        return success_response(data=services.get_days_feed(cal))
    except CalendarValidationError as e:
        return validation_error_response(e.errors)


@academics_bp.route("/calendar/<calendar_id>/export", methods=["GET"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_EXPORT)
def export_calendar_document(calendar_id):
    cal = services.get_calendar(calendar_id)
    if not cal:
        return not_found_response("Calendar not found")

    fmt = (request.args.get("format") or "csv").strip().lower()
    # sections: repeated ?sections=a&sections=b or a single comma-joined value.
    sections = request.args.getlist("sections") or None
    if sections and len(sections) == 1 and "," in sections[0]:
        sections = [s.strip() for s in sections[0].split(",")]

    try:
        content, mimetype, filename = export_services.export_calendar(cal, fmt, sections)
    except ValueError as e:
        return validation_error_response({"format": str(e)})
    except export_services.ExportUnavailableError as e:
        return error_response("export_unavailable", message=str(e), status_code=503)

    services.record_calendar_activity(
        cal, "export_completed", f"Calendar exported as {fmt.upper()}", {"format": fmt}
    )
    return send_file(
        BytesIO(content),
        mimetype=mimetype,
        as_attachment=True,
        download_name=filename,
    )


@academics_bp.route("/calendar/<calendar_id>/print-log", methods=["POST"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_PRINT)
def log_calendar_print(calendar_id):
    cal = services.get_calendar(calendar_id)
    if not cal:
        return not_found_response("Calendar not found")
    mode = (request.get_json() or {}).get("mode") or "full"
    services.record_calendar_activity(
        cal, "print_executed", f"Calendar printed ({mode})", {"mode": mode}
    )
    return success_response(message="Print recorded")


@academics_bp.route("/calendar/<calendar_id>/activity", methods=["GET"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_calendar_activity(calendar_id):
    cal = services.get_calendar(calendar_id)
    if not cal:
        return not_found_response("Calendar not found")
    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(100, max(1, int(request.args.get("page_size", 20))))
    except (TypeError, ValueError):
        page, page_size = 1, 20
    return success_response(data=services.list_calendar_activity(cal, page, page_size))


@academics_bp.route("/calendar/<calendar_id>/publish", methods=["POST"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_EDIT)
def publish_calendar(calendar_id):
    cal = services.get_calendar(calendar_id)
    if not cal:
        return not_found_response("Calendar not found")
    user_id = g.current_user.id if g.current_user else None
    try:
        summary = services.publish_calendar(cal, user_id)
    except CalendarValidationError as e:
        return validation_error_response(e.errors)
    return success_response(
        data={"calendar": cal.to_dict(), "summary": summary},
        message="Academic calendar published",
    )


# ---------------------------------------------------------------------------
# Admin: delete / archive / restore / preferences
# ---------------------------------------------------------------------------

def _current_user_id():
    return g.current_user.id if g.current_user else None


@academics_bp.route("/calendar/<calendar_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_DELETE)
def delete_calendar(calendar_id):
    cal = services.get_calendar(calendar_id)
    if not cal:
        return not_found_response("Calendar not found")
    try:
        services.delete_calendar(cal)
    except CalendarValidationError as e:
        return validation_error_response(e.errors)
    return success_response(message="Draft calendar deleted")


@academics_bp.route("/calendar/<calendar_id>/archive", methods=["POST"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_ARCHIVE)
def archive_calendar(calendar_id):
    cal = services.get_calendar(calendar_id)
    if not cal:
        return not_found_response("Calendar not found")
    try:
        cal = services.archive_calendar(cal, _current_user_id())
    except CalendarValidationError as e:
        return validation_error_response(e.errors)
    return success_response(data=cal.to_dict(), message="Calendar archived")


@academics_bp.route("/calendar/<calendar_id>/restore", methods=["POST"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_ARCHIVE)
def restore_calendar(calendar_id):
    cal = services.get_calendar(calendar_id)
    if not cal:
        return not_found_response("Calendar not found")
    try:
        cal = services.restore_calendar(cal, _current_user_id())
    except CalendarValidationError as e:
        return validation_error_response(e.errors)
    return success_response(data=cal.to_dict(), message="Calendar restored")


@academics_bp.route("/calendar/<calendar_id>/preferences", methods=["PATCH"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_SETTINGS)
def update_calendar_preferences(calendar_id):
    cal = services.get_calendar(calendar_id)
    if not cal:
        return not_found_response("Calendar not found")
    try:
        cal = services.update_preferences(cal, request.get_json() or {})
    except CalendarValidationError as e:
        return validation_error_response(e.errors)
    return success_response(data=cal.to_dict(), message="Preferences saved")


# ---------------------------------------------------------------------------
# Admin: import (template + upload)
# ---------------------------------------------------------------------------

@academics_bp.route("/calendar/<calendar_id>/import-template", methods=["GET"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_IMPORT)
def import_template(calendar_id):
    import_type = (request.args.get("type") or "").strip()
    try:
        content = import_services.import_template_csv(import_type)
    except import_services.ImportValidationError as e:
        return validation_error_response({"type": e.message})
    return send_file(
        BytesIO(content),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"import-template-{import_type}.csv",
    )


@academics_bp.route("/calendar/<calendar_id>/import", methods=["POST"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_IMPORT)
def import_calendar_data(calendar_id):
    cal = services.get_calendar(calendar_id)
    if not cal:
        return not_found_response("Calendar not found")

    if "file" not in request.files:
        return validation_error_response({"file": "A CSV file is required."})
    import_type = (request.form.get("type") or request.args.get("type") or "").strip()
    try:
        text = request.files["file"].read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return validation_error_response({"file": "File must be UTF-8 encoded CSV."})

    try:
        report = import_services.import_rows(cal, import_type, text)
    except import_services.ImportValidationError as e:
        return error_response(
            "invalid_template", message=e.message, status_code=422,
            details=e.details or None,
        )
    return success_response(
        data=report,
        message=f"Imported {report['imported']} of {report['total']} row(s)",
    )


# ---------------------------------------------------------------------------
# Exam windows
# ---------------------------------------------------------------------------

@academics_bp.route("/calendar/exam-windows", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_any_permission(PERM_READ, PERM_MANAGE)
def list_exam_windows():
    academic_year_id, err = _require_year_id()
    if err:
        return err
    windows = services.list_exam_windows(academic_year_id)
    return success_response(data=resolve_user_names([w.to_dict() for w in windows]))


@academics_bp.route("/calendar/exam-windows", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_EDIT)
def create_exam_window():
    data = request.get_json() or {}
    academic_year_id = (data.get("academic_year_id") or "").strip()
    if not academic_year_id:
        return validation_error_response(
            {"academic_year_id": "academic_year_id is required."}
        )
    try:
        window = services.create_exam_window(academic_year_id, data)
    except CalendarValidationError as e:
        return validation_error_response(e.errors)
    return success_response(
        data=window.to_dict(), message="Exam window created", status_code=201
    )


@academics_bp.route("/calendar/exam-windows/<window_id>", methods=["PUT", "PATCH"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_EDIT)
def update_exam_window(window_id):
    try:
        window = services.update_exam_window(window_id, request.get_json() or {})
    except CalendarValidationError as e:
        if "id" in e.errors:
            return not_found_response("Exam window not found")
        return validation_error_response(e.errors)
    return success_response(data=window.to_dict(), message="Exam window updated")


@academics_bp.route("/calendar/exam-windows/<window_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_EDIT)
def delete_exam_window(window_id):
    if not services.delete_exam_window(window_id):
        return not_found_response("Exam window not found")
    return success_response(message="Exam window deleted")


# ---------------------------------------------------------------------------
# School events
# ---------------------------------------------------------------------------

@academics_bp.route("/calendar/events", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_any_permission(PERM_READ, PERM_MANAGE)
def list_school_events():
    academic_year_id, err = _require_year_id()
    if err:
        return err
    events = services.list_school_events(academic_year_id)
    return success_response(data=resolve_user_names([e.to_dict() for e in events]))


@academics_bp.route("/calendar/events", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_EDIT)
def create_school_event():
    data = request.get_json() or {}
    academic_year_id = (data.get("academic_year_id") or "").strip()
    if not academic_year_id:
        return validation_error_response(
            {"academic_year_id": "academic_year_id is required."}
        )
    try:
        event = services.create_school_event(academic_year_id, data)
    except CalendarValidationError as e:
        return validation_error_response(e.errors)
    return success_response(
        data=event.to_dict(), message="Event created", status_code=201
    )


@academics_bp.route("/calendar/events/<event_id>", methods=["PUT", "PATCH"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_EDIT)
def update_school_event(event_id):
    try:
        event = services.update_school_event(event_id, request.get_json() or {})
    except CalendarValidationError as e:
        if "id" in e.errors:
            return not_found_response("School event not found")
        return validation_error_response(e.errors)
    return success_response(data=event.to_dict(), message="Event updated")


@academics_bp.route("/calendar/events/<event_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_EDIT)
def delete_school_event(event_id):
    if not services.delete_school_event(event_id):
        return not_found_response("School event not found")
    return success_response(message="Event deleted")
