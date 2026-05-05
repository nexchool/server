"""Medium CRUD services. Tenant-scoped."""

from __future__ import annotations

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
        return {"success": False, "error": str(e.orig) if hasattr(e, "orig") else str(e)}


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
        return {"success": False, "error": str(e.orig) if hasattr(e, "orig") else str(e)}


def delete_medium(medium_id: str, tenant_id: str) -> Dict[str, Any]:
    m = Medium.query.filter_by(id=medium_id, tenant_id=tenant_id).first()
    if not m or m.deleted_at is not None:
        return {"success": False, "error": "Medium not found"}
    m.deleted_at = datetime.now(timezone.utc)
    m.is_active = False
    db.session.commit()
    return {"success": True}
