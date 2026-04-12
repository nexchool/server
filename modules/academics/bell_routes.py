"""Bell schedules and academic settings."""

from flask import g, request

from modules.academics import academics_bp
from core.decorators import auth_required, require_any_permission, tenant_required, require_plan_feature
from shared.helpers import error_response, success_response

from modules.academics.services import bell_schedules

PERM_READ = "academics.read"
PERM_MANAGE = "academics.manage"


@academics_bp.route("/bell-schedules", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_READ, PERM_MANAGE, "timetable.manage")
def list_bell_schedules():
    r = bell_schedules.list_schedules(g.tenant_id)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(
        data={
            "items": r["items"],
            "tenant_default_bell_schedule_id": r.get("tenant_default_bell_schedule_id"),
        }
    )


@academics_bp.route("/bell-schedules", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_MANAGE, "timetable.manage")
def create_bell_schedule():
    r = bell_schedules.create_schedule(g.tenant_id, request.get_json() or {})
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["bell_schedule"], status_code=201)


@academics_bp.route("/bell-schedules/<sid>", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_READ, PERM_MANAGE, "timetable.manage")
def get_bell_schedule(sid):
    r = bell_schedules.get_schedule(g.tenant_id, sid, include_periods=True)
    if not r["success"]:
        return error_response("NotFound", r["error"], 404)
    return success_response(data=r["bell_schedule"])


@academics_bp.route("/bell-schedules/<sid>", methods=["PATCH"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_MANAGE, "timetable.manage")
def patch_bell_schedule(sid):
    r = bell_schedules.update_schedule(g.tenant_id, sid, request.get_json() or {})
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["bell_schedule"])


@academics_bp.route("/bell-schedules/<sid>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_MANAGE, "timetable.manage")
def delete_bell_schedule(sid):
    r = bell_schedules.delete_schedule(g.tenant_id, sid)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(message=r.get("message", "OK"))


@academics_bp.route("/bell-schedules/<sid>/periods", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_READ, PERM_MANAGE, "timetable.manage")
def list_bell_periods(sid):
    r = bell_schedules.list_periods(g.tenant_id, sid)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data={"items": r["items"]})


@academics_bp.route("/bell-schedules/<sid>/periods", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_MANAGE, "timetable.manage")
def create_bell_period(sid):
    r = bell_schedules.create_period(g.tenant_id, sid, request.get_json() or {})
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["period"], status_code=201)


@academics_bp.route("/bell-schedules/<sid>/periods/<pid>", methods=["PATCH"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_MANAGE, "timetable.manage")
def patch_bell_period(sid, pid):
    r = bell_schedules.update_period(g.tenant_id, sid, pid, request.get_json() or {})
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["period"])


@academics_bp.route("/bell-schedules/<sid>/periods/<pid>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_MANAGE, "timetable.manage")
def delete_bell_period(sid, pid):
    r = bell_schedules.delete_period(g.tenant_id, sid, pid)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(message=r.get("message", "OK"))


@academics_bp.route("/settings", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_any_permission(PERM_READ, PERM_MANAGE, "class.manage")
def get_academic_settings_route():
    r = bell_schedules.get_academic_settings(g.tenant_id)
    return success_response(data=r["settings"])


@academics_bp.route("/settings", methods=["PATCH"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_any_permission(PERM_MANAGE, "class.manage")
def patch_academic_settings_route():
    r = bell_schedules.patch_academic_settings(g.tenant_id, request.get_json() or {})
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["settings"])
