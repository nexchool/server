"""
Academic backbone routes scoped under /api/classes/:class_id/...

TODO: Legacy subject-load routes remain; clients should migrate to /subjects APIs.
"""

from flask import g, request

from backend.modules.classes import classes_bp
from backend.core.decorators import (
    auth_required,
    require_any_permission,
    require_permission,
    tenant_required,
    require_plan_feature,
)
from backend.shared.helpers import success_response, error_response
from backend.modules.academics.services import (
    class_subjects,
    class_subject_teachers,
    class_teacher_assignments,
    timetable_v2,
)

PERM_CS_READ = "class_subject.read"
PERM_CS_MANAGE = "class_subject.manage"
PERM_CT_MANAGE = "class_teacher.manage"
PERM_TT_READ = "timetable.read"
PERM_TT_MANAGE = "timetable.manage"


# --- Class subjects ---


@classes_bp.route("/<class_id>/subjects", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_any_permission(PERM_CS_READ, PERM_CS_MANAGE, "class.manage")
def list_class_subjects(class_id):
    r = class_subjects.list_for_class(g.tenant_id, class_id)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data={"items": r["items"]})


@classes_bp.route("/<class_id>/subjects", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_any_permission(PERM_CS_MANAGE, "class.manage")
def create_class_subject(class_id):
    r = class_subjects.create_offering(g.tenant_id, class_id, request.get_json() or {})
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["class_subject"], status_code=201)


@classes_bp.route("/<class_id>/subjects/<cs_id>", methods=["PATCH"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_any_permission(PERM_CS_MANAGE, "class.manage")
def patch_class_subject(class_id, cs_id):
    r = class_subjects.update_offering(g.tenant_id, class_id, cs_id, request.get_json() or {})
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["class_subject"])


@classes_bp.route("/<class_id>/subjects/<cs_id>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_any_permission(PERM_CS_MANAGE, "class.manage")
def delete_class_subject(class_id, cs_id):
    r = class_subjects.delete_offering(g.tenant_id, class_id, cs_id)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(message=r.get("message", "OK"))


# --- Subject teachers ---


@classes_bp.route("/<class_id>/subject-teachers", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_CS_READ, PERM_CS_MANAGE, "class.manage")
def list_subject_teachers(class_id):
    r = class_subject_teachers.list_for_class(g.tenant_id, class_id)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data={"items": r["items"]})


@classes_bp.route("/<class_id>/subject-teachers", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_CS_MANAGE, "class.manage")
def create_subject_teacher(class_id):
    r = class_subject_teachers.create_assignment(
        g.tenant_id, class_id, request.get_json() or {}, user_id=g.current_user.id
    )
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["assignment"], status_code=201)


@classes_bp.route("/<class_id>/subject-teachers/<aid>", methods=["PATCH"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_CS_MANAGE, "class.manage")
def patch_subject_teacher(class_id, aid):
    r = class_subject_teachers.update_assignment(
        g.tenant_id, class_id, aid, request.get_json() or {}, user_id=g.current_user.id
    )
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["assignment"])


@classes_bp.route("/<class_id>/subject-teachers/<aid>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_CS_MANAGE, "class.manage")
def delete_subject_teacher(class_id, aid):
    r = class_subject_teachers.delete_assignment(g.tenant_id, class_id, aid)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(message=r.get("message", "OK"))


# --- Class teachers (authoritative) ---


@classes_bp.route("/<class_id>/class-teachers", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_any_permission(PERM_CT_MANAGE, "class.read", "class.manage")
def list_class_teachers(class_id):
    r = class_teacher_assignments.list_for_class(g.tenant_id, class_id)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data={"items": r["items"]})


@classes_bp.route("/<class_id>/class-teachers", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_any_permission(PERM_CT_MANAGE, "class.manage")
def create_class_teacher_assignment(class_id):
    r = class_teacher_assignments.create_assignment(
        g.tenant_id, class_id, request.get_json() or {}, user_id=g.current_user.id
    )
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["assignment"], status_code=201)


@classes_bp.route("/<class_id>/class-teachers/<aid>", methods=["PATCH"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_any_permission(PERM_CT_MANAGE, "class.manage")
def patch_class_teacher_assignment(class_id, aid):
    r = class_teacher_assignments.update_assignment(
        g.tenant_id, class_id, aid, request.get_json() or {}, user_id=g.current_user.id
    )
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["assignment"])


@classes_bp.route("/<class_id>/class-teachers/<aid>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("class_management")
@require_any_permission(PERM_CT_MANAGE, "class.manage")
def delete_class_teacher_assignment(class_id, aid):
    r = class_teacher_assignments.delete_assignment(g.tenant_id, class_id, aid)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(message=r.get("message", "OK"))


# --- Timetable v2 ---


@classes_bp.route("/<class_id>/timetable/versions", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_TT_READ, PERM_TT_MANAGE)
def list_timetable_versions(class_id):
    r = timetable_v2.list_versions(g.tenant_id, class_id)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data={"items": r["items"]})


@classes_bp.route("/<class_id>/timetable/versions", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_TT_MANAGE)
def create_timetable_version(class_id):
    r = timetable_v2.create_version(g.tenant_id, class_id, request.get_json() or {}, g.current_user.id)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["version"], status_code=201)


@classes_bp.route("/<class_id>/timetable/versions/<vid>", methods=["PATCH"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_TT_MANAGE)
def patch_timetable_version(class_id, vid):
    r = timetable_v2.update_version(g.tenant_id, class_id, vid, request.get_json() or {})
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["version"])


@classes_bp.route("/<class_id>/timetable/versions/<vid>/activate", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_TT_MANAGE)
def activate_timetable_version_route(class_id, vid):
    r = timetable_v2.activate_version(g.tenant_id, class_id, vid)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["version"])


@classes_bp.route("/<class_id>/timetable", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_any_permission(PERM_TT_READ, PERM_TT_MANAGE)
def get_class_timetable(class_id):
    vid = request.args.get("version_id")
    r = timetable_v2.list_entries_for_active_or_draft(g.tenant_id, class_id, version_id=vid)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(
        data={
            "timetable_version": r.get("timetable_version"),
            "items": r.get("items", []),
        }
    )


@classes_bp.route("/<class_id>/timetable/entries", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_TT_MANAGE)
def create_timetable_entry(class_id):
    r = timetable_v2.create_entry(g.tenant_id, class_id, request.get_json() or {})
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["entry"], status_code=201)


@classes_bp.route("/<class_id>/timetable/entries/<eid>", methods=["PATCH"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_TT_MANAGE)
def patch_timetable_entry(class_id, eid):
    r = timetable_v2.update_entry(g.tenant_id, class_id, eid, request.get_json() or {})
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["entry"])


@classes_bp.route("/<class_id>/timetable/entries/<eid>", methods=["DELETE"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_TT_MANAGE)
def delete_timetable_entry(class_id, eid):
    r = timetable_v2.delete_entry(g.tenant_id, class_id, eid)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(message=r.get("message", "OK"))


@classes_bp.route("/<class_id>/timetable/generate", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("timetable")
@require_permission(PERM_TT_MANAGE)
def generate_class_timetable(class_id):
    r = timetable_v2.generate_draft(g.tenant_id, class_id, g.current_user.id)
    if not r["success"]:
        return error_response(
            "GeneratorError",
            r.get("error", "Generation failed"),
            400,
            details={"warnings": r.get("warnings")} if r.get("warnings") else None,
        )
    return success_response(
        data={
            "timetable_version": r.get("timetable_version"),
            "entries_placed": r.get("entries_placed"),
            "total_required": r.get("total_required"),
            "warnings": r.get("warnings", []),
        },
        status_code=201,
    )
