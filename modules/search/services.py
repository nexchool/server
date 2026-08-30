"""Global search — aggregates scoped ILIKE queries across entities. Read-only."""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import or_

from core.database import db
from core.tenant import get_tenant_id
from modules.people.employment import Staff
from modules.people.models import Person
from core.branch_scope import (
    filter_classes_by_branch,
    filter_fees_by_branch,
    filter_students_by_branch,
    filter_teachers_by_branch,
)
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
    from modules.classes.models import Class

    can_all = has_permission(user.id, "student.read.all")
    can_class = has_permission(user.id, "student.read.class")
    if not (can_all or can_class):
        return []

    # Person-keyed (ADR-001), like the teacher search below: the account is
    # optional (migration 094) and its name is only a display copy anyway.
    query = (
        db.session.query(Student, Person, Class)
        .join(Person, Person.id == Student.person_id)
        .outerjoin(Class, Class.id == Student.class_id)
        .filter(
            Student.tenant_id == tenant_id,
            or_(
                Person.full_name.ilike(_like(q)),
                Student.admission_number.ilike(_like(q)),
            ),
        )
    )
    if not can_all and can_class:
        # The classes this user's teacher is responsible for, asked of
        # Teaching Assignment (ADR-014) — the cache names teachers, not
        # logins, since migration 095.
        from modules.academics.teaching_assignment import classes_taught_by
        from modules.teachers.models import Teacher

        teacher = Teacher.query.filter_by(
            tenant_id=tenant_id, user_id=user.id
        ).first()
        own_class_ids = (
            [a.class_id for a in classes_taught_by(teacher.id)] if teacher else []
        )
        if not own_class_ids:
            return []
        query = query.filter(Student.class_id.in_(own_class_ids))

    query = filter_students_by_branch(query)
    rows = query.limit(limit).all()
    return [
        {
            "id": student.id,
            "name": person.full_name if person else None,
            "admission_number": student.admission_number,
            "class_name": cls.name if cls else None,
        }
        for student, person, cls in rows
    ]


def _search_teachers(user, q: str, limit: int) -> List[Dict[str, Any]]:
    tenant_id = get_tenant_id()
    if not has_permission(user.id, "teacher.read"):
        return []
    from modules.teachers.models import Teacher

    query = (
        db.session.query(Teacher, Person)
        .join(Staff, Staff.id == Teacher.staff_id)
        .join(Person, Person.id == Staff.person_id)
        .filter(
            Teacher.tenant_id == tenant_id,
            or_(
                Person.full_name.ilike(_like(q)),
                Staff.employee_number.ilike(_like(q)),
            ),
        )
    )
    rows = filter_teachers_by_branch(query).limit(limit).all()
    return [
        {
            "id": teacher.id,
            "name": person.full_name if person else None,
            "employee_id": teacher.staff.employee_number if teacher.staff else None,
        }
        for teacher, person in rows
    ]


def _search_classes(user, q: str, limit: int) -> List[Dict[str, Any]]:
    tenant_id = get_tenant_id()
    if not has_permission(user.id, "class.read"):
        return []
    from modules.classes.models import Class

    query = (
        db.session.query(Class)
        .filter(
            Class.tenant_id == tenant_id,
            or_(Class.name.ilike(_like(q)), Class.section.ilike(_like(q))),
        )
    )
    rows = filter_classes_by_branch(query).limit(limit).all()
    return [{"id": c.id, "name": c.name, "section": c.section} for c in rows]


def _search_fees(user, q: str, limit: int) -> List[Dict[str, Any]]:
    tenant_id = get_tenant_id()
    if not (has_permission(user.id, "fees.invoice.read") or has_permission(user.id, "finance.read")):
        return []
    from modules.fees.models import FeeInvoice
    from modules.students.models import Student

    query = (
        db.session.query(FeeInvoice, Person)
        .join(Student, Student.id == FeeInvoice.student_id)
        .join(Person, Person.id == Student.person_id)
        .filter(
            FeeInvoice.tenant_id == tenant_id,
            or_(
                FeeInvoice.invoice_number.ilike(_like(q)),
                Person.full_name.ilike(_like(q)),
            ),
        )
    )
    rows = filter_fees_by_branch(query, FeeInvoice.student_id).limit(limit).all()
    return [
        {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "student_name": person.full_name if person else None,
            "total_amount": float(inv.total_amount) if inv.total_amount is not None else None,
            "status": inv.status,
        }
        for inv, person in rows
    ]
