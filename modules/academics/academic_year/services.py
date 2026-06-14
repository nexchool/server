"""Academic year CRUD services."""
from shared.safe_error import safe_error

from datetime import date
from typing import Dict, List, Optional

from core.database import db
from core.tenant import get_tenant_id
from modules.academics.academic_year.models import AcademicYear
from modules.audit.services import log_finance_action


def find_overlapping_year(
    tenant_id: str,
    start_date: date,
    end_date: date,
    exclude_id: Optional[str] = None,
) -> Optional[AcademicYear]:
    """Return another academic year in the tenant whose range overlaps [start_date, end_date].

    Two closed ranges [a_start, a_end] and [b_start, b_end] overlap when:
        a_start <= b_end AND b_start <= a_end
    """
    q = AcademicYear.query.filter(
        AcademicYear.tenant_id == tenant_id,
        AcademicYear.start_date <= end_date,
        AcademicYear.end_date >= start_date,
    )
    if exclude_id:
        q = q.filter(AcademicYear.id != exclude_id)
    return q.first()


# Keep private alias for backward compatibility within this module.
_find_overlapping_academic_year = find_overlapping_year


def count_dependencies(tenant_id: str, year_id: str) -> Dict[str, int]:
    """Return per-table counts of records that reference this academic year.

    Tables checked (all confirmed to have both academic_year_id and tenant_id):
      - classes            (modules.classes.models.Class)
      - students           (modules.students.models.Student)
      - student_enrollments(modules.academics.backbone.models.StudentClassEnrollment)
      - terms              (modules.academics.backbone.models.AcademicTerm — filtered by deleted_at IS NULL)
      - fee_structures     (modules.finance.models.FeeStructure)
      - transport_enrollments (modules.transport.models.TransportEnrollment)
      - transport_fee_plans   (modules.transport.models.TransportFeePlan)
      - holidays           (modules.holidays.models.Holiday)
    """
    from modules.classes.models import Class
    from modules.students.models import Student
    from modules.academics.backbone.models import AcademicTerm, StudentClassEnrollment
    from modules.finance.models import FeeStructure
    from modules.transport.models import TransportEnrollment, TransportFeePlan
    from modules.holidays.models import Holiday

    counts: Dict[str, int] = {}

    counts["classes"] = (
        Class.query
        .filter_by(academic_year_id=year_id, tenant_id=tenant_id)
        .count()
    )

    counts["students"] = (
        Student.query
        .filter_by(academic_year_id=year_id, tenant_id=tenant_id)
        .count()
    )

    counts["student_enrollments"] = (
        StudentClassEnrollment.query
        .filter_by(academic_year_id=year_id, tenant_id=tenant_id)
        .count()
    )

    # AcademicTerm has a soft-delete column; only count active records.
    counts["terms"] = (
        AcademicTerm.query
        .filter(
            AcademicTerm.academic_year_id == year_id,
            AcademicTerm.tenant_id == tenant_id,
            AcademicTerm.deleted_at.is_(None),
        )
        .count()
    )

    counts["fee_structures"] = (
        FeeStructure.query
        .filter_by(academic_year_id=year_id, tenant_id=tenant_id)
        .count()
    )

    counts["transport_enrollments"] = (
        TransportEnrollment.query
        .filter_by(academic_year_id=year_id, tenant_id=tenant_id)
        .count()
    )

    counts["transport_fee_plans"] = (
        TransportFeePlan.query
        .filter_by(academic_year_id=year_id, tenant_id=tenant_id)
        .count()
    )

    counts["holidays"] = (
        Holiday.query
        .filter_by(academic_year_id=year_id, tenant_id=tenant_id)
        .count()
    )

    return counts


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

        overlap = find_overlapping_year(tenant_id, start_date, end_date)
        if overlap:
            return {
                "success": False,
                "error": (
                    f"Dates overlap with academic year \"{overlap.name}\" "
                    f"({overlap.start_date.isoformat()} – {overlap.end_date.isoformat()})."
                ),
                "overlap_year": overlap.to_dict(),
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
        return {"success": False, "error": safe_error(e)}


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

        overlap = find_overlapping_year(tenant_id, new_start, new_end, exclude_id=year_id)
        if overlap:
            return {
                "success": False,
                "error": (
                    f"Dates overlap with academic year \"{overlap.name}\" "
                    f"({overlap.start_date.isoformat()} – {overlap.end_date.isoformat()})."
                ),
                "overlap_year": overlap.to_dict(),
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
        return {"success": False, "error": safe_error(e)}


def delete_academic_year(year_id: str, user_id: Optional[str] = None) -> Dict:
    """Delete academic year after checking that no data references it.

    Returns:
        {"success": True, "message": ...} on success.
        {"success": False, "error": ..., "blocked": True, "blockers": {...}} when
        dependent records exist (caller should surface 409 to the client).
        {"success": False, "error": ...} for not-found or unexpected errors.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    ay = AcademicYear.query.filter_by(id=year_id, tenant_id=tenant_id).first()
    if not ay:
        return {"success": False, "error": "Academic year not found"}

    deps = count_dependencies(tenant_id, year_id)
    total = sum(deps.values())
    if total > 0:
        nonzero = {k: v for k, v in deps.items() if v > 0}
        labels = ", ".join(
            f"{v} {k.replace('_', ' ')}" for k, v in nonzero.items()
        )
        return {
            "success": False,
            "blocked": True,
            "blockers": deps,
            "error": (
                f"Cannot delete academic year because it has linked data: {labels}. "
                "Remove or reassign that data first."
            ),
        }

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
        return {"success": False, "error": safe_error(e)}
