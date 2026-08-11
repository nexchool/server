"""Shared helpers for academic backbone services."""

from __future__ import annotations

from datetime import date
from typing import Optional

from modules.classes.models import Class
from modules.teachers.models import Teacher
from core.school_time import school_today


def get_class_for_tenant(class_id: str, tenant_id: str) -> Optional[Class]:
    return Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()


def teacher_belongs_to_tenant(teacher_id: str, tenant_id: str) -> bool:
    t = Teacher.query.filter_by(id=teacher_id, tenant_id=tenant_id).first()
    return t is not None


def teacher_is_active_for_class(teacher: Teacher, cls: Class, on_date: Optional[date] = None) -> bool:
    """Teacher must match tenant, be active, and (loosely) align with class academic year dates."""
    employment = teacher.staff
    if teacher.tenant_id != cls.tenant_id or employment is None:
        return False
    # Someone can only be given a class while they still work here (ADR-005).
    if not employment.is_employed:
        return False
    d = on_date or school_today()
    if cls.start_date and d < cls.start_date:
        return False
    if cls.end_date and d > cls.end_date:
        return False
    joined_on = employment.joined_on
    if joined_on and d < joined_on:
        return False
    return True


def date_in_effective_range(
    d: date,
    effective_from: Optional[date],
    effective_to: Optional[date],
) -> bool:
    if effective_from and d < effective_from:
        return False
    if effective_to and d > effective_to:
        return False
    return True


def class_display_name(cls: Class) -> str:
    """What a school calls this class.

    Delegates to `Class.display_name`, which composes grade + section and falls
    back to the legacy `name`. Building the label here as `name-section` printed
    "None-A" for every class made by the structured form, where `name` is null
    and the grade holds the label.
    """
    return cls.display_name or ""
