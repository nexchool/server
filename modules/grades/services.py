"""
Grade Services

Business logic for Grade master CRUD. Tenant-scoped, soft-delete aware.
"""
from shared.safe_error import safe_error

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from core.database import db
from .models import Grade


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


def create_grade(data: Dict, tenant_id: str) -> Dict:
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    name = _clean(data.get("name"))
    if not name:
        return {"success": False, "error": "name is required"}

    sequence = _coerce_int(data.get("sequence"), default=0)

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
        grade.deleted_at = datetime.utcnow()
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
