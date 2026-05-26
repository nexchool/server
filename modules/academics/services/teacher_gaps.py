"""
Teacher-assignment gap summary for a given academic year.

Reports counts and a small sample of:
  - classes with no active primary class teacher;
  - active class_subjects with no primary teacher.

Used by the year-transition completion screen so the admin can see what still
needs human attention after academic-structure rollover.
"""

from __future__ import annotations

from typing import Any, Dict, List

from modules.academics.backbone.models import (
    ClassSubjectTeacher,
    ClassTeacherAssignment,
)
from modules.classes.models import Class, ClassSubject

_SAMPLE_LIMIT = 20


def summarize_teacher_gaps(tenant_id: str, academic_year_id: str) -> Dict[str, Any]:
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}
    if not academic_year_id:
        return {"success": False, "error": "academic_year_id is required"}

    classes: List[Class] = (
        Class.query.filter(
            Class.tenant_id == tenant_id,
            Class.academic_year_id == academic_year_id,
        ).all()
    )
    class_ids = [c.id for c in classes]

    # Classes with an active primary class teacher.
    classes_with_teacher = set()
    if class_ids:
        for row in (
            ClassTeacherAssignment.query.filter(
                ClassTeacherAssignment.tenant_id == tenant_id,
                ClassTeacherAssignment.class_id.in_(class_ids),
                ClassTeacherAssignment.role == "primary",
                ClassTeacherAssignment.is_active.is_(True),
                ClassTeacherAssignment.deleted_at.is_(None),
            ).all()
        ):
            classes_with_teacher.add(row.class_id)

    classes_missing_teacher = [
        {
            "class_id": c.id,
            "class_name": c.name,
            "class_section": c.section,
        }
        for c in classes
        if c.id not in classes_with_teacher
    ]

    # Active class subjects scoped to the year via class_id.
    class_subjects: List[ClassSubject] = (
        ClassSubject.query.filter(
            ClassSubject.tenant_id == tenant_id,
            ClassSubject.class_id.in_(class_ids),
            ClassSubject.status == "active",
            ClassSubject.deleted_at.is_(None),
        ).all()
        if class_ids
        else []
    )
    cs_ids = [cs.id for cs in class_subjects]

    cs_with_primary = set()
    if cs_ids:
        for row in (
            ClassSubjectTeacher.query.filter(
                ClassSubjectTeacher.tenant_id == tenant_id,
                ClassSubjectTeacher.class_subject_id.in_(cs_ids),
                ClassSubjectTeacher.role == "primary",
                ClassSubjectTeacher.is_active.is_(True),
                ClassSubjectTeacher.deleted_at.is_(None),
            ).all()
        ):
            cs_with_primary.add(row.class_subject_id)

    classes_by_id = {c.id: c for c in classes}
    subjects_missing_teacher = []
    for cs in class_subjects:
        if cs.id in cs_with_primary:
            continue
        cls = classes_by_id.get(cs.class_id)
        subjects_missing_teacher.append(
            {
                "class_subject_id": cs.id,
                "class_id": cs.class_id,
                "class_name": cls.name if cls else None,
                "class_section": cls.section if cls else None,
                "subject_id": cs.subject_id,
            }
        )

    return {
        "success": True,
        "data": {
            "academic_year_id": academic_year_id,
            "totals": {
                "classes": len(classes),
                "classes_missing_class_teacher": len(classes_missing_teacher),
                "class_subjects": len(class_subjects),
                "class_subjects_missing_primary_teacher": len(subjects_missing_teacher),
            },
            "samples": {
                "classes_missing_class_teacher": classes_missing_teacher[:_SAMPLE_LIMIT],
                "class_subjects_missing_primary_teacher": subjects_missing_teacher[:_SAMPLE_LIMIT],
            },
        },
    }
