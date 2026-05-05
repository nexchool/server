"""
Student class placement: StudentClassEnrollment is the source of truth.

students.class_id and students.academic_year_id are kept in sync for backward
compatibility and legacy queries.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, exists, and_, or_, not_, false

from core.database import db
from core.tenant import get_tenant_id
from modules.academics.backbone.models import StudentClassEnrollment
from modules.classes.models import Class
from modules.students.models import Student

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

    today = datetime.utcnow().date()

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
        return {"success": False, "error": str(e)}


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

    resolved_ay = cls.academic_year_id
    if academic_year_id and academic_year_id != resolved_ay:
        return "academic_year_id does not match the class's academic year"
    academic_year_id = resolved_ay

    current_rows: List[StudentClassEnrollment] = (
        StudentClassEnrollment.query.filter_by(
            student_id=student_id,
            tenant_id=tenant_id,
            is_current=True,
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
        )
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

    _create_enrollment(
        tenant_id=tenant_id,
        student_id=student_id,
        class_id=class_id,
        academic_year_id=academic_year_id,
        promoted_from_id=prev_id,
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
) -> StudentClassEnrollment:
    row = StudentClassEnrollment(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        student_id=student_id,
        class_id=class_id,
        academic_year_id=academic_year_id,
        enrollment_status="active",
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
        )
    )
    return or_(
        in_enrollment,
        and_(Student.class_id.in_(class_ids), not_(any_current_enrollment_exists())),
    )
