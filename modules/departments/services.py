"""Department services — all operations tenant-scoped.

Count subqueries here MUST carry their own tenant_id predicate. The
`with_loader_criteria` tenant scope installed in core/database.py applies to
entity loads, not to column-level subqueries, so an unscoped count would leak
another tenant's totals into this tenant's list.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

# teachers.models has no exported status constant to import; mirrored here
# rather than reaching into the module's internals for a bare string.
_TEACHER_STATUS_ACTIVE = "active"

_DUPLICATE_ENTRY_PGCODE = "23505"

# Public (no leading underscore): routes.py imports this rather than copying
# the text, so the 500-vs-400 status mapping in `_error_status` can never
# silently drift from the message actually returned below.
INTEGRITY_FALLBACK_ERROR = (
    "Could not save the department because it conflicts with existing data."
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


def _handle_integrity_error(error: IntegrityError) -> Dict:
    """Discriminate duplicate-key violations from everything else.

    Only a unique-violation (Postgres 23505 — the department name/code
    partial unique indexes) is safe to report back as "already exists". Any
    other integrity error (FK violation on created_by/updated_by, a check
    constraint on status/type, etc.) is an operator-facing bug, not a user
    mistake — log it with the original cause and return a generic message
    rather than misreporting it as a duplicate.
    """
    pgcode = getattr(getattr(error, "orig", None), "pgcode", None)
    if pgcode == _DUPLICATE_ENTRY_PGCODE:
        return {"success": False, "error": "A department with this name or code already exists"}
    logger.exception(
        "department service: IntegrityError orig=%r",
        getattr(error, "orig", None),
    )
    return {"success": False, "error": INTEGRITY_FALLBACK_ERROR}


def _counts_for(tenant_id: str, department_ids: list) -> Dict[str, Dict[str, int]]:
    """Return {department_id: {"teachers": n, "classes": n}} in two grouped queries.

    Both subqueries filter on tenant_id explicitly — see the module docstring.
    Teacher counts only include active teachers: a departed staff member
    should not permanently block deleting a department, nor inflate the
    "assigned" figure a principal reads as current headcount.
    """
    counts = {did: {"teachers": 0, "classes": 0} for did in department_ids}
    if not department_ids:
        return counts

    from modules.classes.models import Class
    from modules.teachers.models import Teacher

    from modules.people.employment import EMPLOYED_STATUSES, Staff

    # Which department someone belongs to, and whether they still work here,
    # are both the employment's answers now.
    teacher_rows = (
        db.session.query(Staff.department_id, func.count(Teacher.id))
        .select_from(Teacher)
        .join(Staff, Teacher.staff_id == Staff.id)
        .filter(
            Teacher.tenant_id == tenant_id,
            Staff.department_id.in_(department_ids),
            Staff.employment_status.in_(EMPLOYED_STATUSES),
        )
        .group_by(Staff.department_id)
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
    except IntegrityError as e:
        db.session.rollback()
        return _handle_integrity_error(e)

    # A newly created department genuinely has zero teachers/classes — no
    # need for a _counts_for round trip here.
    return {"success": True, "department": department.to_dict()}


def update_department(
    department_id: str, data: Dict, tenant_id: str, user_id: Optional[str] = None
) -> Dict:
    """Update a department.

    Every field is validated before anything is assigned to `department`.
    This matters beyond readability: `_name_taken`/`_code_taken` issue a
    SELECT, and SQLAlchemy autoflushes pending changes before running any
    query on the same session — so if the name were assigned before the
    code check ran, a later rejection (e.g. an invalid status) would still
    leave the rejected rename flushed to the open transaction, ready to be
    committed by an unrelated later call. Validating into a plain dict
    first and only calling `setattr` once everything has passed avoids
    that entirely. Each failure path also rolls back defensively, matching
    modules/classes/services.py and modules/teachers/services.py.
    """
    department = _base_query(tenant_id).filter(Department.id == department_id).first()
    if not department:
        return {"success": False, "error": "Department not found"}

    updates: Dict = {}

    if "name" in data:
        name = _clean(data.get("name"))
        if not name:
            db.session.rollback()
            return {"success": False, "error": "name is required"}
        if len(name) > NAME_MAX_LENGTH:
            db.session.rollback()
            return {"success": False, "error": f"name must be at most {NAME_MAX_LENGTH} characters"}
        if _name_taken(tenant_id, name, exclude_id=department_id):
            db.session.rollback()
            return {"success": False, "error": "A department with this name already exists"}
        updates["name"] = name

    if "code" in data:
        code = _clean(data.get("code"))
        if code:
            if len(code) > CODE_MAX_LENGTH:
                db.session.rollback()
                return {"success": False, "error": f"code must be at most {CODE_MAX_LENGTH} characters"}
            if _code_taken(tenant_id, code, exclude_id=department_id):
                db.session.rollback()
                return {"success": False, "error": "A department with this code already exists"}
        updates["code"] = code

    if "description" in data:
        updates["description"] = _clean(data.get("description"))

    if "display_order" in data:
        try:
            updates["display_order"] = int(data.get("display_order") or 0)
        except (TypeError, ValueError):
            db.session.rollback()
            return {"success": False, "error": "display_order must be an integer"}

    if "status" in data:
        status = _clean(data.get("status"))
        if status not in DEPARTMENT_STATUSES:
            db.session.rollback()
            return {"success": False, "error": f"status must be one of: {', '.join(DEPARTMENT_STATUSES)}"}
        updates["status"] = status

    for field, value in updates.items():
        setattr(department, field, value)
    department.updated_by = user_id

    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        return _handle_integrity_error(e)

    counts = _counts_for(tenant_id, [department.id])[department.id]
    return {
        "success": True,
        "department": department.to_dict(
            teacher_count=counts["teachers"], class_count=counts["classes"]
        ),
    }


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
            or_(
                Department.name.ilike(pattern),
                Department.code.ilike(pattern),
                Department.description.ilike(pattern),
            )
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
    """Soft delete. Blocked while any *active* teacher or class still references it."""
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

    # _counts_for only counts *active* teachers (see its note), so an inactive
    # teacher can still hold this department_id even though the guard above
    # passed. The deletion itself is soft (deleted_at), so ON DELETE RESTRICT
    # never fires and that FK would otherwise dangle at a row no listing shows
    # — clear it in the same transaction as the soft delete.
    from modules.teachers.models import Teacher

    from modules.people.employment import Staff

    Staff.query.filter(
        Staff.tenant_id == tenant_id, Staff.department_id == department_id
    ).update({Staff.department_id: None}, synchronize_session=False)

    department.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    return {"success": True}


def resolve_department_name(name: str, tenant_id: str) -> Optional[str]:
    """Return the department id for a case-insensitive name match, or None.

    Used by the legacy free-text write paths (mobile teacher form, bulk import).
    Deliberately does not create missing departments — silently inventing them
    would rebuild the uncontrolled vocabulary this module exists to replace.
    """
    cleaned = _clean(name)
    if not cleaned:
        return None
    row = (
        _base_query(tenant_id)
        .filter(func.lower(Department.name) == cleaned.lower())
        .first()
    )
    return row.id if row else None


def list_active_departments(tenant_id: str) -> list:
    """[{id, name}] in display order — for filter facets and dropdowns."""
    rows = (
        _base_query(tenant_id)
        .filter(Department.status == DEPARTMENT_STATUS_ACTIVE)
        .order_by(Department.display_order.asc(), Department.name.asc())
        .all()
    )
    return [{"id": row.id, "name": row.name} for row in rows]


def get_department_stats(tenant_id: str) -> Dict:
    from modules.classes.models import Class
    from modules.teachers.models import Teacher

    total = _base_query(tenant_id).count()
    active = _base_query(tenant_id).filter(
        Department.status == DEPARTMENT_STATUS_ACTIVE
    ).count()

    # Active teachers only — see the note in _counts_for.
    from modules.people.employment import EMPLOYED_STATUSES, Staff

    teachers_assigned = (
        db.session.query(func.count(Teacher.id))
        .select_from(Teacher)
        .join(Staff, Teacher.staff_id == Staff.id)
        .filter(
            Teacher.tenant_id == tenant_id,
            Staff.department_id.isnot(None),
            Staff.employment_status.in_(EMPLOYED_STATUSES),
        )
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
