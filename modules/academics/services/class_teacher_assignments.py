"""Authoritative class teacher assignments — class_teacher_assignments."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from backend.core.database import db
from backend.modules.academics.backbone.models import ClassTeacherAssignment
from backend.modules.teachers.models import Teacher

from .common import get_class_for_tenant, teacher_is_active_for_class


def _serialize(row: ClassTeacherAssignment) -> Dict[str, Any]:
    t = row.teacher
    return {
        "id": row.id,
        "class_id": row.class_id,
        "teacher_id": row.teacher_id,
        "teacher_name": t.user.name if t and t.user else None,
        "employee_id": t.employee_id if t else None,
        "role": row.role,
        "allow_attendance_marking": row.allow_attendance_marking,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _parse_date(val: Any) -> Optional[date]:
    if val is None or val == "":
        return None
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val)[:10])


def _deactivate_other_primary(tenant_id: str, class_id: str, exclude_id: Optional[str]) -> None:
    q = ClassTeacherAssignment.query.filter(
        ClassTeacherAssignment.tenant_id == tenant_id,
        ClassTeacherAssignment.class_id == class_id,
        ClassTeacherAssignment.role == "primary",
        ClassTeacherAssignment.is_active.is_(True),
        ClassTeacherAssignment.deleted_at.is_(None),
    )
    if exclude_id:
        q = q.filter(ClassTeacherAssignment.id != exclude_id)
    for r in q.all():
        r.is_active = False
        r.updated_at = datetime.now(timezone.utc)


def list_for_class(tenant_id: str, class_id: str) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}
    rows = (
        ClassTeacherAssignment.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .filter(ClassTeacherAssignment.deleted_at.is_(None))
        .order_by(ClassTeacherAssignment.role, ClassTeacherAssignment.id)
        .all()
    )
    return {"success": True, "items": [_serialize(r) for r in rows]}


def create_assignment(
    tenant_id: str, class_id: str, data: Dict[str, Any], user_id: Optional[str] = None
) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    teacher_id = data.get("teacher_id")
    if not teacher_id:
        return {"success": False, "error": "teacher_id is required"}

    teacher = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
    if not teacher:
        return {"success": False, "error": "Teacher not found"}
    if not teacher_is_active_for_class(teacher, cls):
        return {"success": False, "error": "Teacher is not active for this class academic year"}

    role = (data.get("role") or "primary").strip()
    if role not in ("primary", "assistant"):
        return {"success": False, "error": "role must be primary or assistant"}

    eff_from = _parse_date(data.get("effective_from"))
    eff_to = _parse_date(data.get("effective_to"))
    if eff_from and eff_to and eff_from > eff_to:
        return {"success": False, "error": "effective_from must be before effective_to"}

    allow = bool(data.get("allow_attendance_marking", role == "primary"))
    if role != "primary":
        allow = bool(data.get("allow_attendance_marking", False))

    is_active = bool(data.get("is_active", True))

    if role == "primary" and is_active:
        _deactivate_other_primary(tenant_id, class_id, exclude_id=None)

    row = ClassTeacherAssignment(
        tenant_id=tenant_id,
        class_id=class_id,
        teacher_id=teacher_id,
        role=role,
        allow_attendance_marking=allow,
        effective_from=eff_from,
        effective_to=eff_to,
        is_active=is_active,
        created_by=user_id,
        updated_by=user_id,
    )
    db.session.add(row)
    db.session.commit()
    return {"success": True, "assignment": _serialize(row)}


def update_assignment(
    tenant_id: str,
    class_id: str,
    assignment_id: str,
    data: Dict[str, Any],
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    row = ClassTeacherAssignment.query.filter_by(
        id=assignment_id, tenant_id=tenant_id, class_id=class_id
    ).filter(ClassTeacherAssignment.deleted_at.is_(None)).first()
    if not row:
        return {"success": False, "error": "Assignment not found"}

    if "teacher_id" in data and data["teacher_id"]:
        teacher = Teacher.query.filter_by(id=data["teacher_id"], tenant_id=tenant_id).first()
        if not teacher:
            return {"success": False, "error": "Teacher not found"}
        if not teacher_is_active_for_class(teacher, cls):
            return {"success": False, "error": "Teacher is not active for this class academic year"}
        row.teacher_id = data["teacher_id"]

    if "role" in data and data["role"]:
        role = str(data["role"]).strip()
        if role not in ("primary", "assistant"):
            return {"success": False, "error": "invalid role"}
        row.role = role

    if "allow_attendance_marking" in data:
        row.allow_attendance_marking = bool(data["allow_attendance_marking"])

    if "effective_from" in data:
        row.effective_from = _parse_date(data.get("effective_from"))
    if "effective_to" in data:
        row.effective_to = _parse_date(data.get("effective_to"))

    if row.effective_from and row.effective_to and row.effective_from > row.effective_to:
        return {"success": False, "error": "effective_from must be before effective_to"}

    if "is_active" in data:
        row.is_active = bool(data["is_active"])

    if row.role == "primary" and row.is_active:
        _deactivate_other_primary(tenant_id, class_id, exclude_id=row.id)

    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return {"success": True, "assignment": _serialize(row)}


def delete_assignment(tenant_id: str, class_id: str, assignment_id: str) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    row = ClassTeacherAssignment.query.filter_by(
        id=assignment_id, tenant_id=tenant_id, class_id=class_id
    ).filter(ClassTeacherAssignment.deleted_at.is_(None)).first()
    if not row:
        return {"success": False, "error": "Assignment not found"}

    row.is_active = False
    row.deleted_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return {"success": True, "message": "Assignment removed"}
