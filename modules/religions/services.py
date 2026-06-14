"""
Religion Services

Business logic for the tenant-scoped religion master. Soft-delete aware.
"""
from shared.safe_error import safe_error

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from core.database import db
from .models import Religion


def _active(query):
    return query.filter(Religion.deleted_at.is_(None))


def _clean(value):
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v or None
    return value


def list_religions(tenant_id: str) -> List[Dict]:
    rows = (
        _active(Religion.query.filter_by(tenant_id=tenant_id))
        .order_by(Religion.name.asc())
        .all()
    )
    return [r.to_dict() for r in rows]


def get_religion(religion_id: str, tenant_id: str) -> Optional[Dict]:
    r = _active(Religion.query.filter_by(id=religion_id, tenant_id=tenant_id)).first()
    return r.to_dict() if r else None


def create_religion(data: Dict, tenant_id: str) -> Dict:
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    name = _clean(data.get("name"))
    if not name:
        return {"success": False, "error": "name is required"}

    try:
        religion = Religion(tenant_id=tenant_id, name=name)
        db.session.add(religion)
        db.session.commit()
        return {"success": True, "religion": religion.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        msg = str(getattr(e, "orig", e)).lower()
        if (
            "uq_religions_tenant_name_active" in msg
            or "uq_religions_tenant_name" in msg
            or "name" in msg
        ):
            return {"success": False, "error": "A religion with this name already exists"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}


def update_religion(religion_id: str, data: Dict, tenant_id: str) -> Dict:
    religion = _active(
        Religion.query.filter_by(id=religion_id, tenant_id=tenant_id)
    ).first()
    if not religion:
        return {"success": False, "error": "Religion not found"}

    if "name" not in data:
        return {"success": True, "religion": religion.to_dict()}

    name = _clean(data["name"])
    if not name:
        return {"success": False, "error": "name cannot be empty"}

    try:
        religion.name = name
        db.session.commit()
        return {"success": True, "religion": religion.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        msg = str(getattr(e, "orig", e)).lower()
        if (
            "uq_religions_tenant_name_active" in msg
            or "uq_religions_tenant_name" in msg
            or "name" in msg
        ):
            return {"success": False, "error": "A religion with this name already exists"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}


def delete_religion(religion_id: str, tenant_id: str) -> Dict:
    """Soft-delete: stamp deleted_at, free up the name."""
    religion = _active(
        Religion.query.filter_by(id=religion_id, tenant_id=tenant_id)
    ).first()
    if not religion:
        return {"success": False, "error": "Religion not found"}

    try:
        religion.deleted_at = datetime.utcnow()
        db.session.commit()
        return {"success": True, "message": "Religion deleted"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}
