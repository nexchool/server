"""
SchoolUnit Services

Business logic for SchoolUnit CRUD. Tenant-scoped, soft-delete aware.
"""

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from core.database import db
from .models import (
    SchoolUnit,
    SCHOOL_UNIT_TYPES,
    SCHOOL_UNIT_STATUSES,
    SCHOOL_UNIT_TYPE_OTHER,
    SCHOOL_UNIT_STATUS_ACTIVE,
)


def _active(query):
    return query.filter(SchoolUnit.deleted_at.is_(None))


_EDITABLE_FIELDS = (
    "name",
    "code",
    "type",
    "dise_no",
    "index_no",
    "recognition_no",
    "phone",
    "address",
    "logo_url",
    "principal_signature_url",
    "status",
)


def _clean(value):
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v or None
    return value


def list_school_units(tenant_id: str, status: Optional[str] = None) -> List[Dict]:
    q = _active(SchoolUnit.query.filter_by(tenant_id=tenant_id))
    if status:
        q = q.filter(SchoolUnit.status == status)
    return [u.to_dict() for u in q.order_by(SchoolUnit.name.asc()).all()]


def get_school_unit(unit_id: str, tenant_id: str) -> Optional[Dict]:
    u = _active(SchoolUnit.query.filter_by(id=unit_id, tenant_id=tenant_id)).first()
    return u.to_dict() if u else None


def create_school_unit(data: Dict, tenant_id: str) -> Dict:
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    name = _clean(data.get("name"))
    code = _clean(data.get("code"))
    if not name:
        return {"success": False, "error": "name is required"}
    if not code:
        return {"success": False, "error": "code is required"}

    unit_type = _clean(data.get("type")) or SCHOOL_UNIT_TYPE_OTHER
    if unit_type not in SCHOOL_UNIT_TYPES:
        return {"success": False, "error": f"type must be one of {SCHOOL_UNIT_TYPES}"}

    status = _clean(data.get("status")) or SCHOOL_UNIT_STATUS_ACTIVE
    if status not in SCHOOL_UNIT_STATUSES:
        return {"success": False, "error": f"status must be one of {SCHOOL_UNIT_STATUSES}"}

    try:
        unit = SchoolUnit(
            tenant_id=tenant_id,
            name=name,
            code=code,
            type=unit_type,
            dise_no=_clean(data.get("dise_no")),
            index_no=_clean(data.get("index_no")),
            recognition_no=_clean(data.get("recognition_no")),
            phone=_clean(data.get("phone")),
            address=_clean(data.get("address")),
            logo_url=_clean(data.get("logo_url")),
            principal_signature_url=_clean(data.get("principal_signature_url")),
            status=status,
        )
        db.session.add(unit)
        db.session.commit()
        return {"success": True, "school_unit": unit.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        msg = str(getattr(e, "orig", e)).lower()
        if (
            "uq_school_units_tenant_code_active" in msg
            or "uq_school_units_tenant_code" in msg
            or "code" in msg
        ):
            return {"success": False, "error": "A school unit with this code already exists"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def update_school_unit(unit_id: str, data: Dict, tenant_id: str) -> Dict:
    unit = _active(SchoolUnit.query.filter_by(id=unit_id, tenant_id=tenant_id)).first()
    if not unit:
        return {"success": False, "error": "School unit not found"}

    try:
        for field in _EDITABLE_FIELDS:
            if field not in data:
                continue
            value = _clean(data[field])
            if field == "type" and value not in SCHOOL_UNIT_TYPES:
                return {"success": False, "error": f"type must be one of {SCHOOL_UNIT_TYPES}"}
            if field == "status" and value not in SCHOOL_UNIT_STATUSES:
                return {"success": False, "error": f"status must be one of {SCHOOL_UNIT_STATUSES}"}
            if field in ("name", "code") and not value:
                return {"success": False, "error": f"{field} cannot be empty"}
            setattr(unit, field, value)

        db.session.commit()
        return {"success": True, "school_unit": unit.to_dict()}
    except IntegrityError as e:
        db.session.rollback()
        msg = str(getattr(e, "orig", e)).lower()
        if (
            "uq_school_units_tenant_code_active" in msg
            or "uq_school_units_tenant_code" in msg
            or "code" in msg
        ):
            return {"success": False, "error": "A school unit with this code already exists"}
        return {"success": False, "error": "Database constraint violation"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def delete_school_unit(unit_id: str, tenant_id: str) -> Dict:
    """Soft-delete: stamp deleted_at, mark inactive, free up the code."""
    unit = _active(SchoolUnit.query.filter_by(id=unit_id, tenant_id=tenant_id)).first()
    if not unit:
        return {"success": False, "error": "School unit not found"}

    from modules.classes.models import Class

    in_use = Class.query.filter_by(tenant_id=tenant_id, school_unit_id=unit_id).first()
    if in_use:
        return {
            "success": False,
            "error": "School unit is referenced by existing classes; remove or reassign them first.",
        }

    try:
        unit.deleted_at = datetime.utcnow()
        unit.status = "inactive"
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}

    try:
        from modules.school_setup.services import recompute_setup_complete
        recompute_setup_complete(tenant_id)
    except Exception:
        pass
    return {"success": True, "message": "School unit deleted"}
