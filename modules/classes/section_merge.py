"""Two sections becoming one, without pretending the other never existed.

Schools merge sections mid-year for ordinary reasons — a grade that lost
students, a teacher who left, a decision from above. What must not happen is
the history going with them: the attendance taken in 8B, the marks awarded
there and the reports issued from it all happened in 8B, and they stay
there. The canon puts it plainly — "Historical records remain associated
with their original Sections. Only future activities use the merged
Section."

So a merge moves the children and retires the room. The absorbed section is
never deleted; it is marked with where its future went, which is both the
fact a reader needs and the flag that stops anything new being placed into
it.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from core.branch_scope import assert_class_allowed
from core.database import db
from core.school_time import school_today
from core.tenant import get_tenant_id

from .models import Class


def _section(tenant_id: str, class_id: str) -> Optional[Class]:
    return Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()


def merge_sections(
    source_class_id: str,
    into_class_id: str,
    *,
    occurred_on: Optional[datetime.date] = None,
    reason: Optional[str] = None,
    recorded_by_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Move a section's students into another, and retire it.

    Refuses across academic years: merging is a mid-year operation, and a
    move between years is promotion, which decides different things.
    """
    from modules.students.lifecycle_service import transfer_section

    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    source = _section(tenant_id, source_class_id)
    target = _section(tenant_id, into_class_id)
    if source is None or target is None:
        return {"success": False, "error": "Section not found"}
    if source.id == target.id:
        return {"success": False, "error": "A section cannot be merged into itself"}

    # A restricted sub-admin may only reorganise their own campus, and both
    # ends of a merge are a reorganisation.
    assert_class_allowed(source.id)
    assert_class_allowed(target.id)

    if source.is_merged_away:
        return {"success": False, "error": "This section has already been merged"}
    if target.is_merged_away:
        return {
            "success": False,
            "error": "That section has itself been merged; merge into the surviving one",
        }
    if source.academic_year_id != target.academic_year_id:
        return {
            "success": False,
            "error": (
                "Sections can only be merged within one academic year. Moving "
                "students between years is promotion."
            ),
        }

    when = occurred_on or school_today()

    moved: List[str] = []
    for student in _students_currently_in(tenant_id, source.id):
        outcome = transfer_section(
            student.id,
            to_class_id=target.id,
            occurred_on=when,
            reason=reason or f"Section merged into {target.section}",
            recorded_by_user_id=recorded_by_user_id,
        )
        if not outcome.get("success"):
            db.session.rollback()
            return {
                "success": False,
                "error": (
                    f"Could not move {student.admission_number}: "
                    f"{outcome.get('error', 'unknown error')}"
                ),
            }
        moved.append(student.id)

    # Retire the room, keeping everything that happened in it — and keeping
    # the decision itself, which the students' timelines record but the
    # section did not.
    source.merged_into_class_id = target.id
    source.merged_on = when
    source.merged_by_user_id = recorded_by_user_id
    source.merge_reason = reason
    db.session.add(source)
    db.session.commit()

    return {
        "success": True,
        "merged_section_id": source.id,
        "into_section_id": target.id,
        "students_moved": len(moved),
        "merged_on": when.isoformat(),
    }


def _students_currently_in(tenant_id: str, class_id: str):
    """Children whose current placement is this section.

    Read from the enrollment rather than `students.class_id`, since the
    enrollment is the owner and the column is its cache (ADR-014).
    """
    from modules.academics.backbone.models import StudentClassEnrollment
    from modules.students.models import Student

    return (
        Student.query.join(
            StudentClassEnrollment, StudentClassEnrollment.student_id == Student.id
        )
        .filter(
            Student.tenant_id == tenant_id,
            StudentClassEnrollment.class_id == class_id,
            StudentClassEnrollment.is_current.is_(True),
        )
        .all()
    )


def merged_sections(tenant_id: str, academic_year_id: Optional[str] = None) -> List[Class]:
    """Sections that have been merged away, newest first.

    Kept findable on purpose: somebody asked why last term's attendance is
    recorded against a section that no longer takes students needs to be able
    to see that it was merged, and where.
    """
    query = Class.query.filter(
        Class.tenant_id == tenant_id, Class.merged_into_class_id.isnot(None)
    )
    if academic_year_id:
        query = query.filter(Class.academic_year_id == academic_year_id)
    return query.order_by(Class.merged_on.desc()).all()
