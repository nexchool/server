"""Apply subject offerings to all class sections sharing the same grade (standard) within an academic year."""

from __future__ import annotations

from typing import Any, Dict, List

from backend.modules.classes.models import Class

from . import class_subjects


def apply_subject_to_grade(
    tenant_id: str,
    academic_year_id: str,
    grade_level: int,
    subject_id: str,
    weekly_periods: int,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create/update class_subjects rows for every class with matching academic_year_id and grade_level.
    """
    if grade_level < 1 or grade_level > 20:
        return {"success": False, "error": "grade_level must be between 1 and 20"}

    classes: List[Class] = (
        Class.query.filter_by(tenant_id=tenant_id, academic_year_id=academic_year_id, grade_level=grade_level)
        .all()
    )
    if not classes:
        return {
            "success": False,
            "error": "No classes found for this grade. Create classes with standard (grade) set first.",
        }

    applied: List[str] = []
    skipped: List[Dict[str, Any]] = []

    payload_base = {
        "weekly_periods": weekly_periods,
        "is_mandatory": bool(data.get("is_mandatory", True)),
        "is_elective_bucket": bool(data.get("is_elective_bucket", False)),
        "academic_term_id": data.get("academic_term_id"),
        "status": (data.get("status") or "active").strip() or "active",
    }

    for cls in classes:
        body = {"subject_id": subject_id, **payload_base}
        r = class_subjects.create_offering(tenant_id, cls.id, body)
        if r.get("success"):
            applied.append(cls.id)
        else:
            err = r.get("error") or ""
            if "already assigned" in err.lower() or "already" in err.lower():
                skipped.append({"class_id": cls.id, "reason": "already_offered"})
            else:
                skipped.append({"class_id": cls.id, "error": err})

    return {
        "success": True,
        "applied_count": len(applied),
        "skipped": skipped,
        "class_ids": applied,
    }
