"""
Schedule Routes

REST API for schedule endpoints: today's schedule, admin coverage view,
and per-day override management (substitute/activity/cancel).
"""

from datetime import date
from flask import g, request

from backend.modules.schedule import schedule_bp
from backend.core.decorators import (
    auth_required,
    tenant_required,
    require_plan_feature,
    require_permission,
)
from backend.shared.helpers import (
    success_response,
    error_response,
    validation_error_response,
    not_found_response,
)
from . import services


@schedule_bp.route("/today", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature("timetable")
def get_todays_schedule():
    """
    GET /api/schedule/today

    Returns today's schedule for the current user, enriched with:
      - teacher_on_leave, teacher_unavailable, needs_coverage
      - override (substitute/activity/cancelled for today)
    """
    user_id = g.current_user.id
    tenant_id = g.tenant_id
    slots = services.get_todays_schedule(user_id, tenant_id)
    return success_response(data=slots)


@schedule_bp.route("/today/all", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission("timetable.manage")
def get_all_slots_today():
    """
    GET /api/schedule/today/all

    Admin: all timetable slots for today across all classes,
    enriched with leave/unavailability and override data.
    Useful for identifying which classes need coverage.
    """
    tenant_id = g.tenant_id
    slots = services.get_all_slots_today(tenant_id)
    return success_response(data=slots)


@schedule_bp.route("/override", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission("timetable.manage")
def upsert_override():
    """
    POST /api/schedule/override

    Create or update a per-day override for a timetable slot.

    Body:
        slot_id         (str, required)
        override_date   (str, required, YYYY-MM-DD; omit for today)
        override_type   (str, required) – 'substitute' | 'activity' | 'cancelled'
        substitute_teacher_id  (str, required if substitute)
        activity_label  (str, required if activity)
        note            (str, optional)
    """
    data = request.get_json() or {}
    slot_id = data.get("slot_id")
    if not slot_id:
        return validation_error_response("slot_id is required")

    override_type = data.get("override_type")
    if not override_type:
        return validation_error_response("override_type is required (substitute | activity | cancelled)")

    date_str = data.get("override_date")
    if date_str:
        try:
            override_date = date.fromisoformat(date_str)
        except ValueError:
            return validation_error_response("override_date must be YYYY-MM-DD")
    else:
        override_date = date.today()

    result = services.upsert_override(
        slot_id=slot_id,
        override_date=override_date,
        override_type=override_type,
        tenant_id=g.tenant_id,
        created_by=g.current_user.id,
        substitute_teacher_id=data.get("substitute_teacher_id"),
        activity_label=data.get("activity_label"),
        note=data.get("note"),
    )

    if not result.get("success"):
        return error_response("OverrideError", result["error"], 400)

    return success_response(data=result["override"], message="Override saved", status_code=201)


@schedule_bp.route("/override", methods=["DELETE"], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission("timetable.manage")
def delete_override():
    """
    DELETE /api/schedule/override

    Remove an override, restoring the original slot for that day.

    Body:
        slot_id       (str, required)
        override_date (str, YYYY-MM-DD; omit for today)
    """
    data = request.get_json() or {}
    slot_id = data.get("slot_id")
    if not slot_id:
        return validation_error_response("slot_id is required")

    date_str = data.get("override_date")
    override_date = date.fromisoformat(date_str) if date_str else date.today()

    result = services.delete_override(slot_id, override_date, g.tenant_id)
    if not result.get("success"):
        return not_found_response("Override")
    return success_response(message="Override removed")
