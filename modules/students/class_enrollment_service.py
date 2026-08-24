"""
Student class placement: StudentClassEnrollment is the source of truth.

students.class_id and students.academic_year_id are kept in sync for backward
compatibility and legacy queries.
"""

from __future__ import annotations
from shared.safe_error import safe_error

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, exists, and_, or_, not_, false

from core.database import db
from core.tenant import get_tenant_id
from modules.academics.backbone.models import (
    ENROLLMENT_TYPE_ADDITIONAL,
    ENROLLMENT_TYPE_PRIMARY,
    StudentClassEnrollment,
)
from modules.classes.models import Class
from modules.students.models import Student
from core.school_time import school_today, utc_now

logger = logging.getLogger(__name__)


def assign_student_to_class(
    student_id: str,
    class_id: Optional[str],
    academic_year_id: Optional[str] = None,
    *,
    commit: bool = True,
) -> Dict[str, Any]:
    """
    Assign a student to a class for an academic year using StudentClassEnrollment.

    - When class_id is set: academic_year_id must match the class's year (or omit
      academic_year_id to use the class's academic_year_id).
    - When class_id is None: closes all current enrollments and clears class_id;
      academic_year_id on the student is set from the argument (may be None).

    Transaction: when commit=False, uses a savepoint so the outer session can recover.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    student = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
    if not student:
        return {"success": False, "error": "Student not found"}

    today = utc_now().date()

    def _run() -> Optional[str]:
        err = _assign_student_to_class_impl(
            student=student,
            tenant_id=tenant_id,
            class_id=class_id,
            academic_year_id=academic_year_id,
            ended_on=today,
        )
        return err

    try:
        if commit:
            err = _run()
            if err:
                db.session.rollback()
                return {"success": False, "error": err}
            db.session.commit()
        else:
            try:
                with db.session.begin_nested():
                    err = _run()
                    if err:
                        raise ValueError(err)
            except ValueError as ve:
                return {"success": False, "error": str(ve)}
        return {"success": True}
    except IntegrityError as e:
        logger.warning("assign_student_to_class integrity error: %s", e)
        if commit:
            db.session.rollback()
        return {"success": False, "error": "Enrollment constraint violation"}
    except Exception as e:
        logger.exception("assign_student_to_class failed: %s", e)
        if commit:
            db.session.rollback()
        return {"success": False, "error": safe_error(e)}


def _assign_student_to_class_impl(
    *,
    student: Student,
    tenant_id: str,
    class_id: Optional[str],
    academic_year_id: Optional[str],
    ended_on: datetime.date,
) -> Optional[str]:
    """
    Perform assignment; session flush at end. Returns error message or None.
    """
    student_id = student.id

    if not class_id:
        _close_all_current_enrollments(student_id, tenant_id, ended_on=ended_on)
        student.class_id = None
        student.academic_year_id = academic_year_id
        db.session.flush()
        return None

    cls = Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()
    if not cls:
        return "Class not found"
    if cls.merged_into_class_id is not None:
        # "Only future activities use the merged Section." Guarded here
        # rather than at each caller, so admission, transfer, bulk import
        # and promotion targets are all covered by one rule.
        return "That section has been merged; place the student in the section it merged into"

    resolved_ay = cls.academic_year_id
    if academic_year_id and academic_year_id != resolved_ay:
        return "academic_year_id does not match the class's academic year"
    academic_year_id = resolved_ay

    current_rows: List[StudentClassEnrollment] = (
        StudentClassEnrollment.query.filter_by(
            student_id=student_id,
            tenant_id=tenant_id,
            is_current=True,
            enrollment_type=ENROLLMENT_TYPE_PRIMARY,
        )
        .order_by(StudentClassEnrollment.created_at.desc())
        .all()
    )

    if (
        len(current_rows) == 1
        and current_rows[0].class_id == class_id
        and current_rows[0].academic_year_id == academic_year_id
    ):
        student.class_id = class_id
        student.academic_year_id = academic_year_id
        db.session.flush()
        return None

    if (
        not current_rows
        and student.class_id == class_id
        and student.academic_year_id == academic_year_id
    ):
        _create_enrollment(
            tenant_id=tenant_id,
            student_id=student_id,
            class_id=class_id,
            academic_year_id=academic_year_id,
            promoted_from_id=None,
            roll_number=student.roll_number,
        )
        db.session.flush()
        return None

    # A move inside one academic year is a section transfer, and the canon is
    # exact about it: "Section Transfer modifies the current Academic
    # Enrollment." Closing and reopening would read as the student leaving 8A
    # and joining 8B — two placements for one year — and would stamp
    # `promoted_from_enrollment_id`, which is a promotion's word for a thing
    # that is not a promotion. Where they moved *from* is kept by the
    # SectionTransferred event, which is where transfer history belongs.
    if len(current_rows) == 1 and current_rows[0].academic_year_id == academic_year_id:
        current_rows[0].class_id = class_id
        student.class_id = class_id
        student.academic_year_id = academic_year_id
        db.session.flush()
        return None

    prev_id: Optional[str] = None
    if current_rows:
        prev_id = max(current_rows, key=lambda r: r.created_at).id
        for row in current_rows:
            row.is_current = False
            row.ended_on = ended_on
            row.enrollment_status = "transferred"

    db.session.flush()

    # A new year is a new placement and usually a new roll number, but the
    # school assigns that when it numbers the section. Carrying the previous
    # one forward is the best available answer until they do, and it is what
    # the cache already said.
    _create_enrollment(
        tenant_id=tenant_id,
        student_id=student_id,
        class_id=class_id,
        academic_year_id=academic_year_id,
        promoted_from_id=prev_id,
        roll_number=student.roll_number,
    )

    student.class_id = class_id
    student.academic_year_id = academic_year_id
    db.session.flush()
    return None


def _close_all_current_enrollments(
    student_id: str, tenant_id: str, *, ended_on: datetime.date
) -> None:
    rows = StudentClassEnrollment.query.filter_by(
        student_id=student_id,
        tenant_id=tenant_id,
        is_current=True,
        enrollment_type=ENROLLMENT_TYPE_PRIMARY,
    ).all()
    for row in rows:
        row.is_current = False
        row.ended_on = ended_on
        row.enrollment_status = "transferred"


def _create_enrollment(
    *,
    tenant_id: str,
    student_id: str,
    class_id: str,
    academic_year_id: str,
    promoted_from_id: Optional[str],
    enrollment_type: str = ENROLLMENT_TYPE_PRIMARY,
    roll_number: Optional[int] = None,
) -> StudentClassEnrollment:
    row = StudentClassEnrollment(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        student_id=student_id,
        class_id=class_id,
        academic_year_id=academic_year_id,
        enrollment_status="active",
        enrollment_type=enrollment_type,
        roll_number=roll_number,
        is_current=True,
        started_on=None,
        ended_on=None,
        promoted_from_enrollment_id=promoted_from_id,
    )
    db.session.add(row)
    return row


def academic_year_filter_exists(academic_year_id: str):
    """ EXISTS: student has a current enrollment for this academic year. """
    sce = StudentClassEnrollment
    return exists(
        select(1).where(
            sce.student_id == Student.id,
            sce.tenant_id == Student.tenant_id,
            sce.academic_year_id == academic_year_id,
            sce.is_current.is_(True),
            sce.enrollment_type == ENROLLMENT_TYPE_PRIMARY,
        )
    )


def any_current_enrollment_exists():
    """ EXISTS: student has any current enrollment row. """
    sce = StudentClassEnrollment
    return exists(
        select(1).where(
            sce.student_id == Student.id,
            sce.tenant_id == Student.tenant_id,
            sce.is_current.is_(True),
            sce.enrollment_type == ENROLLMENT_TYPE_PRIMARY,
        )
    )


def student_matches_academic_year_filter(academic_year_id: str):
    """
    Prefer current enrollment for the year; fall back to students.academic_year_id
    when no enrollment rows exist (legacy / migration gaps).
    """
    return or_(
        academic_year_filter_exists(academic_year_id),
        and_(
            Student.academic_year_id == academic_year_id,
            not_(any_current_enrollment_exists()),
        ),
    )


def student_matches_class_filter(class_id: str):
    """ Prefer current enrollment class; fall back to students.class_id. """
    sce = StudentClassEnrollment
    in_enrollment = exists(
        select(1).where(
            sce.student_id == Student.id,
            sce.tenant_id == Student.tenant_id,
            sce.class_id == class_id,
            sce.is_current.is_(True),
            sce.enrollment_type == ENROLLMENT_TYPE_PRIMARY,
        )
    )
    return or_(
        in_enrollment,
        and_(Student.class_id == class_id, not_(any_current_enrollment_exists())),
    )


def student_matches_any_class_filter(class_ids: List[str]):
    if not class_ids:
        return false()
    sce = StudentClassEnrollment
    in_enrollment = exists(
        select(1).where(
            sce.student_id == Student.id,
            sce.tenant_id == Student.tenant_id,
            sce.class_id.in_(class_ids),
            sce.is_current.is_(True),
            sce.enrollment_type == ENROLLMENT_TYPE_PRIMARY,
        )
    )
    return or_(
        in_enrollment,
        and_(Student.class_id.in_(class_ids), not_(any_current_enrollment_exists())),
    )


# ---------------------------------------------------------------------------
# Additional enrollments
# ---------------------------------------------------------------------------
#
# A vacation batch, a coaching programme, a remedial or weekend class. Each is
# a Class like any other — its own campus, teachers, subjects, timetable and
# attendance — so none of them needs an entity of its own. What they are not is
# the student's *class*: `students.class_id` keeps naming the academic
# placement, and nothing here touches it.


def enroll_additional(
    *,
    tenant_id: str,
    student_id: str,
    class_id: str,
) -> Dict[str, Any]:
    """Enroll a student in something they attend alongside their class.

    Deliberately not a variant of `assign_student_to_class`: that function's
    whole job is to keep one placement and one cache in step, and every branch
    of it would have to learn to do nothing. Refusals are returned rather than
    raised, matching the placement primitive.
    """
    student = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
    if not student:
        return {"success": False, "error": "Student not found"}

    cls = Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()
    if not cls:
        return {"success": False, "error": "Class not found"}
    if getattr(cls, "merged_into_class_id", None):
        return {
            "success": False,
            "error": "That section has been merged; use the section it merged into",
        }

    existing = StudentClassEnrollment.query.filter_by(
        tenant_id=tenant_id,
        student_id=student_id,
        class_id=class_id,
        is_current=True,
    ).first()
    if existing:
        return {
            "success": False,
            "error": "The student is already enrolled in this class",
        }

    row = _create_enrollment(
        tenant_id=tenant_id,
        student_id=student_id,
        class_id=class_id,
        academic_year_id=cls.academic_year_id,
        promoted_from_id=None,
        enrollment_type=ENROLLMENT_TYPE_ADDITIONAL,
    )
    db.session.flush()
    return {"success": True, "enrollment_id": row.id}


def end_additional_enrollment(
    *,
    tenant_id: str,
    enrollment_id: str,
    ended_on: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    """Close one additional enrollment. The primary placement is untouched."""
    row = StudentClassEnrollment.query.filter_by(
        id=enrollment_id, tenant_id=tenant_id
    ).first()
    if not row:
        return {"success": False, "error": "Enrollment not found"}
    if row.enrollment_type != ENROLLMENT_TYPE_ADDITIONAL:
        return {
            "success": False,
            "error": (
                "That is the student's academic placement. Use the withdraw, "
                "transfer or graduate workflow instead."
            ),
        }

    row.is_current = False
    row.ended_on = ended_on or school_today()
    row.enrollment_status = "completed"
    db.session.flush()
    return {"success": True}


def additional_enrollments(
    student_id: str, tenant_id: str, *, current_only: bool = True
) -> List[StudentClassEnrollment]:
    """Everything this student attends besides their class."""
    q = StudentClassEnrollment.query.filter_by(
        tenant_id=tenant_id,
        student_id=student_id,
        enrollment_type=ENROLLMENT_TYPE_ADDITIONAL,
    )
    if current_only:
        q = q.filter(StudentClassEnrollment.is_current.is_(True))
    return q.order_by(StudentClassEnrollment.created_at.desc()).all()


def set_primary_roll_number(
    student_id: str, tenant_id: str, roll_number: Optional[int]
) -> Dict[str, Any]:
    """Record a roll number against the student's academic placement.

    The single write path. The enrollment holds the record — that is what a
    reprinted marksheet for an earlier year reads — and `students.roll_number`
    mirrors the primary one, exactly as `students.class_id` mirrors the
    primary placement.

    A student with no primary enrollment yet (admitted, not placed) still gets
    the cache set, and `_create_enrollment` seeds the enrollment from it when
    they are placed. Otherwise a roll number typed on the admission form would
    be silently discarded.
    """
    student = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
    if not student:
        return {"success": False, "error": "Student not found"}

    placement = StudentClassEnrollment.query.filter_by(
        student_id=student_id,
        tenant_id=tenant_id,
        is_current=True,
        enrollment_type=ENROLLMENT_TYPE_PRIMARY,
    ).first()
    if placement is not None:
        placement.roll_number = roll_number

    student.roll_number = roll_number
    db.session.flush()
    return {"success": True}


def set_enrollment_roll_number(
    enrollment_id: str, tenant_id: str, roll_number: Optional[int]
) -> Dict[str, Any]:
    """Number a student within one specific enrollment.

    Used for an additional enrollment — a vacation batch numbers its own
    register — and deliberately does **not** touch `students.roll_number`,
    which names the student's position in their class.
    """
    row = StudentClassEnrollment.query.filter_by(
        id=enrollment_id, tenant_id=tenant_id
    ).first()
    if not row:
        return {"success": False, "error": "Enrollment not found"}

    row.roll_number = roll_number
    if row.enrollment_type == ENROLLMENT_TYPE_PRIMARY and row.is_current:
        # Keep the cache with its owner.
        student = Student.query.filter_by(
            id=row.student_id, tenant_id=tenant_id
        ).first()
        if student is not None:
            student.roll_number = roll_number
    db.session.flush()
    return {"success": True}
