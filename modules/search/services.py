"""Global search — aggregates scoped ILIKE queries across entities. Read-only."""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import or_

from core.database import db
from core.tenant import get_tenant_id
from modules.rbac.services import has_permission


MIN_QUERY_LEN = 2
DEFAULT_LIMIT = 5
MAX_LIMIT = 10


def _clamp_limit(limit: int) -> int:
    if limit is None:
        limit = DEFAULT_LIMIT
    return max(1, min(int(limit), MAX_LIMIT))


def _like(q: str) -> str:
    return f"%{q}%"


def global_search(user, q: str, limit: int = DEFAULT_LIMIT) -> Dict[str, List[Dict[str, Any]]]:
    q = (q or "").strip()
    if len(q) < MIN_QUERY_LEN:
        return {"students": [], "teachers": [], "classes": [], "fees": []}
    limit = _clamp_limit(limit)
    return {
        "students": _search_students(user, q, limit),
        "teachers": _search_teachers(user, q, limit),
        "classes": _search_classes(user, q, limit),
        "fees": _search_fees(user, q, limit),
    }


def _search_students(user, q: str, limit: int) -> List[Dict[str, Any]]:
    tenant_id = get_tenant_id()
    from modules.students.models import Student
    from modules.auth.models import User
    from modules.classes.models import Class

    can_all = has_permission(user.id, "student.read.all")
    can_class = has_permission(user.id, "student.read.class")
    if not (can_all or can_class):
        return []

    query = (
        db.session.query(Student, User, Class)
        .join(User, User.id == Student.user_id)
        .outerjoin(Class, Class.id == Student.class_id)
        .filter(
            Student.tenant_id == tenant_id,
            or_(User.name.ilike(_like(q)), Student.admission_number.ilike(_like(q))),
        )
    )
    if not can_all and can_class:
        class_ids_subq = (
            db.session.query(Class.id)
            .filter(Class.tenant_id == tenant_id, Class.teacher_id == user.id)
            .subquery()
        )
        query = query.filter(Student.class_id.in_(class_ids_subq))

    rows = query.limit(limit).all()
    return [
        {
            "id": student.id,
            "name": u.name if u else None,
            "admission_number": student.admission_number,
            "class_name": cls.name if cls else None,
        }
        for student, u, cls in rows
    ]


def _search_teachers(user, q: str, limit: int) -> List[Dict[str, Any]]:
    tenant_id = get_tenant_id()
    if not has_permission(user.id, "teacher.read"):
        return []
    from modules.teachers.models import Teacher
    from modules.auth.models import User

    rows = (
        db.session.query(Teacher, User)
        .join(User, User.id == Teacher.user_id)
        .filter(
            Teacher.tenant_id == tenant_id,
            or_(User.name.ilike(_like(q)), Teacher.employee_id.ilike(_like(q))),
        )
        .limit(limit)
        .all()
    )
    return [
        {"id": teacher.id, "name": u.name if u else None, "employee_id": teacher.employee_id}
        for teacher, u in rows
    ]


def _search_classes(user, q: str, limit: int) -> List[Dict[str, Any]]:
    tenant_id = get_tenant_id()
    if not has_permission(user.id, "class.read"):
        return []
    from modules.classes.models import Class

    rows = (
        db.session.query(Class)
        .filter(
            Class.tenant_id == tenant_id,
            or_(Class.name.ilike(_like(q)), Class.section.ilike(_like(q))),
        )
        .limit(limit)
        .all()
    )
    return [{"id": c.id, "name": c.name, "section": c.section} for c in rows]


def _search_fees(user, q: str, limit: int) -> List[Dict[str, Any]]:
    tenant_id = get_tenant_id()
    if not (has_permission(user.id, "fees.invoice.read") or has_permission(user.id, "finance.read")):
        return []
    from modules.fees.models import FeeInvoice
    from modules.students.models import Student
    from modules.auth.models import User

    rows = (
        db.session.query(FeeInvoice, User)
        .join(Student, Student.id == FeeInvoice.student_id)
        .join(User, User.id == Student.user_id)
        .filter(
            FeeInvoice.tenant_id == tenant_id,
            or_(FeeInvoice.invoice_number.ilike(_like(q)), User.name.ilike(_like(q))),
        )
        .limit(limit)
        .all()
    )
    return [
        {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "student_name": u.name if u else None,
            "total_amount": float(inv.total_amount) if inv.total_amount is not None else None,
            "status": inv.status,
        }
        for inv, u in rows
    ]
