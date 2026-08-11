"""My weekly timetable — REST.

Two reads, both for the signed-in person: a teacher's week and a student's
week. The class-centric timetable API (versions, entries, generation) lives
under `/api/classes/<id>/timetable` and owns the data; this surface exists
because a person's own week is assembled across classes, which that API
cannot answer.

The slot CRUD, generator, conflict-check and config endpoints that used to
live here were deleted with the parallel `timetable_slots` table in
migration 096.
"""

from datetime import date as _date

from flask import request, g

from modules.timetable import timetable_bp
from core.decorators import (
    require_permission,
    auth_required,
    tenant_required,
    require_feature,
    require_setup_complete,
    require_active_subscription,
)
from shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
)
from . import services

PERM_READ = "timetable.read"


def _parse_week_start_param():
    """Return (week_start_date|None, error_response|None)."""
    raw = request.args.get("week_start_date")
    if not raw:
        return None, None
    try:
        return _date.fromisoformat(raw), None
    except ValueError:
        return None, validation_error_response(
            {"week_start_date": "must be ISO date (YYYY-MM-DD)"}
        )


@timetable_bp.route("/teachers/me/weekly", methods=["GET"])
@tenant_required
@auth_required
@require_feature("timetable")
@require_setup_complete
@require_active_subscription
@require_permission(PERM_READ)
def teacher_weekly_timetable():
    """Return the authenticated teacher's weekly timetable.

    Query params:
        week_start_date: optional ISO date; any day in the target week works.
                         Normalized to that week's Monday.
        academic_year_id: optional; defaults to the active AY.

    Responses:
        200 success_response with {academic_year, week_start_date, week_end_date, days[7]}
        400 if week_start_date is malformed
        403 if the authenticated user has no Teacher row in this tenant
        404 if no published timetable exists for the resolved academic year
    """
    from .services import TimetableNotFoundError

    week_start, err = _parse_week_start_param()
    if err is not None:
        return err
    ay_id = request.args.get("academic_year_id")

    try:
        data = services.get_teacher_weekly_timetable(
            tenant_id=g.tenant_id,
            teacher_user_id=g.current_user.id,
            week_start_date=week_start,
            academic_year_id=ay_id,
        )
    except TimetableNotFoundError:
        return not_found_response("Timetable for this academic year")

    if data is None:
        return error_response(
            "Forbidden",
            "Only teachers can access this endpoint",
            403,
        )

    return success_response(data=data)


@timetable_bp.route("/students/me/weekly", methods=["GET"])
@tenant_required
@auth_required
@require_feature("timetable")
@require_setup_complete
@require_active_subscription
@require_permission(PERM_READ)
def student_weekly_timetable():
    """Return the authenticated student's weekly timetable.

    Query params: same shape as the teacher endpoint.

    Responses:
        200 success_response with weekly envelope
        400 if week_start_date is malformed
        403 if the authenticated user has no Student row in this tenant
        404 if no published timetable exists for the resolved academic year
    """
    from .services import TimetableNotFoundError, StudentNotEnrolledError

    week_start, err = _parse_week_start_param()
    if err is not None:
        return err
    ay_id = request.args.get("academic_year_id")

    try:
        data = services.get_student_weekly_timetable(
            tenant_id=g.tenant_id,
            student_user_id=g.current_user.id,
            week_start_date=week_start,
            academic_year_id=ay_id,
        )
    except TimetableNotFoundError:
        return not_found_response("Timetable for this academic year")
    except StudentNotEnrolledError:
        # 409 Conflict — the request is well-formed but the caller's account
        # state (no class enrollment for this AY) prevents fulfilment.
        return error_response(
            "NotEnrolled",
            "Student is not enrolled in a class for this academic year",
            409,
        )

    if data is None:
        return error_response(
            "Forbidden",
            "Only students can access this endpoint",
            403,
        )

    return success_response(data=data)
