"""Attendance session API (v2) — daily class sessions."""

from datetime import date

from flask import g, request

from backend.modules.attendance import attendance_bp
from backend.core.decorators import auth_required, require_any_permission, tenant_required, require_plan_feature
from backend.shared.helpers import error_response, success_response, validation_error_response

from backend.modules.rbac.services import has_permission

from . import session_services as svc

PERM_MARK = "attendance.mark"
PERM_READ_CLASS = "attendance.read.class"
PERM_READ_ALL = "attendance.read.all"
PERM_READ_SELF = "attendance.read.self"
PERM_MANAGE = "attendance.manage"


@attendance_bp.route("/eligible-classes", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("attendance")
@require_any_permission(PERM_MARK, PERM_MANAGE)
def eligible_classes():
    d = date.today()
    ds = request.args.get("date")
    if ds:
        d = date.fromisoformat(ds[:10])
    r = svc.get_eligible_classes_for_user(g.tenant_id, g.current_user.id, d)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data={"items": r["items"], "date": d.isoformat()})


@attendance_bp.route("/class/<class_id>/session", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("attendance")
@require_any_permission(PERM_MARK, PERM_READ_CLASS, PERM_READ_ALL, PERM_MANAGE)
def get_class_attendance_session(class_id):
    ds = request.args.get("date") or date.today().isoformat()
    try:
        d = date.fromisoformat(ds[:10])
    except ValueError:
        return validation_error_response("Invalid date (YYYY-MM-DD)")

    from backend.modules.classes.models import Class

    cls = Class.query.filter_by(id=class_id, tenant_id=g.tenant_id).first()
    if not cls:
        return error_response("NotFound", "Class not found", 404)

    s = svc.get_session_for_class_date(g.tenant_id, class_id, d)
    if not s:
        return success_response(data={"session": None})
    return success_response(data={"session": svc.serialize_session(s, f"{cls.name}-{cls.section}")})


@attendance_bp.route("/class/<class_id>/session", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("attendance")
@require_any_permission(PERM_MARK, PERM_MANAGE)
def create_class_attendance_session(class_id):
    body = request.get_json() or {}
    ds = body.get("session_date")
    if not ds:
        return validation_error_response("session_date is required (YYYY-MM-DD)")
    try:
        d = date.fromisoformat(str(ds)[:10])
    except ValueError:
        return validation_error_response("Invalid session_date")

    r = svc.get_or_create_session(
        g.tenant_id,
        class_id,
        d,
        g.current_user.id,
        assigned_marker_teacher_id=body.get("assigned_marker_teacher_id"),
        notes=body.get("notes"),
    )
    if not r["success"]:
        return error_response("Error", r.get("error", "Failed"), 400)
    code = 201 if r.get("created") else 200
    return success_response(data={"session": r["session"], "created": r.get("created", False)}, status_code=code)


@attendance_bp.route("/sessions/<session_id>/records", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("attendance")
@require_any_permission(PERM_MARK, PERM_MANAGE)
def post_session_records(session_id):
    body = request.get_json() or {}
    records = body.get("records") or []
    if not isinstance(records, list):
        return validation_error_response("records must be a list")

    r = svc.upsert_records(g.tenant_id, session_id, g.current_user.id, records)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r)


@attendance_bp.route("/sessions/<session_id>/finalize", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("attendance")
@require_any_permission(PERM_MARK, PERM_MANAGE)
def finalize_session(session_id):
    r = svc.finalize_session(g.tenant_id, session_id, g.current_user.id)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["session"])


@attendance_bp.route("/class/<class_id>/history", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("attendance")
@require_any_permission(PERM_READ_CLASS, PERM_READ_ALL, PERM_MANAGE)
def class_attendance_history(class_id):
    r = svc.class_history(g.tenant_id, class_id)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data={"items": r["items"]})


@attendance_bp.route("/student/<student_id>/v2", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("attendance")
@require_any_permission(PERM_READ_SELF, PERM_READ_CLASS, PERM_READ_ALL, PERM_MANAGE)
def student_attendance_v2(student_id):
    user_id = g.current_user.id
    if has_permission(user_id, PERM_READ_SELF) and not has_permission(user_id, PERM_READ_ALL):
        from backend.modules.students.models import Student

        st = Student.query.filter_by(id=student_id).first()
        if not st or st.user_id != user_id:
            if not has_permission(user_id, PERM_READ_CLASS):
                return error_response("Forbidden", "You can only view your own attendance", 403)

    month = request.args.get("month")
    r = svc.student_history_v2(g.tenant_id, student_id, month=month)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["data"])


@attendance_bp.route("/me/v2", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("attendance")
@require_any_permission(PERM_READ_SELF, PERM_MANAGE)
def my_attendance_v2():
    month = request.args.get("month")
    r = svc.me_student_attendance_v2(g.tenant_id, g.current_user.id, month=month)
    if not r["success"]:
        return error_response("Error", r["error"], 400)
    return success_response(data=r["data"])
