"""
Academic Year Promotion Service

Clones every (school_unit, programme, grade, section) class from a source
academic year into a target academic year. Subject offerings are programme+
grade keyed (subject_contexts), so they carry across years implicitly — this
function only deals with classes. Optional flag `apply_subjects=True` will
also seed class_subjects rows for the new classes from the per-grade
subject_contexts (re-using subject_contexts.apply_for_grade semantics:
idempotent, never overwrites existing user-tuned weekly_periods).
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.academics.academic_year.models import AcademicYear
from modules.classes.models import Class


def promote_year(tenant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    source_id = (payload.get("source_year_id") or "").strip() or None
    target_id = (payload.get("target_year_id") or "").strip() or None
    apply_subjects = bool(payload.get("apply_subjects", False))

    if not (source_id and target_id):
        return {"success": False, "error": "source_year_id and target_year_id are required"}
    if source_id == target_id:
        return {"success": False, "error": "source and target year must differ"}

    if not AcademicYear.query.filter_by(id=source_id, tenant_id=tenant_id).first():
        return {"success": False, "error": "Invalid source_year_id for this tenant"}
    if not AcademicYear.query.filter_by(id=target_id, tenant_id=tenant_id).first():
        return {"success": False, "error": "Invalid target_year_id for this tenant"}

    sources = Class.query.filter_by(
        tenant_id=tenant_id, academic_year_id=source_id
    ).all()
    if not sources:
        return {
            "success": True,
            "classes_created": 0,
            "classes_skipped": 0,
            "subject_links_created": 0,
            "message": "No classes in source year.",
        }

    created_classes: List[Class] = []
    skipped = 0

    try:
        for src in sources:
            existing = Class.query.filter_by(
                tenant_id=tenant_id,
                school_unit_id=src.school_unit_id,
                programme_id=src.programme_id,
                grade_id=src.grade_id,
                section=src.section,
                academic_year_id=target_id,
            ).first()
            if existing:
                skipped += 1
                continue

            new_cls = Class(
                tenant_id=tenant_id,
                name=src.name,
                section=src.section,
                academic_year_id=target_id,
                school_unit_id=src.school_unit_id,
                programme_id=src.programme_id,
                grade_id=src.grade_id,
            )
            try:
                with db.session.begin_nested():
                    db.session.add(new_cls)
            except IntegrityError as e:
                msg = str(getattr(e, "orig", e)).lower()
                if "uq_classes_unit_programme_grade_section_year" in msg:
                    skipped += 1
                    continue
                db.session.rollback()
                return {"success": False, "error": "Database constraint violation during promote"}
            created_classes.append(new_cls)

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}

    subject_links_created = 0
    if apply_subjects and created_classes:
        # Additive only: apply_for_grade already filters out existing
        # (class_id, subject_id) pairs via its `existing_pairs` set, so
        # re-running this never overwrites user-tuned ClassSubject rows.
        try:
            from modules.subject_contexts.services import apply_for_grade

            seen_pairs = set()
            for c in created_classes:
                if not c.programme_id or not c.grade_id:
                    continue
                key = (c.programme_id, c.grade_id)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                res = apply_for_grade(tenant_id, c.programme_id, c.grade_id)
                if res.get("success"):
                    subject_links_created += int(res.get("created_count", 0))
        except Exception:
            pass

    try:
        from .services import recompute_setup_complete
        recompute_setup_complete(tenant_id)
    except Exception:
        pass

    return {
        "success": True,
        "classes_created": len(created_classes),
        "classes_skipped": skipped,
        "subject_links_created": subject_links_created,
    }
