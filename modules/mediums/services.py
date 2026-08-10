"""Medium CRUD services. Tenant-scoped."""

from __future__ import annotations
from shared.safe_error import safe_error

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from core.database import db

from .models import Medium


def _norm_name(name: str) -> str:
    return (name or "").strip()


def list_mediums(tenant_id: str, include_inactive: bool = False) -> List[Dict[str, Any]]:
    q = Medium.query.filter(
        Medium.tenant_id == tenant_id,
        Medium.deleted_at.is_(None),
    )
    if not include_inactive:
        q = q.filter(Medium.is_active.is_(True))
    return [m.to_dict() for m in q.order_by(Medium.name.asc()).all()]


def create_medium(
    tenant_id: str,
    data: Dict[str, Any],
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}
    name = _norm_name(data.get("name", ""))
    if not name:
        return {"success": False, "error": "name is required"}

    existing = Medium.query.filter(
        Medium.tenant_id == tenant_id,
        db.func.lower(Medium.name) == name.lower(),
        Medium.deleted_at.is_(None),
    ).first()
    if existing:
        return {"success": False, "error": "A medium with this name already exists"}

    code = (data.get("code") or "").strip() or None
    try:
        m = Medium(
            tenant_id=tenant_id,
            name=name,
            code=code,
            is_active=bool(data.get("is_active", True)),
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        db.session.add(m)
        db.session.commit()
        return {"success": True, "medium": m.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}


def update_medium(
    medium_id: str,
    tenant_id: str,
    data: Dict[str, Any],
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    m = Medium.query.filter_by(id=medium_id, tenant_id=tenant_id).first()
    if not m or m.deleted_at is not None:
        return {"success": False, "error": "Medium not found"}

    if "name" in data:
        new_name = _norm_name(data.get("name", ""))
        if not new_name:
            return {"success": False, "error": "name cannot be empty"}
        if new_name.lower() != m.name.lower():
            dup = Medium.query.filter(
                Medium.tenant_id == tenant_id,
                Medium.id != medium_id,
                db.func.lower(Medium.name) == new_name.lower(),
                Medium.deleted_at.is_(None),
            ).first()
            if dup:
                return {"success": False, "error": "A medium with this name already exists"}
        m.name = new_name
    if "code" in data:
        m.code = (data.get("code") or "").strip() or None
    if "is_active" in data:
        m.is_active = bool(data["is_active"])
    m.updated_by = actor_user_id
    m.updated_at = datetime.now(timezone.utc)

    try:
        db.session.commit()
        return {"success": True, "medium": m.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}


def delete_medium(medium_id: str, tenant_id: str) -> Dict[str, Any]:
    """Soft-delete, refused while anything still names this medium.

    The other three structural catalogues — grades, programmes and campuses —
    have always counted the classes referencing them and refused. This one did
    not, so a school teaching parallel English and Gujarati sections could
    delete "Gujarati" and leave every one of those sections pointing at a
    soft-deleted row. Medium is part of a section's identity by the scale
    contract, which makes an orphan here worse than in the other three, not
    better (debt 44).

    Three things can name a medium and all three count: a class is taught in
    one, a programme is offered in one, and a subject context is defined for
    one. Checking only classes would let a programme keep a reference to
    something the school believes it has stopped teaching in.
    """
    m = Medium.query.filter_by(id=medium_id, tenant_id=tenant_id).first()
    if not m or m.deleted_at is not None:
        return {"success": False, "error": "Medium not found"}

    from modules.academic_programmes.models import AcademicProgramme
    from modules.classes.models import Class
    from modules.subject_contexts.models import SubjectContext

    for model, what in (
        (Class, "classes"),
        (AcademicProgramme, "programmes"),
        (SubjectContext, "subject contexts"),
    ):
        if model.query.filter_by(tenant_id=tenant_id, medium_id=medium_id).first():
            return {
                "success": False,
                "error": (
                    f"Medium is referenced by existing {what}; "
                    "remove or reassign them first."
                ),
            }

    m.deleted_at = datetime.now(timezone.utc)
    m.is_active = False
    db.session.commit()
    return {"success": True}
