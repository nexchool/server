"""
Duplicate Structure Service

Two modes, both idempotent:
  - "unit_to_unit"   — copies (grade, section) class structure from a source
                       school_unit into a target school_unit, scoped to one
                       (programme, academic_year). Existing classes for the
                       target are skipped via the structural unique index.
  - "programme_to_programme" — copies subject_contexts from a source
                       programme into a target programme. Existing contexts
                       (matched on subject + medium + role) are skipped.

Each row insert is wrapped in a savepoint so a single duplicate doesn't
poison the batch (mirrors `bulk_create_classes`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.academic_programmes.models import AcademicProgramme
from modules.academics.academic_year.models import AcademicYear
from modules.classes.models import Class
from modules.school_units.models import SchoolUnit
from modules.subject_contexts.models import SubjectContext


def _validate_unit(tenant_id: str, unit_id: str) -> Optional[SchoolUnit]:
    return (
        SchoolUnit.query.filter_by(id=unit_id, tenant_id=tenant_id)
        .filter(SchoolUnit.deleted_at.is_(None))
        .first()
    )


def _validate_programme(tenant_id: str, programme_id: str) -> Optional[AcademicProgramme]:
    return (
        AcademicProgramme.query.filter_by(id=programme_id, tenant_id=tenant_id)
        .filter(AcademicProgramme.deleted_at.is_(None))
        .first()
    )


def duplicate_unit_to_unit(
    tenant_id: str, payload: Dict[str, Any], dry_run: bool = False
) -> Dict[str, Any]:
    source_id = (payload.get("source_unit_id") or "").strip() or None
    target_id = (payload.get("target_unit_id") or "").strip() or None
    programme_id = (payload.get("programme_id") or "").strip() or None
    academic_year_id = (payload.get("academic_year_id") or "").strip() or None

    if not (source_id and target_id):
        return {"success": False, "error": "source_unit_id and target_unit_id are required"}
    if source_id == target_id:
        return {"success": False, "error": "source and target unit must differ"}
    if not academic_year_id:
        return {"success": False, "error": "academic_year_id is required"}

    if not _validate_unit(tenant_id, source_id):
        return {"success": False, "error": "Invalid source_unit_id for this tenant"}
    if not _validate_unit(tenant_id, target_id):
        return {"success": False, "error": "Invalid target_unit_id for this tenant"}
    if programme_id and not _validate_programme(tenant_id, programme_id):
        return {"success": False, "error": "Invalid programme_id for this tenant"}
    if not AcademicYear.query.filter_by(id=academic_year_id, tenant_id=tenant_id).first():
        return {"success": False, "error": "Invalid academic_year_id for this tenant"}

    src_q = Class.query.filter_by(
        tenant_id=tenant_id,
        school_unit_id=source_id,
        academic_year_id=academic_year_id,
    )
    if programme_id:
        src_q = src_q.filter_by(programme_id=programme_id)
    sources = src_q.all()
    if not sources:
        return {
            "success": True,
            "created": [],
            "skipped": [],
            "created_count": 0,
            "skipped_count": 0,
            "message": "No source classes to copy.",
        }

    created: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    try:
        for src in sources:
            existing = Class.query.filter_by(
                tenant_id=tenant_id,
                school_unit_id=target_id,
                programme_id=src.programme_id,
                grade_id=src.grade_id,
                section=src.section,
                academic_year_id=academic_year_id,
            ).first()
            if existing:
                skipped.append(
                    {
                        "grade_id": src.grade_id,
                        "section": src.section,
                        "programme_id": src.programme_id,
                        "class_id": existing.id,
                        "reason": "already_exists",
                    }
                )
                continue

            new_cls = Class(
                tenant_id=tenant_id,
                name=src.name,
                section=src.section,
                academic_year_id=academic_year_id,
                school_unit_id=target_id,
                programme_id=src.programme_id,
                grade_id=src.grade_id,
            )
            try:
                with db.session.begin_nested():
                    db.session.add(new_cls)
            except IntegrityError as e:
                msg = str(getattr(e, "orig", e)).lower()
                if "uq_classes_unit_programme_grade_section_year" in msg:
                    skipped.append(
                        {
                            "grade_id": src.grade_id,
                            "section": src.section,
                            "programme_id": src.programme_id,
                            "reason": "already_exists",
                        }
                    )
                    continue
                db.session.rollback()
                return {"success": False, "error": "Database constraint violation during duplicate"}

            created.append(
                {
                    "id": new_cls.id,
                    "school_unit_id": target_id,
                    "programme_id": src.programme_id,
                    "grade_id": src.grade_id,
                    "section": src.section,
                }
            )

        if dry_run:
            db.session.rollback()
            return {
                "success": True,
                "dry_run": True,
                "would_create_count": len(created),
                "would_skip_count": len(skipped),
                "preview": created[:20],
                "message": (
                    f"Dry run: would create {len(created)}, "
                    f"skip {len(skipped)}."
                ),
            }

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
    }


def duplicate_programme_to_programme(
    tenant_id: str, payload: Dict[str, Any], dry_run: bool = False
) -> Dict[str, Any]:
    source_id = (payload.get("source_programme_id") or "").strip() or None
    target_id = (payload.get("target_programme_id") or "").strip() or None
    grade_ids: Optional[List[str]] = payload.get("grade_ids")

    if not (source_id and target_id):
        return {
            "success": False,
            "error": "source_programme_id and target_programme_id are required",
        }
    if source_id == target_id:
        return {"success": False, "error": "source and target programme must differ"}

    if not _validate_programme(tenant_id, source_id):
        return {"success": False, "error": "Invalid source_programme_id for this tenant"}
    if not _validate_programme(tenant_id, target_id):
        return {"success": False, "error": "Invalid target_programme_id for this tenant"}

    src_q = SubjectContext.query.filter(
        SubjectContext.tenant_id == tenant_id,
        SubjectContext.programme_id == source_id,
        SubjectContext.deleted_at.is_(None),
        SubjectContext.is_active.is_(True),
    )
    if grade_ids:
        src_q = src_q.filter(SubjectContext.grade_id.in_(list(set(grade_ids))))
    sources = src_q.all()
    if not sources:
        return {
            "success": True,
            "created": [],
            "skipped": [],
            "created_count": 0,
            "skipped_count": 0,
            "message": "No source contexts to copy.",
        }

    existing_keys = set(
        db.session.query(
            SubjectContext.grade_id,
            SubjectContext.subject_id,
            SubjectContext.medium_id,
            SubjectContext.role,
        )
        .filter(
            SubjectContext.tenant_id == tenant_id,
            SubjectContext.programme_id == target_id,
            SubjectContext.deleted_at.is_(None),
        )
        .all()
    )

    created: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    try:
        for ctx in sources:
            key = (ctx.grade_id, ctx.subject_id, ctx.medium_id, ctx.role)
            if key in existing_keys:
                skipped.append(
                    {
                        "grade_id": ctx.grade_id,
                        "subject_id": ctx.subject_id,
                        "reason": "already_exists",
                    }
                )
                continue

            new_ctx = SubjectContext(
                tenant_id=tenant_id,
                programme_id=target_id,
                grade_id=ctx.grade_id,
                subject_id=ctx.subject_id,
                display_name=ctx.display_name,
                short_code=ctx.short_code,
                type=ctx.type,
                role=ctx.role,
                medium_id=ctx.medium_id,
                elective_group_key=ctx.elective_group_key,
                default_weekly_periods=ctx.default_weekly_periods,
                sort_order=ctx.sort_order,
                is_active=True,
            )
            try:
                with db.session.begin_nested():
                    db.session.add(new_ctx)
            except IntegrityError as e:
                msg = str(getattr(e, "orig", e)).lower()
                if "uq_subject_contexts_offering_active" in msg:
                    skipped.append(
                        {
                            "grade_id": ctx.grade_id,
                            "subject_id": ctx.subject_id,
                            "reason": "already_exists",
                        }
                    )
                    continue
                db.session.rollback()
                return {"success": False, "error": "Database constraint violation during duplicate"}

            existing_keys.add(key)
            created.append(
                {
                    "id": new_ctx.id,
                    "grade_id": ctx.grade_id,
                    "subject_id": ctx.subject_id,
                }
            )

        if dry_run:
            db.session.rollback()
            return {
                "success": True,
                "dry_run": True,
                "would_create_count": len(created),
                "would_skip_count": len(skipped),
                "preview": created[:20],
                "message": (
                    f"Dry run: would create {len(created)}, "
                    f"skip {len(skipped)}."
                ),
            }

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
    }


def duplicate_structure(tenant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}
    mode = (payload.get("mode") or "").strip()
    dry_run: bool = bool(payload.get("dry_run", False))
    if mode == "unit_to_unit":
        result = duplicate_unit_to_unit(tenant_id, payload, dry_run=dry_run)
    elif mode == "programme_to_programme":
        result = duplicate_programme_to_programme(tenant_id, payload, dry_run=dry_run)
    else:
        return {
            "success": False,
            "error": "mode must be 'unit_to_unit' or 'programme_to_programme'",
        }

    if result.get("success"):
        try:
            from .services import recompute_setup_complete
            recompute_setup_complete(tenant_id)
        except Exception:
            pass
    return result
