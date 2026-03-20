"""
Holiday Routes

REST endpoints:
    GET    /api/holidays/            — list (filterable, paginated)
    POST   /api/holidays/            — create (single-day, range, or recurring)
    GET    /api/holidays/upcoming    — upcoming non-recurring holidays
    GET    /api/holidays/recurring   — all recurring weekly-off entries
    GET    /api/holidays/<id>        — get single record
    PUT    /api/holidays/<id>        — update
    DELETE /api/holidays/<id>        — delete
"""

from flask import request, g

from backend.modules.holidays import holidays_bp
from backend.core.decorators import (
    auth_required,
    tenant_required,
    require_permission,
    require_plan_feature,
)
from backend.core.decorators.rbac import require_any_permission
from backend.shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
)
from . import services

PERM_READ = "holiday.read"
PERM_CREATE = "holiday.create"
PERM_UPDATE = "holiday.update"
PERM_DELETE = "holiday.delete"
PERM_MANAGE = "holiday.manage"


@holidays_bp.route("/", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("holiday_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def list_holidays():
    """
    List holidays.

    Query params:
        academic_year_id, holiday_type, start_date, end_date, search,
        include_recurring (default true), limit, offset
    """
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        return validation_error_response("limit and offset must be integers")

    include_recurring_str = request.args.get("include_recurring", "true").lower()
    include_recurring = include_recurring_str != "false"

    result = services.list_holidays(
        tenant_id=g.tenant_id,
        academic_year_id=request.args.get("academic_year_id"),
        holiday_type=request.args.get("holiday_type"),
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
        search=request.args.get("search"),
        include_recurring=include_recurring,
        limit=limit,
        offset=offset,
    )
    if result["success"]:
        return success_response(data=result["data"])
    return error_response("FetchError", result["error"], 400)


@holidays_bp.route("/upcoming", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("holiday_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_upcoming_holidays():
    """Upcoming non-recurring holidays from today. Query: limit (default 10, max 50)."""
    try:
        limit = min(int(request.args.get("limit", 10)), 50)
    except ValueError:
        return validation_error_response("limit must be an integer")

    result = services.get_upcoming_holidays(tenant_id=g.tenant_id, limit=limit)
    if result["success"]:
        return success_response(data=result["data"])
    return error_response("FetchError", result["error"], 400)


@holidays_bp.route("/recurring", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("holiday_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_recurring_holidays():
    """Return all recurring weekly-off entries for the tenant."""
    result = services.get_recurring_holidays(tenant_id=g.tenant_id)
    if result["success"]:
        return success_response(data=result["data"])
    return error_response("FetchError", result["error"], 400)


@holidays_bp.route("/", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("holiday_management")
@require_any_permission(PERM_CREATE, PERM_MANAGE)
def create_holiday():
    """
    Create a holiday.

    Body (JSON):
        name                 — required
        start_date           — YYYY-MM-DD, required for non-recurring
        end_date             — YYYY-MM-DD, optional (defaults to start_date → single day)
        description          — optional
        holiday_type         — public|school|regional|optional|weekly_off (default: school)
        academic_year_id     — optional UUID
        is_recurring         — bool (default false)
        recurring_day_of_week — 0-6 (Mon-Sun), required when is_recurring=true
    """
    data = request.get_json(silent=True)
    if not data:
        return validation_error_response("Request body must be valid JSON")

    tenant_id = g.tenant_id
    result = services.create_holiday(data, tenant_id)

    if result["success"]:
        return success_response(
            data=result["data"],
            message="Holiday created successfully",
            status_code=201,
        )
    if result.get("details"):
        return validation_error_response(result["details"])
    return error_response("CreateError", result["error"], 400)


@holidays_bp.route("/<string:holiday_id>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("holiday_management")
@require_any_permission(PERM_READ, PERM_MANAGE)
def get_holiday(holiday_id):
    result = services.get_holiday(holiday_id, tenant_id=g.tenant_id)
    if result["success"]:
        return success_response(data=result["data"])
    if result.get("not_found"):
        return not_found_response("Holiday")
    return error_response("FetchError", result["error"], 400)


@holidays_bp.route("/<string:holiday_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("holiday_management")
@require_any_permission(PERM_UPDATE, PERM_MANAGE)
def update_holiday(holiday_id):
    """Update a holiday. All body fields are optional — only sent fields are changed."""
    data = request.get_json(silent=True)
    if not data:
        return validation_error_response("Request body must be valid JSON")

    result = services.update_holiday(holiday_id, data, g.tenant_id)

    if result["success"]:
        return success_response(data=result["data"], message="Holiday updated successfully")
    if result.get("not_found"):
        return not_found_response("Holiday")
    if result.get("details"):
        return validation_error_response(result["details"])
    return error_response("UpdateError", result["error"], 400)


@holidays_bp.route("/<string:holiday_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("holiday_management")
@require_any_permission(PERM_DELETE, PERM_MANAGE)
def delete_holiday(holiday_id):
    result = services.delete_holiday(holiday_id, tenant_id=g.tenant_id)
    if result["success"]:
        return success_response(message=result["message"])
    if result.get("not_found"):
        return not_found_response("Holiday")
    return error_response("DeleteError", result["error"], 400)
