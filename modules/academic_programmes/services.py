"""
AcademicProgramme Services

Business logic for AcademicProgramme CRUD. Tenant-scoped, soft-delete aware.
"""
from shared.safe_error import safe_error

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from core.database import db
from .models import (
    AcademicProgramme,
    PROGRAMME_STATUSES,
    PROGRAMME_STATUS_ACTIVE,
)


_EDITABLE_FIELDS = ("name", "board", "medium", "code", "status")


def _active(query):
    return query.filter(AcademicProgramme.deleted_at.is_(None))


def _clean(value):
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v or None
    return value


def _resolve_medium(tenant_id: str, medium_id: Optional[str], medium_name: Optional[str]):
    """Return (medium_id, medium_name) — looks up or creates a Medium row.

    The legacy `programme.medium` string is kept in sync with the linked
    Medium for one release (back-compat); on new writes both fields are set.
    """
    from modules.mediums.models import Medium

    if medium_id:
        m = Medium.query.filter_by(id=medium_id, tenant_id=tenant_id).filter(
            Medium.deleted_at.is_(None)
        ).first()
        if not m:
            return None, None, "medium_id not found for this tenant"
        return m.id, m.name, None

    if not medium_name:
        return None, None, None

    name = medium_name.strip()
    if not name:
        return None, None, None

    m = (
        Medium.query.filter(
            Medium.tenant_id == tenant_id,
            Medium.deleted_at.is_(None),
            db.func.lower(Medium.name) == name.lower(),
        ).first()
    )
    if m:
        return m.id, m.name, None

    m = Medium(tenant_id=tenant_id, name=name, is_active=True)
    db.session.add(m)
    db.session.flush()
    return m.id, m.name, None


def list_programmes(tenant_id: str, status: Optional[str] = None) -> List[Dict]:
    q = _active(AcademicProgramme.query.filter_by(tenant_id=tenant_id))
    if status:
        q = q.filter(AcademicProgramme.status == status)
    return [p.to_dict() for p in q.order_by(AcademicProgramme.name.asc()).all()]


def get_programme(programme_id: str, tenant_id: str) -> Optional[Dict]:
    p = _active(
        AcademicProgramme.query.filter_by(id=programme_id, tenant_id=tenant_id)
    ).first()
    return p.to_dict() if p else None


def create_programme(data: Dict, tenant_id: str) -> Dict:
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    name = _clean(data.get("name"))
    board = _clean(data.get("board"))
    medium = _clean(data.get("medium"))
    medium_id_in = _clean(data.get("medium_id"))
    code = _clean(data.get("code"))
    if not board:
        return {"success": False, "error": "board is required"}
    if not code:
        return {"success": False, "error": "code is required"}
    if not name:
        name = f"{board} {medium}".strip() if medium else board

    status = _clean(data.get("status")) or PROGRAMME_STATUS_ACTIVE
    if status not in PROGRAMME_STATUSES:
        return {"success": False, "error": f"status must be one of {PROGRAMME_STATUSES}"}

    medium_id, medium_canonical, m_err = _resolve_medium(tenant_id, medium_id_in, medium)
    if m_err:
        return {"success": False, "error": m_err}

    try:
        programme = AcademicProgramme(
            tenant_id=tenant_id,
            name=name,
            board=board,
            medium=medium_canonical or medium,
            medium_id=medium_id,
            code=code,
            status=status,
        )
        db.session.add(programme)
        db.session.commit()
        return {"success": True, "programme": programme.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        msg = str(getattr(e, "orig", e)).lower()
        if (
            "uq_academic_programmes_tenant_code_active" in msg
            or "uq_academic_programmes_tenant_code" in msg
            or "code" in msg
        ):
            return {"success": False, "error": "A programme with this code already exists"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}


def update_programme(programme_id: str, data: Dict, tenant_id: str) -> Dict:
    programme = _active(
        AcademicProgramme.query.filter_by(id=programme_id, tenant_id=tenant_id)
    ).first()
    if not programme:
        return {"success": False, "error": "Programme not found"}

    try:
        for field in _EDITABLE_FIELDS:
            if field not in data:
                continue
            value = _clean(data[field])
            if field == "status" and value not in PROGRAMME_STATUSES:
                return {"success": False, "error": f"status must be one of {PROGRAMME_STATUSES}"}
            if field == "medium":
                m_id, m_name, m_err = _resolve_medium(tenant_id, None, value)
                if m_err:
                    return {"success": False, "error": m_err}
                programme.medium = m_name or value
                programme.medium_id = m_id
                continue
            if field in ("name", "board", "code") and not value:
                return {"success": False, "error": f"{field} cannot be empty"}
            setattr(programme, field, value)

        if "medium_id" in data:
            m_id, m_name, m_err = _resolve_medium(
                tenant_id, _clean(data.get("medium_id")), None
            )
            if m_err:
                return {"success": False, "error": m_err}
            programme.medium_id = m_id
            if m_name:
                programme.medium = m_name

        db.session.commit()
        return {"success": True, "programme": programme.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        msg = str(getattr(e, "orig", e)).lower()
        if (
            "uq_academic_programmes_tenant_code_active" in msg
            or "uq_academic_programmes_tenant_code" in msg
            or "code" in msg
        ):
            return {"success": False, "error": "A programme with this code already exists"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}


def delete_programme(programme_id: str, tenant_id: str) -> Dict:
    """Soft-delete: stamp deleted_at, mark inactive, free up the code."""
    programme = _active(
        AcademicProgramme.query.filter_by(id=programme_id, tenant_id=tenant_id)
    ).first()
    if not programme:
        return {"success": False, "error": "Programme not found"}

    from modules.classes.models import Class

    in_use = Class.query.filter_by(tenant_id=tenant_id, programme_id=programme_id).first()
    if in_use:
        return {
            "success": False,
            "error": "Programme is referenced by existing classes; remove or reassign them first.",
        }

    try:
        programme.deleted_at = datetime.utcnow()
        programme.status = "inactive"
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}

    try:
        from modules.school_setup.services import recompute_setup_complete
        recompute_setup_complete(tenant_id)
    except Exception:
        pass
    return {"success": True, "message": "Programme deleted"}
