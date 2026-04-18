"""Assign teachers to class_subject rows — class_subject_teachers."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from core.database import db
from modules.academics.backbone.models import ClassSubjectTeacher
from modules.classes.models import ClassSubject
from modules.teachers.models import Teacher

from .common import get_class_for_tenant, teacher_is_active_for_class


def _serialize(row: ClassSubjectTeacher) -> Dict[str, Any]:
    t = row.teacher
    return {
        "id": row.id,
        "class_subject_id": row.class_subject_id,
        "teacher_id": row.teacher_id,
        "teacher_name": t.user.name if t and t.user else None,
        "employee_id": t.employee_id if t else None,
        "role": row.role,
        "effective_from": row.effective_from.isoformat() if row.effective_from else None,
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _get_class_subject(tenant_id: str, class_id: str, class_subject_id: str) -> Optional[ClassSubject]:
    return ClassSubject.query.filter_by(
        id=class_subject_id, tenant_id=tenant_id, class_id=class_id
    ).filter(ClassSubject.deleted_at.is_(None)).first()


def list_for_class(tenant_id: str, class_id: str) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    cs_ids = [
        r.id
        for r in ClassSubject.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .filter(ClassSubject.deleted_at.is_(None))
        .all()
    ]
    if not cs_ids:
        return {"success": True, "items": []}

    rows = (
        ClassSubjectTeacher.query.filter(
            ClassSubjectTeacher.tenant_id == tenant_id,
            ClassSubjectTeacher.class_subject_id.in_(cs_ids),
            ClassSubjectTeacher.deleted_at.is_(None),
        )
        .order_by(ClassSubjectTeacher.class_subject_id, ClassSubjectTeacher.role)
        .all()
    )
    return {"success": True, "items": [_serialize(r) for r in rows]}


def list_assignment_candidates(tenant_id: str, class_id: str) -> Dict[str, Any]:
    """
    Active teachers in the tenant for assigning to class_subject rows.

    Not the same as "available class teachers" (homeroom / class-teacher rules).
    """
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    from modules.teachers.services import list_teachers

    items = list_teachers(search=None, status="active")
    return {"success": True, "items": items}


def create_assignment(
    tenant_id: str, class_id: str, data: Dict[str, Any], user_id: Optional[str] = None
) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    cs = _get_class_subject(tenant_id, class_id, data.get("class_subject_id"))
    if not cs:
        return {"success": False, "error": "class_subject_id not found for this class"}

    teacher_id = data.get("teacher_id")
    if not teacher_id:
        return {"success": False, "error": "teacher_id is required"}

    teacher = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
    if not teacher:
        return {"success": False, "error": "Teacher not found"}
    if not teacher_is_active_for_class(teacher, cls):
        return {"success": False, "error": "Teacher is not active for this class academic year"}

    role = (data.get("role") or "primary").strip()
    if role not in ("primary", "assistant", "guest"):
        return {"success": False, "error": "role must be primary, assistant, or guest"}

    eff_from = _parse_date(data.get("effective_from"))
    eff_to = _parse_date(data.get("effective_to"))
    if eff_from and eff_to and eff_from > eff_to:
        return {"success": False, "error": "effective_from must be before effective_to"}

    if role == "primary" and data.get("is_active", True):
        _deactivate_other_primary(tenant_id, cs.id, exclude_id=None)

    row = ClassSubjectTeacher(
        tenant_id=tenant_id,
        class_subject_id=cs.id,
        teacher_id=teacher_id,
        role=role,
        effective_from=eff_from,
        effective_to=eff_to,
        is_active=bool(data.get("is_active", True)),
        created_by=user_id,
        updated_by=user_id,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
    return {"success": True, "assignment": _serialize(row)}


def _deactivate_other_primary(tenant_id: str, class_subject_id: str, exclude_id: Optional[str]) -> None:
    q = ClassSubjectTeacher.query.filter(
        ClassSubjectTeacher.tenant_id == tenant_id,
        ClassSubjectTeacher.class_subject_id == class_subject_id,
        ClassSubjectTeacher.role == "primary",
        ClassSubjectTeacher.is_active.is_(True),
        ClassSubjectTeacher.deleted_at.is_(None),
    )
    if exclude_id:
        q = q.filter(ClassSubjectTeacher.id != exclude_id)
    for r in q.all():
        r.is_active = False
        r.updated_at = datetime.now(timezone.utc)


def _parse_date(val: Any) -> Optional[date]:
    if val is None or val == "":
        return None
    if isinstance(val, date):
        return val
    return date.fromisoformat(str(val)[:10])


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

    row = ClassSubjectTeacher.query.filter_by(
        id=assignment_id, tenant_id=tenant_id
    ).filter(ClassSubjectTeacher.deleted_at.is_(None)).first()
    if not row:
        return {"success": False, "error": "Assignment not found"}

    cs = _get_class_subject(tenant_id, class_id, row.class_subject_id)
    if not cs:
        return {"success": False, "error": "Assignment does not belong to this class"}

    if "teacher_id" in data and data["teacher_id"]:
        teacher = Teacher.query.filter_by(id=data["teacher_id"], tenant_id=tenant_id).first()
        if not teacher:
            return {"success": False, "error": "Teacher not found"}
        if not teacher_is_active_for_class(teacher, cls):
            return {"success": False, "error": "Teacher is not active for this class academic year"}
        row.teacher_id = data["teacher_id"]

    if "role" in data and data["role"]:
        role = str(data["role"]).strip()
        if role not in ("primary", "assistant", "guest"):
            return {"success": False, "error": "invalid role"}
        row.role = role

    if "effective_from" in data:
        row.effective_from = _parse_date(data.get("effective_from"))
    if "effective_to" in data:
        row.effective_to = _parse_date(data.get("effective_to"))

    if row.effective_from and row.effective_to and row.effective_from > row.effective_to:
        return {"success": False, "error": "effective_from must be before effective_to"}

    if "is_active" in data:
        row.is_active = bool(data["is_active"])

    if row.role == "primary" and row.is_active:
        _deactivate_other_primary(tenant_id, row.class_subject_id, exclude_id=row.id)

    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return {"success": True, "assignment": _serialize(row)}


def delete_assignment(tenant_id: str, class_id: str, assignment_id: str) -> Dict[str, Any]:
    cls = get_class_for_tenant(class_id, tenant_id)
    if not cls:
        return {"success": False, "error": "Class not found"}

    row = ClassSubjectTeacher.query.filter_by(
        id=assignment_id, tenant_id=tenant_id
    ).filter(ClassSubjectTeacher.deleted_at.is_(None)).first()
    if not row:
        return {"success": False, "error": "Assignment not found"}

    cs = _get_class_subject(tenant_id, class_id, row.class_subject_id)
    if not cs:
        return {"success": False, "error": "Assignment does not belong to this class"}

    row.is_active = False
    row.deleted_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return {"success": True, "message": "Assignment removed"}
