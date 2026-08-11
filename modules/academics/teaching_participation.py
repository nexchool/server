"""Teaching ends when the employment it hangs off does.

Teaching is an academic participation of an employed person (ADR-005), so
when the employment ends the participation cannot outlive it — the canon
states it plainly: "Teaching participation automatically ends when active
employment ends."

The rule lives here rather than in People because it is a fact about
teaching. People announces that somebody has left; Academic decides what
that means for the classes they held. Registered in `app.py`.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict

from core.database import db


def end_teaching_for(staff, on_date: datetime.date) -> Dict[str, Any]:
    """Close the classes and subjects a departing teacher was answerable for.

    Practical, not tidy-minded: a class whose teacher has left still reads as
    staffed, so nobody is told to cover it and the gap is found by a parent.

    The Teacher row itself stays. That this person taught here is history,
    and history is not a responsibility.
    """
    from modules.academics.backbone.models import (
        ClassSubjectTeacher,
        ClassTeacherAssignment,
    )

    teacher_ids = [teaching.id for teaching in staff.teaching_participations]
    if not teacher_ids:
        return {}

    subjects = 0
    for held in ClassSubjectTeacher.query.filter(
        ClassSubjectTeacher.tenant_id == staff.tenant_id,
        ClassSubjectTeacher.teacher_id.in_(teacher_ids),
        ClassSubjectTeacher.is_active.is_(True),
    ).all():
        held.is_active = False
        held.effective_to = held.effective_to or on_date
        subjects += 1

    classes = 0
    for held in ClassTeacherAssignment.query.filter(
        ClassTeacherAssignment.tenant_id == staff.tenant_id,
        ClassTeacherAssignment.teacher_id.in_(teacher_ids),
        ClassTeacherAssignment.is_active.is_(True),
    ).all():
        held.is_active = False
        held.effective_to = held.effective_to or on_date
        classes += 1

    # The cache follows its owner (ADR-014): a class whose teacher has gone
    # has no class teacher, rather than a departed one.
    if classes:
        from modules.classes.models import Class

        Class.query.filter(
            Class.tenant_id == staff.tenant_id, Class.teacher_id.in_(teacher_ids)
        ).update({Class.teacher_id: None}, synchronize_session=False)

    if not (subjects or classes):
        return {}
    return {"teaching_ended": {"subjects": subjects, "classes": classes}}


def register() -> None:
    """Tell People to call us when somebody's employment ends."""
    from modules.people.separation import when_employment_ends

    when_employment_ends(end_teaching_for)
