"""
Timetable Routes

REST API for timetable slot CRUD. All routes require tenant context and RBAC permissions.
"""

from flask import request, g

from backend.modules.timetable import timetable_bp
from backend.core.decorators import (
    require_permission,
    auth_required,
    tenant_required,
    require_plan_feature,
)
from backend.shared.helpers import (
    success_response,
    error_response,
    not_found_response,
    validation_error_response,
)
from . import services
from . import generator as gen_svc

# Permissions
PERM_READ = "timetable.read"
PERM_CREATE = "timetable.create"
PERM_UPDATE = "timetable.update"
PERM_DELETE = "timetable.delete"
PERM_MANAGE = "timetable.manage"


@timetable_bp.route("/generate", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def generate_timetable():
    """
    Smart timetable generator.

    Reads SubjectLoad, TeacherSubject, TeacherAvailability, TeacherLeaves,
    and TeacherWorkloadRule constraints for the given class, then runs a
    greedy multi-attempt algorithm to fill the weekly 5×8 grid.

    Body:
        class_id (str, required)
        overwrite_existing (bool, default false) – delete existing slots first

    Response:
        {success, slots_created, total_periods_needed, conflicts[]}
    """
    data = request.get_json() or {}
    class_id = data.get("class_id")
    overwrite_existing = bool(data.get("overwrite_existing", False))

    if not class_id:
        return validation_error_response("class_id is required")

    result = gen_svc.generate_timetable(class_id, overwrite_existing)

    if not result.get("success"):
        return error_response("GeneratorError", result.get("error", "Generation failed"), 400)

    return success_response(
        data={
            "slots_created": result["slots_created"],
            "total_periods_needed": result["total_periods_needed"],
            "conflicts": result["conflicts"],
        },
        message=_generation_message(result),
        status_code=201,
    )


def _generation_message(result: dict) -> str:
    created = result["slots_created"]
    needed = result["total_periods_needed"]
    n_conflicts = len(result["conflicts"])
    if n_conflicts == 0:
        return f"Timetable generated successfully: {created}/{needed} slots filled with no conflicts."
    return (
        f"Timetable generated: {created}/{needed} slots filled. "
        f"{n_conflicts} slot(s) could not be assigned — see conflicts."
    )


@timetable_bp.route("/config", methods=["GET"], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def get_config():
    """Get timetable configuration (duration, breaks, etc.) for this school."""
    tenant_id = g.tenant_id
    result = services.get_timetable_config(tenant_id)
    return success_response(data=result["config"])


@timetable_bp.route("/config", methods=["PUT"], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def update_config():
    """Update timetable configuration. Persisted per school."""
    data = request.get_json() or {}
    tenant_id = g.tenant_id
    result = services.upsert_timetable_config(tenant_id, data)
    return success_response(data=result["config"], message="Timetable configuration saved")


@timetable_bp.route("/check-conflicts", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_MANAGE)
def check_conflicts():
    """
    Check all timetable constraints for a proposed slot placement.

    Body:
        class_id (str, required)
        teacher_id (str, required)
        subject_id (str, required)
        day (int, required) — 0-indexed day of week
        period (int, required)
        exclude_slot_id (str, optional) — exclude when editing an existing slot

    Response:
        {has_conflict, conflicts[{type, message, class_id, day, period}]}
    """
    data = request.get_json() or {}
    required = ["class_id", "teacher_id", "subject_id", "day", "period"]
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return validation_error_response(f"Missing required fields: {', '.join(missing)}")

    from . import validators

    result = validators.check_slot_conflicts(
        class_id=data["class_id"],
        teacher_id=data["teacher_id"],
        subject_id=data["subject_id"],
        day=int(data["day"]),
        period=int(data["period"]),
        tenant_id=g.tenant_id,
        exclude_slot_id=data.get("exclude_slot_id"),
    )
    return success_response(data=result)


# ---------------------------------------------------------------------------
# Drag-and-drop editing endpoints
# ---------------------------------------------------------------------------

@timetable_bp.route("/slots/<slot_id>/move", methods=["PATCH"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_UPDATE)
def move_slot(slot_id):
    """
    Move a timetable slot to a new day/period (drag-and-drop).

    Body:
        day (int, required) — 0-indexed day of week
        period (int, required)

    On conflict returns:
        {success: false, conflicts: [{type, message, day, period}]}
    """
    data = request.get_json() or {}
    if data.get("day") is None or data.get("period") is None:
        return validation_error_response("day and period are required")

    result = services.move_slot(
        slot_id=slot_id,
        day=int(data["day"]),
        period=int(data["period"]),
        tenant_id=g.tenant_id,
    )

    if result.get("conflicts"):
        return success_response(
            data={"success": False, "conflicts": result["conflicts"]},
            status_code=409,
        )
    if not result["success"]:
        if result.get("error") == "Timetable slot not found":
            return not_found_response("Timetable slot")
        return error_response("MoveError", result["error"], 400)

    return success_response(
        data=result["slot"],
        message="Slot moved successfully",
    )


@timetable_bp.route("/slots/swap", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_UPDATE)
def swap_slots():
    """
    Swap positions of two timetable slots (drag-and-drop onto occupied cell).

    Body:
        slot_a_id (str, required)
        slot_b_id (str, required)

    On conflict returns:
        {success: false, conflicts: [{type, message, day, period, slot}]}
    """
    data = request.get_json() or {}
    slot_a_id = data.get("slot_a_id")
    slot_b_id = data.get("slot_b_id")

    if not slot_a_id or not slot_b_id:
        return validation_error_response("slot_a_id and slot_b_id are required")

    result = services.swap_slots(
        slot_a_id=slot_a_id,
        slot_b_id=slot_b_id,
        tenant_id=g.tenant_id,
    )

    if result.get("conflicts"):
        return success_response(
            data={"success": False, "conflicts": result["conflicts"]},
            status_code=409,
        )
    if not result["success"]:
        return error_response("SwapError", result.get("error", "Swap failed"), 400)

    return success_response(
        data={"slot_a": result["slot_a"], "slot_b": result["slot_b"]},
        message="Slots swapped successfully",
    )


@timetable_bp.route("/slots/<slot_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_DELETE)
def remove_slot(slot_id):
    """Delete a single timetable slot (drag-and-drop editing context)."""
    result = services.delete_slot(slot_id, g.tenant_id)

    if not result["success"]:
        if result.get("error") == "Timetable slot not found":
            return not_found_response("Timetable slot")
        return error_response("DeleteError", result["error"], 400)

    return success_response(message="Slot removed successfully")


# ---------------------------------------------------------------------------
# Generic CRUD
# ---------------------------------------------------------------------------

@timetable_bp.route("/", methods=["POST"], strict_slashes=False)
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_permission(PERM_CREATE)
def create_slot():
    """Create a new timetable slot."""
    data = request.get_json() or {}
    required = ["class_id", "subject_id", "teacher_id", "day_of_week", "period_number", "start_time", "end_time"]
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return validation_error_response(f"Missing required fields: {', '.join(missing)}")

    tenant_id = g.tenant_id
    result = services.create_slot(data, tenant_id)

    if result["success"]:
        return success_response(
            data=result["slot"],
            message="Timetable slot created successfully",
            status_code=201,
        )
    return error_response("CreationError", result["error"], 400)


@timetable_bp.route("/class/<class_id>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_permission(PERM_READ)
def get_slots_by_class(class_id):
    """Get all timetable slots for a class."""
    tenant_id = g.tenant_id
    slots = services.get_slots_by_class(class_id, tenant_id)
    return success_response(data=slots)


@timetable_bp.route("/<slot_id>", methods=["PUT"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_permission(PERM_UPDATE)
def update_slot(slot_id):
    """Update a timetable slot."""
    data = request.get_json() or {}
    tenant_id = g.tenant_id
    result = services.update_slot(slot_id, data, tenant_id)

    if result["success"]:
        return success_response(
            data=result["slot"],
            message="Timetable slot updated successfully",
        )
    if result.get("error") == "Timetable slot not found":
        return not_found_response("Timetable slot")
    return error_response("UpdateError", result["error"], 400)


@timetable_bp.route("/<slot_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_permission(PERM_DELETE)
def delete_slot(slot_id):
    """Delete a timetable slot."""
    tenant_id = g.tenant_id
    result = services.delete_slot(slot_id, tenant_id)

    if result["success"]:
        return success_response(message="Timetable slot deleted successfully")
    if result.get("error") == "Timetable slot not found":
        return not_found_response("Timetable slot")
    return error_response("DeleteError", result["error"], 400)
