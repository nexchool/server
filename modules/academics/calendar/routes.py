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

from flask import g, request

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

from . import services
from .services import CalendarValidationError

PERM_READ = "academic_calendar.read"
PERM_MANAGE = "academic_calendar.manage"


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
@require_permission(PERM_MANAGE)
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
@require_permission(PERM_MANAGE)
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


@academics_bp.route("/calendar/<calendar_id>/publish", methods=["POST"])
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_MANAGE)
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
    return success_response(data=[w.to_dict() for w in windows])


@academics_bp.route("/calendar/exam-windows", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_MANAGE)
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
@require_permission(PERM_MANAGE)
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
@require_permission(PERM_MANAGE)
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
    return success_response(data=[e.to_dict() for e in events])


@academics_bp.route("/calendar/events", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_feature("academic_calendar")
@require_permission(PERM_MANAGE)
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
@require_permission(PERM_MANAGE)
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
@require_permission(PERM_MANAGE)
def delete_school_event(event_id):
    if not services.delete_school_event(event_id):
        return not_found_response("School event not found")
    return success_response(message="Event deleted")
