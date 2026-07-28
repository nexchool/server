"""Department services — all operations tenant-scoped.

Count subqueries here MUST carry their own tenant_id predicate. The
`with_loader_criteria` tenant scope installed in core/database.py applies to
entity loads, not to column-level subqueries, so an unscoped count would leak
another tenant's totals into this tenant's list.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from typing import Dict, Optional

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from core.database import db

from .models import (
    DEPARTMENT_STATUSES,
    DEPARTMENT_STATUS_ACTIVE,
    DEPARTMENT_TYPE_ACADEMIC,
    Department,
)
from .schemas import (
    CODE_MAX_LENGTH,
    DEFAULT_PER_PAGE,
    MAX_PER_PAGE,
    NAME_MAX_LENGTH,
    SORTABLE_COLUMNS,
)


def _clean(value) -> Optional[str]:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _base_query(tenant_id: str):
    return Department.query.filter(
        Department.tenant_id == tenant_id,
        Department.deleted_at.is_(None),
    )


def _name_taken(tenant_id: str, name: str, exclude_id: Optional[str] = None) -> bool:
    query = _base_query(tenant_id).filter(func.lower(Department.name) == name.lower())
    if exclude_id:
        query = query.filter(Department.id != exclude_id)
    return db.session.query(query.exists()).scalar()


def _code_taken(tenant_id: str, code: str, exclude_id: Optional[str] = None) -> bool:
    query = _base_query(tenant_id).filter(func.lower(Department.code) == code.lower())
    if exclude_id:
        query = query.filter(Department.id != exclude_id)
    return db.session.query(query.exists()).scalar()


def _counts_for(tenant_id: str, department_ids: list) -> Dict[str, Dict[str, int]]:
    """Return {department_id: {"teachers": n, "classes": n}} in two grouped queries.

    Both subqueries filter on tenant_id explicitly — see the module docstring.
    """
    counts = {did: {"teachers": 0, "classes": 0} for did in department_ids}
    if not department_ids:
        return counts

    from modules.classes.models import Class
    from modules.teachers.models import Teacher

    teacher_rows = (
        db.session.query(Teacher.department_id, func.count(Teacher.id))
        .filter(
            Teacher.tenant_id == tenant_id,
            Teacher.department_id.in_(department_ids),
        )
        .group_by(Teacher.department_id)
        .all()
    )
    for department_id, count in teacher_rows:
        counts[department_id]["teachers"] = count

    # Class has no deleted_at column (unlike ClassSubject) — rows are never
    # soft-deleted, so there is no "active" filter to apply here.
    class_rows = (
        db.session.query(Class.department_id, func.count(Class.id))
        .filter(
            Class.tenant_id == tenant_id,
            Class.department_id.in_(department_ids),
        )
        .group_by(Class.department_id)
        .all()
    )
    for department_id, count in class_rows:
        counts[department_id]["classes"] = count

    return counts


def create_department(data: Dict, tenant_id: str, user_id: Optional[str] = None) -> Dict:
    """Create a department. `type` is never taken from the client."""
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    name = _clean(data.get("name"))
    if not name:
        return {"success": False, "error": "name is required"}
    if len(name) > NAME_MAX_LENGTH:
        return {"success": False, "error": f"name must be at most {NAME_MAX_LENGTH} characters"}
    if _name_taken(tenant_id, name):
        return {"success": False, "error": "A department with this name already exists"}

    code = _clean(data.get("code"))
    if code:
        if len(code) > CODE_MAX_LENGTH:
            return {"success": False, "error": f"code must be at most {CODE_MAX_LENGTH} characters"}
        if _code_taken(tenant_id, code):
            return {"success": False, "error": "A department with this code already exists"}

    status = _clean(data.get("status")) or DEPARTMENT_STATUS_ACTIVE
    if status not in DEPARTMENT_STATUSES:
        return {"success": False, "error": f"status must be one of: {', '.join(DEPARTMENT_STATUSES)}"}

    try:
        display_order = int(data.get("display_order") or 0)
    except (TypeError, ValueError):
        return {"success": False, "error": "display_order must be an integer"}

    department = Department(
        tenant_id=tenant_id,
        name=name,
        code=code,
        description=_clean(data.get("description")),
        display_order=display_order,
        type=DEPARTMENT_TYPE_ACADEMIC,
        status=status,
        created_by=user_id,
        updated_by=user_id,
    )

    try:
        db.session.add(department)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "A department with this name or code already exists"}

    return {"success": True, "department": department.to_dict()}


def update_department(
    department_id: str, data: Dict, tenant_id: str, user_id: Optional[str] = None
) -> Dict:
    department = _base_query(tenant_id).filter(Department.id == department_id).first()
    if not department:
        return {"success": False, "error": "Department not found"}

    if "name" in data:
        name = _clean(data.get("name"))
        if not name:
            return {"success": False, "error": "name is required"}
        if len(name) > NAME_MAX_LENGTH:
            return {"success": False, "error": f"name must be at most {NAME_MAX_LENGTH} characters"}
        if _name_taken(tenant_id, name, exclude_id=department_id):
            return {"success": False, "error": "A department with this name already exists"}
        department.name = name

    if "code" in data:
        code = _clean(data.get("code"))
        if code:
            if len(code) > CODE_MAX_LENGTH:
                return {"success": False, "error": f"code must be at most {CODE_MAX_LENGTH} characters"}
            if _code_taken(tenant_id, code, exclude_id=department_id):
                return {"success": False, "error": "A department with this code already exists"}
        department.code = code

    if "description" in data:
        department.description = _clean(data.get("description"))

    if "display_order" in data:
        try:
            department.display_order = int(data.get("display_order") or 0)
        except (TypeError, ValueError):
            return {"success": False, "error": "display_order must be an integer"}

    if "status" in data:
        status = _clean(data.get("status"))
        if status not in DEPARTMENT_STATUSES:
            return {"success": False, "error": f"status must be one of: {', '.join(DEPARTMENT_STATUSES)}"}
        department.status = status

    department.updated_by = user_id

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return {"success": False, "error": "A department with this name or code already exists"}

    return {"success": True, "department": department.to_dict()}


def get_department(department_id: str, tenant_id: str) -> Optional[Dict]:
    department = _base_query(tenant_id).filter(Department.id == department_id).first()
    if not department:
        return None
    counts = _counts_for(tenant_id, [department.id])[department.id]
    return department.to_dict(
        teacher_count=counts["teachers"], class_count=counts["classes"]
    )


def list_departments(params: Dict, tenant_id: str) -> Dict:
    query = _base_query(tenant_id)

    search = _clean(params.get("search"))
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(Department.name.ilike(pattern), Department.code.ilike(pattern))
        )

    status = _clean(params.get("status"))
    if status:
        query = query.filter(Department.status == status)

    sort_by = _clean(params.get("sort_by")) or "display_order"
    if sort_by not in SORTABLE_COLUMNS:
        sort_by = "display_order"
    descending = (_clean(params.get("sort_dir")) or "asc").lower() == "desc"

    column = getattr(Department, sort_by)
    order = [column.desc() if descending else column.asc()]
    if sort_by == "display_order":
        order.append(Department.name.asc())
    query = query.order_by(*order)

    total = query.count()

    try:
        page = max(1, int(params.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(params.get("per_page") or DEFAULT_PER_PAGE)
    except (TypeError, ValueError):
        per_page = DEFAULT_PER_PAGE
    per_page = max(1, min(per_page, MAX_PER_PAGE))

    rows = query.limit(per_page).offset((page - 1) * per_page).all()
    counts = _counts_for(tenant_id, [row.id for row in rows])

    return {
        "items": [
            row.to_dict(
                teacher_count=counts[row.id]["teachers"],
                class_count=counts[row.id]["classes"],
            )
            for row in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": ceil(total / per_page) if per_page else 0,
    }


def delete_department(department_id: str, tenant_id: str) -> Dict:
    """Soft delete. Blocked while any teacher or class still references it."""
    department = _base_query(tenant_id).filter(Department.id == department_id).first()
    if not department:
        return {"success": False, "error": "Department not found"}

    counts = _counts_for(tenant_id, [department.id])[department.id]
    if counts["teachers"] or counts["classes"]:
        parts = []
        if counts["teachers"]:
            parts.append(f"{counts['teachers']} teachers")
        if counts["classes"]:
            parts.append(f"{counts['classes']} classes")
        return {
            "success": False,
            "error": (
                "Cannot delete this department because it is currently assigned to "
                f"{' and '.join(parts)}. Set it to inactive instead to hide it from "
                "new assignments."
            ),
            "in_use": {"teachers": counts["teachers"], "classes": counts["classes"]},
        }

    department.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return {"success": True}


def get_department_stats(tenant_id: str) -> Dict:
    from modules.classes.models import Class
    from modules.teachers.models import Teacher

    total = _base_query(tenant_id).count()
    active = _base_query(tenant_id).filter(
        Department.status == DEPARTMENT_STATUS_ACTIVE
    ).count()

    teachers_assigned = (
        db.session.query(func.count(Teacher.id))
        .filter(Teacher.tenant_id == tenant_id, Teacher.department_id.isnot(None))
        .scalar()
    ) or 0
    # Class has no deleted_at column — see the note in _counts_for.
    classes_assigned = (
        db.session.query(func.count(Class.id))
        .filter(
            Class.tenant_id == tenant_id,
            Class.department_id.isnot(None),
        )
        .scalar()
    ) or 0

    return {
        "total": total,
        "active": active,
        "teachers_assigned": teachers_assigned,
        "classes_assigned": classes_assigned,
    }
