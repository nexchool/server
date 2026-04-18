"""Academic year CRUD services."""

from datetime import date
from typing import Dict, List, Optional, Tuple

from core.database import db
from core.tenant import get_tenant_id
from modules.academics.academic_year.models import AcademicYear
from modules.audit.services import log_finance_action


def _inclusive_ranges_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """True if closed date ranges share at least one calendar day."""
    return a_start <= b_end and b_start <= a_end


def _find_overlapping_academic_year(
    tenant_id: str,
    start_date: date,
    end_date: date,
    exclude_id: Optional[str] = None,
) -> Optional[AcademicYear]:
    """Return another academic year in the tenant whose range overlaps [start_date, end_date]."""
    q = AcademicYear.query.filter_by(tenant_id=tenant_id)
    if exclude_id:
        q = q.filter(AcademicYear.id != exclude_id)
    for other in q.all():
        if _inclusive_ranges_overlap(start_date, end_date, other.start_date, other.end_date):
            return other
    return None


def _delete_blockers(tenant_id: str, year_id: str) -> Tuple[bool, str]:
    """
    Return (blocked, message) if the academic year cannot be deleted safely.
    Prefer explicit checks over relying on DB RESTRICT alone.
    """
    from modules.classes.models import Class
    from modules.finance.models import FeeStructure
    from modules.students.models import Student

    n_classes = Class.query.filter_by(academic_year_id=year_id, tenant_id=tenant_id).count()
    if n_classes:
        return True, f"Cannot delete: {n_classes} class(es) still use this academic year."

    n_fees = FeeStructure.query.filter_by(academic_year_id=year_id, tenant_id=tenant_id).count()
    if n_fees:
        return True, f"Cannot delete: {n_fees} fee structure(s) are linked to this academic year."

    n_students = Student.query.filter_by(academic_year_id=year_id, tenant_id=tenant_id).count()
    if n_students:
        return True, f"Cannot delete: {n_students} student(s) are still linked to this academic year."

    return False, ""


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

        overlap = _find_overlapping_academic_year(tenant_id, start_date, end_date)
        if overlap:
            return {
                "success": False,
                "error": (
                    f"Dates overlap with academic year “{overlap.name}” "
                    f"({overlap.start_date.isoformat()} – {overlap.end_date.isoformat()})."
                ),
            }

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
        new_name = name if name is not None else ay.name
        new_start = (
            date.fromisoformat(start_date)
            if isinstance(start_date, str)
            else start_date
            if start_date is not None
            else ay.start_date
        )
        new_end = (
            date.fromisoformat(end_date)
            if isinstance(end_date, str)
            else end_date
            if end_date is not None
            else ay.end_date
        )

        if new_name != ay.name:
            taken = (
                AcademicYear.query.filter_by(name=new_name, tenant_id=tenant_id)
                .filter(AcademicYear.id != year_id)
                .first()
            )
            if taken:
                return {"success": False, "error": "Academic year with this name already exists"}

        if new_start >= new_end:
            return {"success": False, "error": "start_date must be before end_date"}

        overlap = _find_overlapping_academic_year(tenant_id, new_start, new_end, exclude_id=year_id)
        if overlap:
            return {
                "success": False,
                "error": (
                    f"Dates overlap with academic year “{overlap.name}” "
                    f"({overlap.start_date.isoformat()} – {overlap.end_date.isoformat()})."
                ),
            }

        ay.name = new_name
        ay.start_date = new_start
        ay.end_date = new_end
        if is_active is not None:
            ay.is_active = is_active

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

    blocked, msg = _delete_blockers(tenant_id, year_id)
    if blocked:
        return {"success": False, "error": msg}

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
