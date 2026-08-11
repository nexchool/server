"""
Grade Services

Business logic for Grade master CRUD. Tenant-scoped, soft-delete aware.
"""
from shared.safe_error import safe_error

import re
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from core.database import db
from .models import Grade
from core.school_time import utc_now


def _active(query):
    return query.filter(Grade.deleted_at.is_(None))


def _clean(value):
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v or None
    return value


def _coerce_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def list_grades(tenant_id: str) -> List[Dict]:
    grades = (
        _active(Grade.query.filter_by(tenant_id=tenant_id))
        .order_by(Grade.sequence.asc(), Grade.name.asc())
        .all()
    )
    return [g.to_dict() for g in grades]


def get_grade(grade_id: str, tenant_id: str) -> Optional[Dict]:
    g = _active(Grade.query.filter_by(id=grade_id, tenant_id=tenant_id)).first()
    return g.to_dict() if g else None


def _infer_sequence(name: str, tenant_id: str) -> int:
    """Where a grade sits in the ladder when the caller did not say.

    `sequence` is what orders grades everywhere — their names cannot, because
    sorted as text "Std 10" comes before "Std 2". It used to default to 0 when
    absent, which put every such grade *first*; harmless while the only caller
    was a form that always sent one, and wrong the moment a grade can be
    created inline while opening a section.

    A school names its grades after the number of the year — "5", "Std 5",
    "Grade 5" — so the number in the name is the order, and that is what a
    person means by typing it. A name with no number in it is either
    pre-primary (LKG, Nursery) or something we have not seen; those go to the
    end, where they are visible and can be corrected, rather than silently
    into the middle of the ladder.
    """
    digits = re.search(r"\d+", name)
    if digits:
        return int(digits.group())

    highest = (
        db.session.query(db.func.max(Grade.sequence))
        .filter(Grade.tenant_id == tenant_id, Grade.deleted_at.is_(None))
        .scalar()
    )
    return (highest or 0) + 1


def create_grade(data: Dict, tenant_id: str) -> Dict:
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    name = _clean(data.get("name"))
    if not name:
        return {"success": False, "error": "name is required"}

    sequence = (
        _coerce_int(data["sequence"])
        if data.get("sequence") is not None and data.get("sequence") != ""
        else _infer_sequence(name, tenant_id)
    )

    try:
        grade = Grade(tenant_id=tenant_id, name=name, sequence=sequence)
        db.session.add(grade)
        db.session.commit()
        return {"success": True, "grade": grade.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        msg = str(getattr(e, "orig", e)).lower()
        if (
            "uq_grades_tenant_name_active" in msg
            or "uq_grades_tenant_name" in msg
            or "name" in msg
        ):
            return {"success": False, "error": "A grade with this name already exists"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}


def update_grade(grade_id: str, data: Dict, tenant_id: str) -> Dict:
    grade = _active(Grade.query.filter_by(id=grade_id, tenant_id=tenant_id)).first()
    if not grade:
        return {"success": False, "error": "Grade not found"}

    try:
        if "name" in data:
            name = _clean(data["name"])
            if not name:
                return {"success": False, "error": "name cannot be empty"}
            grade.name = name
        if "sequence" in data:
            grade.sequence = _coerce_int(data["sequence"], default=grade.sequence)

        db.session.commit()
        return {"success": True, "grade": grade.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        msg = str(getattr(e, "orig", e)).lower()
        if (
            "uq_grades_tenant_name_active" in msg
            or "uq_grades_tenant_name" in msg
            or "name" in msg
        ):
            return {"success": False, "error": "A grade with this name already exists"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}


def delete_grade(grade_id: str, tenant_id: str) -> Dict:
    """Soft-delete: stamp deleted_at, free up the name."""
    grade = _active(Grade.query.filter_by(id=grade_id, tenant_id=tenant_id)).first()
    if not grade:
        return {"success": False, "error": "Grade not found"}

    from modules.classes.models import Class

    in_use = Class.query.filter_by(tenant_id=tenant_id, grade_id=grade_id).first()
    if in_use:
        return {
            "success": False,
            "error": "Grade is referenced by existing classes; remove or reassign them first.",
        }

    try:
        grade.deleted_at = utc_now()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}

    try:
        from modules.school_setup.services import recompute_setup_complete
        recompute_setup_complete(tenant_id)
    except Exception:
        pass
    return {"success": True, "message": "Grade deleted"}
