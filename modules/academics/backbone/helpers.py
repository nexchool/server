"""
Read helpers for academic backbone models.

LEGACY COMPAT: classes.teacher_id and students.class_id remain populated; prefer
ClassTeacherAssignment and StudentClassEnrollment for new features.
"""

from __future__ import annotations

from typing import Optional

from modules.academics.backbone.models import ClassTeacherAssignment


def get_active_primary_class_teacher_assignment(class_id: str, tenant_id: str) -> Optional[ClassTeacherAssignment]:
    """Return the active primary class teacher assignment, if any."""
    return (
        ClassTeacherAssignment.query.filter_by(
            class_id=class_id,
            tenant_id=tenant_id,
            role="primary",
            is_active=True,
        )
        .filter(ClassTeacherAssignment.deleted_at.is_(None))
        .first()
    )
