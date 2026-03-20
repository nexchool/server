"""Academic year CRUD services."""

from datetime import date
from typing import Dict, List, Optional

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.modules.academics.academic_year.models import AcademicYear
from backend.modules.audit.services import log_finance_action


def list_academic_years(active_only: bool = False) -> List[Dict]:
    """List academic years for current tenant."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []

    query = AcademicYear.query.filter_by(tenant_id=tenant_id)
    if active_only:
        query = query.filter_by(is_active=True)
    query = query.order_by(AcademicYear.start_date.desc())
    return [ay.to_dict() for ay in query.all()]


def get_academic_year(year_id: str) -> Optional[Dict]:
    """Get academic year by ID."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None

    ay = AcademicYear.query.filter_by(id=year_id, tenant_id=tenant_id).first()
    return ay.to_dict() if ay else None


def create_academic_year(
    name: str,
    start_date: date | str,
    end_date: date | str,
    is_active: bool = True,
    user_id: Optional[str] = None,
) -> Dict:
    """Create academic year."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    try:
        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)

        if start_date >= end_date:
            return {"success": False, "error": "start_date must be before end_date"}

        existing = AcademicYear.query.filter_by(name=name, tenant_id=tenant_id).first()
        if existing:
            return {"success": False, "error": "Academic year with this name already exists"}

        ay = AcademicYear(
            tenant_id=tenant_id,
            name=name,
            start_date=start_date,
            end_date=end_date,
            is_active=is_active,
        )
        db.session.add(ay)
        db.session.commit()

        log_finance_action(
            action="finance.academic_year.created",
            tenant_id=tenant_id,
            user_id=user_id,
            extra_data={"academic_year_id": ay.id, "name": name},
        )
        return {"success": True, "academic_year": ay.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def update_academic_year(
    year_id: str,
    name: Optional[str] = None,
    start_date: Optional[date | str] = None,
    end_date: Optional[date | str] = None,
    is_active: Optional[bool] = None,
    user_id: Optional[str] = None,
) -> Dict:
    """Update academic year."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    ay = AcademicYear.query.filter_by(id=year_id, tenant_id=tenant_id).first()
    if not ay:
        return {"success": False, "error": "Academic year not found"}

    try:
        if name is not None:
            ay.name = name
        if start_date is not None:
            ay.start_date = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        if end_date is not None:
            ay.end_date = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
        if is_active is not None:
            ay.is_active = is_active

        if ay.start_date >= ay.end_date:
            return {"success": False, "error": "start_date must be before end_date"}

        db.session.commit()
        log_finance_action(
            action="finance.academic_year.updated",
            tenant_id=tenant_id,
            user_id=user_id,
            extra_data={"academic_year_id": year_id},
        )
        return {"success": True, "academic_year": ay.to_dict()}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def delete_academic_year(year_id: str, user_id: Optional[str] = None) -> Dict:
    """Delete academic year."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    ay = AcademicYear.query.filter_by(id=year_id, tenant_id=tenant_id).first()
    if not ay:
        return {"success": False, "error": "Academic year not found"}

    try:
        db.session.delete(ay)
        db.session.commit()
        log_finance_action(
            action="finance.academic_year.deleted",
            tenant_id=tenant_id,
            user_id=user_id,
            extra_data={"academic_year_id": year_id},
        )
        return {"success": True, "message": "Academic year deleted"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
