"""
Class & Class-Subject bulk services.

Structured (UI-driven) bulk operations — NOT Excel imports.

- bulk_create_classes:
    Given a (school_unit, programme, academic_year) and a list of
    {grade_id, sections}, create one Class per (grade, section). Skips
    duplicates that already match the structural unique constraint
    `uq_classes_unit_programme_grade_section_year`.

- bulk_assign_subjects:
    Given a list of class_ids and a list of subject_ids, create one
    ClassSubject row per (class, subject) combination, skipping pairs
    that already exist (active, not soft-deleted).
"""
from shared.safe_error import safe_error

from typing import Any, Dict, List

from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.academic_programmes.models import AcademicProgramme
from modules.academics.academic_year.models import AcademicYear
from modules.classes.models import Class, ClassSubject
from modules.grades.models import Grade
from modules.school_units.models import SchoolUnit
from modules.subjects.models import Subject


def _normalize_section(value: Any) -> str:
    return (str(value or "")).strip()


def bulk_create_classes(payload: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """
    Structured bulk class creation.

    Input:
        {
            "school_unit_id": "...",
            "programme_id":   "...",
            "academic_year_id": "...",
            "structure": [
                {"grade_id": "...", "sections": ["A", "B"]},
                ...
            ]
        }
    """
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    school_unit_id = (payload.get("school_unit_id") or "").strip() or None
    programme_id = (payload.get("programme_id") or "").strip() or None
    academic_year_id = (payload.get("academic_year_id") or "").strip() or None
    structure = payload.get("structure") or []

    if not school_unit_id:
        return {"success": False, "error": "school_unit_id is required"}
    if not programme_id:
        return {"success": False, "error": "programme_id is required"}
    if not academic_year_id:
        return {"success": False, "error": "academic_year_id is required"}
    if not isinstance(structure, list) or not structure:
        return {"success": False, "error": "structure must be a non-empty list"}

    # Validate parent rows belong to this tenant and are not soft-deleted.
    school_unit = (
        SchoolUnit.query.filter_by(id=school_unit_id, tenant_id=tenant_id)
        .filter(SchoolUnit.deleted_at.is_(None))
        .first()
    )
    if not school_unit:
        return {"success": False, "error": "Invalid school_unit_id for this tenant"}

    programme = (
        AcademicProgramme.query.filter_by(id=programme_id, tenant_id=tenant_id)
        .filter(AcademicProgramme.deleted_at.is_(None))
        .first()
    )
    if not programme:
        return {"success": False, "error": "Invalid programme_id for this tenant"}

    if not AcademicYear.query.filter_by(id=academic_year_id, tenant_id=tenant_id).first():
        return {"success": False, "error": "Invalid academic_year_id for this tenant"}

    # Resolve all grades in one query for naming + tenant validation.
    grade_ids = []
    for entry in structure:
        gid = (entry or {}).get("grade_id")
        if not gid:
            return {"success": False, "error": "Each structure entry needs a grade_id"}
        grade_ids.append(gid)

    grades = (
        Grade.query.filter(
            Grade.tenant_id == tenant_id,
            Grade.id.in_(set(grade_ids)),
            Grade.deleted_at.is_(None),
        ).all()
    )
    grade_by_id = {g.id: g for g in grades}
    missing = [gid for gid in set(grade_ids) if gid not in grade_by_id]
    if missing:
        return {
            "success": False,
            "error": f"Invalid grade_id(s) for this tenant: {missing}",
        }

    created: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    # Single outer transaction. Each insert lives inside a SAVEPOINT so a
    # racy duplicate doesn't poison the rest of the batch — but anything
    # other than a duplicate-key error rolls the whole bulk back.
    try:
        for entry in structure:
            grade_id = entry["grade_id"]
            grade = grade_by_id[grade_id]
            sections = entry.get("sections") or []
            if not isinstance(sections, list):
                db.session.rollback()
                return {"success": False, "error": "sections must be a list of strings"}

            seen = set()
            for raw_section in sections:
                section = _normalize_section(raw_section)
                if not section:
                    continue
                key = section.lower()
                if key in seen:
                    continue
                seen.add(key)

                existing = Class.query.filter_by(
                    tenant_id=tenant_id,
                    school_unit_id=school_unit_id,
                    programme_id=programme_id,
                    grade_id=grade_id,
                    section=section,
                    academic_year_id=academic_year_id,
                ).first()
                if existing:
                    skipped.append(
                        {
                            "grade_id": grade_id,
                            "section": section,
                            "class_id": existing.id,
                            "reason": "already_exists",
                        }
                    )
                    continue

                display_name = f"{grade.name} {section}".strip()
                new_class = Class(
                    tenant_id=tenant_id,
                    name=display_name,
                    section=section,
                    academic_year_id=academic_year_id,
                    school_unit_id=school_unit_id,
                    programme_id=programme_id,
                    grade_id=grade_id,
                )
                try:
                    with db.session.begin_nested():
                        db.session.add(new_class)
                except IntegrityError as e:
                    msg = str(getattr(e, "orig", e)).lower()
                    if "uq_classes_unit_programme_grade_section_year" in msg:
                        skipped.append(
                            {
                                "grade_id": grade_id,
                                "section": section,
                                "reason": "already_exists",
                            }
                        )
                        continue
                    db.session.rollback()
                    return {
                        "success": False,
                        "error": "Database constraint violation during bulk create",
                    }
                created.append(new_class.to_dict())

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}

    try:
        from modules.school_setup.services import recompute_setup_complete
        recompute_setup_complete(tenant_id)
    except Exception:
        pass

    return {
        "success": True,
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
    }


def bulk_assign_class_subjects(payload: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """
    Structured bulk subject assignment.

    Input:
        {
            "class_ids":   ["...", "..."],
            "subject_ids": ["...", "..."],
            "weekly_periods": 1   # optional, default 1
        }

    Creates one ClassSubject per (class, subject) pair. Skips duplicates
    where an active row already exists for the (tenant, class, subject)
    combination (matches the partial unique index
    `uq_class_subjects_active_class_subject`).
    """
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    class_ids = list({c for c in (payload.get("class_ids") or []) if c})
    subject_ids = list({s for s in (payload.get("subject_ids") or []) if s})

    if not class_ids:
        return {"success": False, "error": "class_ids must be a non-empty list"}
    if not subject_ids:
        return {"success": False, "error": "subject_ids must be a non-empty list"}

    weekly_periods_raw = payload.get("weekly_periods", 1)
    try:
        weekly_periods = int(weekly_periods_raw)
    except (TypeError, ValueError):
        return {"success": False, "error": "weekly_periods must be an integer"}
    if weekly_periods <= 0:
        return {"success": False, "error": "weekly_periods must be greater than 0"}

    # Validate everything belongs to this tenant in one shot.
    classes = Class.query.filter(
        Class.tenant_id == tenant_id,
        Class.id.in_(class_ids),
    ).all()
    found_class_ids = {c.id for c in classes}
    missing_classes = [cid for cid in class_ids if cid not in found_class_ids]
    if missing_classes:
        return {
            "success": False,
            "error": f"Invalid class_id(s) for this tenant: {missing_classes}",
        }

    subjects = Subject.query.filter(
        Subject.tenant_id == tenant_id,
        Subject.id.in_(subject_ids),
        Subject.deleted_at.is_(None),
    ).all()
    found_subject_ids = {s.id for s in subjects}
    missing_subjects = [sid for sid in subject_ids if sid not in found_subject_ids]
    if missing_subjects:
        return {
            "success": False,
            "error": f"Invalid subject_id(s) for this tenant: {missing_subjects}",
        }

    # Existing active assignments — bulk-load once.
    existing_pairs = {
        (cs.class_id, cs.subject_id)
        for cs in ClassSubject.query.filter(
            ClassSubject.tenant_id == tenant_id,
            ClassSubject.class_id.in_(class_ids),
            ClassSubject.subject_id.in_(subject_ids),
            ClassSubject.deleted_at.is_(None),
            ClassSubject.status == "active",
        ).all()
    }

    created: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    try:
        for class_id in class_ids:
            for subject_id in subject_ids:
                if (class_id, subject_id) in existing_pairs:
                    skipped.append(
                        {
                            "class_id": class_id,
                            "subject_id": subject_id,
                            "reason": "already_assigned",
                        }
                    )
                    continue

                cs = ClassSubject(
                    tenant_id=tenant_id,
                    class_id=class_id,
                    subject_id=subject_id,
                    weekly_periods=weekly_periods,
                )
                try:
                    with db.session.begin_nested():
                        db.session.add(cs)
                except IntegrityError:
                    # Concurrent writer beat us to the same pair — record as skip.
                    skipped.append(
                        {
                            "class_id": class_id,
                            "subject_id": subject_id,
                            "reason": "already_assigned",
                        }
                    )
                    continue
                created.append(
                    {
                        "id": cs.id,
                        "class_id": cs.class_id,
                        "subject_id": cs.subject_id,
                        "weekly_periods": cs.weekly_periods,
                    }
                )

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": safe_error(e)}

    try:
        from modules.school_setup.services import recompute_setup_complete
        recompute_setup_complete(tenant_id)
    except Exception:
        pass

    return {
        "success": True,
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
    }
