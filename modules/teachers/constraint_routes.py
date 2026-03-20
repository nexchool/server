"""
Teacher Constraint Routes

Endpoints for:
  - Teacher Subject Expertise:  GET/POST/DELETE /api/teachers/<id>/subjects
  - Teacher Availability:       GET/POST/PUT/DELETE /api/teachers/<id>/availability
  - Teacher Leaves:             POST/GET /api/teachers/leaves
                                PUT /api/teachers/leaves/<id>/approve|reject|cancel
  - Leave Balances:             GET /api/teachers/leave-balances/my
                                GET /api/teachers/<id>/leave-balances
                                PUT /api/teachers/<id>/leave-balances/<type>
  - Leave Policy:               GET /api/teachers/leave-policy
                                PUT /api/teachers/leave-policy/<type>
  - Teacher Workload Rules:     GET/POST/PUT /api/teachers/<id>/workload
"""

from flask import request, g
from backend.modules.teachers import teachers_bp
from backend.core.decorators import require_permission, auth_required, tenant_required, require_plan_feature
from backend.shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
)
from . import constraint_services as svc
from . import services as teacher_svc

PERM_MANAGE = "teacher.manage"
PERM_LEAVE_APPLY = "teacher.leave.apply"
PERM_LEAVE_MANAGE = "teacher.leave.manage"


# ===========================================================================
# Feature 1 — Teacher Subject Expertise
# ===========================================================================

@teachers_bp.route("/<teacher_id>/subjects", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_MANAGE)
def list_teacher_subjects(teacher_id):
    """List all subjects a teacher is qualified to teach."""
    subjects = svc.get_teacher_subjects(teacher_id)
    return success_response(data=subjects)


@teachers_bp.route("/<teacher_id>/subjects", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_MANAGE)
def add_teacher_subject(teacher_id):
    """Assign a subject to a teacher."""
    data = request.get_json() or {}
    subject_id = data.get("subject_id")
    if not subject_id:
        return validation_error_response("subject_id is required")

    result = svc.add_teacher_subject(teacher_id, subject_id)
    if result["success"]:
        return success_response(data=result["teacher_subject"], message="Subject assigned to teacher", status_code=201)
    return error_response("AssignError", result["error"], 400)


@teachers_bp.route("/<teacher_id>/subjects/<subject_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_MANAGE)
def remove_teacher_subject(teacher_id, subject_id):
    """Remove a subject from a teacher."""
    result = svc.remove_teacher_subject(teacher_id, subject_id)
    if result["success"]:
        return success_response(message="Subject removed from teacher")
    return error_response("RemoveError", result["error"], 400)


# ===========================================================================
# Feature 2 — Teacher Availability
# ===========================================================================

@teachers_bp.route("/<teacher_id>/availability", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def list_teacher_availability(teacher_id):
    """List availability records for a teacher."""
    items = svc.get_teacher_availability(teacher_id)
    return success_response(data=items)


@teachers_bp.route("/<teacher_id>/availability", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def create_teacher_availability(teacher_id):
    """Create an availability record for a teacher."""
    data = request.get_json() or {}
    day_of_week = data.get("day_of_week")
    period_number = data.get("period_number")
    available = data.get("available")

    if day_of_week is None or period_number is None or available is None:
        return validation_error_response("day_of_week, period_number, and available are required")

    result = svc.create_availability(teacher_id, int(day_of_week), int(period_number), bool(available))
    if result["success"]:
        return success_response(data=result["availability"], message="Availability created", status_code=201)
    return error_response("CreateError", result["error"], 400)


@teachers_bp.route("/<teacher_id>/availability/<availability_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def update_teacher_availability(teacher_id, availability_id):
    """Update an availability record."""
    data = request.get_json() or {}
    available = data.get("available")
    if available is None:
        return validation_error_response("available is required")

    result = svc.update_availability(availability_id, bool(available))
    if result["success"]:
        return success_response(data=result["availability"], message="Availability updated")
    return error_response("UpdateError", result["error"], 400)


@teachers_bp.route("/<teacher_id>/availability/<availability_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def delete_teacher_availability(teacher_id, availability_id):
    """Delete an availability record."""
    result = svc.delete_availability(availability_id)
    if result["success"]:
        return success_response(message="Availability record deleted")
    return error_response("DeleteError", result["error"], 400)


# ===========================================================================
# Feature 3 — Teacher Leaves
# ===========================================================================

@teachers_bp.route("/leaves", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_LEAVE_APPLY)
def create_teacher_leave():
    """Submit a leave request. teacher_id is derived from the authenticated user."""
    data = request.get_json() or {}

    start_date = data.get("start_date")
    end_date = data.get("end_date")
    leave_type = data.get("leave_type", "casual")
    reason = data.get("reason")

    if not start_date or not end_date:
        return validation_error_response("start_date and end_date are required")

    teacher = teacher_svc.get_teacher_by_user_id(g.current_user.id)
    if not teacher:
        return not_found_response("Teacher profile")

    result = svc.create_leave(teacher["id"], start_date, end_date, leave_type, reason)
    if result["success"]:
        return success_response(data=result["leave"], message="Leave request submitted", status_code=201)
    return error_response("LeaveError", result["error"], 400)


@teachers_bp.route("/leaves/my", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_LEAVE_APPLY)
def list_my_leaves():
    """List leave requests for the authenticated teacher. Supports ?status filter."""
    teacher = teacher_svc.get_teacher_by_user_id(g.current_user.id)
    if not teacher:
        return not_found_response("Teacher profile")

    status = request.args.get("status")
    leaves = svc.list_leaves(teacher_id=teacher["id"], status=status)
    return success_response(data=leaves)


@teachers_bp.route("/leaves", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_LEAVE_MANAGE)
def list_teacher_leaves():
    """List all leave requests (admin view). Supports ?teacher_id and ?status filters."""
    teacher_id = request.args.get("teacher_id")
    status = request.args.get("status")
    leaves = svc.list_leaves(teacher_id=teacher_id, status=status)
    return success_response(data=leaves)


@teachers_bp.route("/leaves/<leave_id>/cancel", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_LEAVE_APPLY)
def cancel_teacher_leave(leave_id):
    """Cancel a pending leave request (teacher cancels their own leave)."""
    teacher = teacher_svc.get_teacher_by_user_id(g.current_user.id)
    if not teacher:
        return not_found_response("Teacher profile")

    result = svc.cancel_leave(leave_id, teacher["id"])
    if result["success"]:
        return success_response(data=result["leave"], message="Leave cancelled")
    return error_response("CancelError", result["error"], 400)


@teachers_bp.route("/leaves/<leave_id>/approve", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_LEAVE_MANAGE)
def approve_teacher_leave(leave_id):
    """Approve a teacher leave request."""
    result = svc.approve_leave(leave_id)
    if result["success"]:
        return success_response(data=result["leave"], message="Leave approved")
    return error_response("ApproveError", result["error"], 400)


@teachers_bp.route("/leaves/<leave_id>/reject", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_LEAVE_MANAGE)
def reject_teacher_leave(leave_id):
    """Reject a teacher leave request."""
    result = svc.reject_leave(leave_id)
    if result["success"]:
        return success_response(data=result["leave"], message="Leave rejected")
    return error_response("RejectError", result["error"], 400)


# ===========================================================================
# Feature 3b — Leave Balance & Policy
# ===========================================================================

@teachers_bp.route("/leave-balances/my", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_LEAVE_APPLY)
def get_my_leave_balances():
    """Return leave balances for the authenticated teacher (current academic year)."""
    teacher = teacher_svc.get_teacher_by_user_id(g.current_user.id)
    if not teacher:
        return not_found_response("Teacher profile")

    academic_year = request.args.get("academic_year")
    balances = svc.get_teacher_leave_balances(teacher["id"], academic_year)
    return success_response(data=balances)


@teachers_bp.route("/<teacher_id>/leave-balances", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_LEAVE_MANAGE)
def get_teacher_leave_balances(teacher_id):
    """Admin: return leave balances for a specific teacher."""
    academic_year = request.args.get("academic_year")
    balances = svc.get_teacher_leave_balances(teacher_id, academic_year)
    return success_response(data=balances)


@teachers_bp.route("/<teacher_id>/leave-balances/<leave_type>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_LEAVE_MANAGE)
def adjust_teacher_leave_balance(teacher_id, leave_type):
    """Admin: override the allocated leave days for a teacher and leave type."""
    data = request.get_json() or {}
    allocated_days = data.get("allocated_days")
    if allocated_days is None:
        return validation_error_response("allocated_days is required")

    notes = data.get("notes")
    academic_year = data.get("academic_year")

    result = svc.adjust_teacher_leave_balance(
        teacher_id=teacher_id,
        leave_type=leave_type,
        allocated_days=int(allocated_days),
        notes=notes,
        adjusted_by_user_id=g.current_user.id,
        academic_year=academic_year,
    )
    if result["success"]:
        return success_response(data=result["balance"], message="Leave balance updated")
    return error_response("BalanceError", result["error"], 400)


@teachers_bp.route("/leave-policy", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_LEAVE_APPLY)
def get_leave_policy():
    """Return leave policies for all leave types for this tenant."""
    policies = svc.get_all_policies()
    return success_response(data=policies)


@teachers_bp.route("/leave-policy/<leave_type>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("teacher_management")
@require_permission(PERM_LEAVE_MANAGE)
def update_leave_policy(leave_type):
    """Admin: create or update the leave policy for a specific leave type."""
    data = request.get_json() or {}
    result = svc.upsert_leave_policy(
        leave_type=leave_type,
        total_days=data.get("total_days"),
        is_unlimited=data.get("is_unlimited"),
        is_carry_forward_allowed=data.get("is_carry_forward_allowed"),
        max_carry_forward_days=data.get("max_carry_forward_days"),
        allow_negative=data.get("allow_negative"),
        requires_reason=data.get("requires_reason"),
    )
    if result["success"]:
        return success_response(data=result["policy"], message="Leave policy updated")
    return error_response("PolicyError", result["error"], 400)


# ===========================================================================
# Feature 4 — Teacher Workload Rules
# ===========================================================================

@teachers_bp.route("/<teacher_id>/workload", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def get_teacher_workload(teacher_id):
    """Get workload rule for a teacher."""
    rule = svc.get_workload_rule(teacher_id)
    if rule is None:
        return not_found_response("Workload rule")
    return success_response(data=rule)


@teachers_bp.route("/<teacher_id>/workload", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def create_teacher_workload(teacher_id):
    """Create a workload rule for a teacher."""
    data = request.get_json() or {}
    max_per_day = data.get("max_periods_per_day")
    max_per_week = data.get("max_periods_per_week")

    if max_per_day is None or max_per_week is None:
        return validation_error_response("max_periods_per_day and max_periods_per_week are required")

    result = svc.create_workload_rule(teacher_id, int(max_per_day), int(max_per_week))
    if result["success"]:
        return success_response(data=result["workload"], message="Workload rule created", status_code=201)
    return error_response("WorkloadError", result["error"], 400)


@teachers_bp.route("/<teacher_id>/workload", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def update_teacher_workload(teacher_id):
    """Update (or upsert) the workload rule for a teacher."""
    data = request.get_json() or {}
    max_per_day = data.get("max_periods_per_day")
    max_per_week = data.get("max_periods_per_week")

    result = svc.update_workload_rule(
        teacher_id,
        int(max_per_day) if max_per_day is not None else None,
        int(max_per_week) if max_per_week is not None else None,
    )
    if result["success"]:
        return success_response(data=result["workload"], message="Workload rule updated")
    return error_response("WorkloadError", result["error"], 400)
