"""Student leave business logic (state machine).

Task 4 of Slice 4.5: implements create_request / approve / reject with the
validation guards and state machine. Cancellation flow, attendance sync, and
the full admin fallback come in Task 5.

Exceptions intentionally distinct so callers (routes) can map to HTTP codes:
    ValidationError   -> 400
    StateError        -> 409
    AuthorizationError-> 403
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import joinedload

from core.database import db
from core.tenant import get_tenant_id
from modules.classes.models import Class
from modules.students.models import Student
from modules.student_leaves.models import StudentLeave, LEAVE_TYPES


class ValidationError(Exception):
    """Raised on invalid request data — caller maps to 400."""


class StateError(Exception):
    """Raised on invalid state transition — caller maps to 409."""


class AuthorizationError(Exception):
    """Raised when actor is not allowed to perform the action — caller maps to 403."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_request(payload: Dict[str, Any], actor_user_id: str) -> StudentLeave:
    """Create a new student leave request.

    Guards:
        - required: student_id, leave_type, start_date, end_date, reason
        - leave_type must be in LEAVE_TYPES
        - dates parseable YYYY-MM-DD
        - start_date >= today
        - end_date >= start_date
        - half_day only on single-day requests, and must be 'am' or 'pm'
        - student exists, has a class, class exists
        - attachment (if provided) belongs to the student
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise AuthorizationError("Tenant context required")

    student_id = payload.get("student_id")
    leave_type = payload.get("leave_type")
    start_date_s = payload.get("start_date")
    end_date_s = payload.get("end_date")
    reason = payload.get("reason")
    half_day = payload.get("half_day")
    attachment_document_id = payload.get("attachment_document_id")

    if not all([student_id, leave_type, start_date_s, end_date_s, reason]):
        raise ValidationError(
            "student_id, leave_type, start_date, end_date, reason are required"
        )

    if leave_type not in LEAVE_TYPES:
        raise ValidationError(f"leave_type must be one of {LEAVE_TYPES}")

    try:
        start_d = datetime.strptime(start_date_s, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_date_s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ValidationError("start_date and end_date must be YYYY-MM-DD")

    today = date.today()
    if start_d < today:
        raise ValidationError("start_date cannot be in the past")
    if end_d < start_d:
        raise ValidationError("end_date must be >= start_date")
    if half_day and start_d != end_d:
        raise ValidationError("half_day is only allowed on single-day requests")
    if half_day and half_day not in ("am", "pm"):
        raise ValidationError("half_day must be 'am' or 'pm'")

    student = (
        db.session.query(Student)
        .options(joinedload(Student.user))
        .filter(Student.id == student_id, Student.tenant_id == tenant_id)
        .first()
    )
    if not student:
        raise ValidationError("Student not found")
    if not student.class_id:
        raise ValidationError("Student is not assigned to a class")

    cls = (
        db.session.query(Class)
        .filter(Class.id == student.class_id, Class.tenant_id == tenant_id)
        .first()
    )
    if not cls:
        raise ValidationError("Student's class no longer exists")

    class_teacher_id = _resolve_primary_class_teacher_id(tenant_id, cls.id, today)

    if attachment_document_id:
        _assert_attachment_belongs_to(tenant_id, student.id, attachment_document_id)

    requires_admin_approval = _read_tenant_setting_admin_approval(tenant_id)

    leave = StudentLeave(
        tenant_id=tenant_id,
        student_id=student.id,
        class_id=cls.id,
        class_teacher_id=class_teacher_id,
        leave_type=leave_type,
        start_date=start_d,
        end_date=end_d,
        half_day=half_day,
        reason=reason.strip(),
        attachment_document_id=attachment_document_id,
        status="pending_class_teacher",
        requires_admin_approval=requires_admin_approval,
    )
    db.session.add(leave)
    db.session.commit()
    return leave


def approve(leave_id: str, actor_user_id: str) -> StudentLeave:
    """Approve a pending student leave.

    State transitions:
        pending_class_teacher → pending_admin   (if requires_admin_approval)
        pending_class_teacher → approved        (otherwise)
        pending_admin         → approved
    """
    leave = _get_or_404(leave_id)
    if leave.status not in ("pending_class_teacher", "pending_admin"):
        raise StateError("Leave is not pending approval")
    if not _actor_is_authorized_approver(leave, actor_user_id):
        raise AuthorizationError("You are not authorized to approve this request")

    now = datetime.utcnow()
    if leave.status == "pending_class_teacher":
        if leave.requires_admin_approval:
            leave.status = "pending_admin"
        else:
            leave.status = "approved"
            _sync_attendance_rows(leave, actor_user_id)
    else:  # pending_admin
        leave.status = "approved"
        _sync_attendance_rows(leave, actor_user_id)

    leave.decided_by_id = actor_user_id
    leave.decided_at = now
    db.session.commit()
    return leave


def reject(leave_id: str, actor_user_id: str, rejection_reason: str) -> StudentLeave:
    """Reject a pending student leave. Reason is mandatory."""
    leave = _get_or_404(leave_id)
    if leave.status not in ("pending_class_teacher", "pending_admin"):
        raise StateError("Leave is not pending approval")
    if not _actor_is_authorized_approver(leave, actor_user_id):
        raise AuthorizationError("You are not authorized to reject this request")
    if not rejection_reason or not rejection_reason.strip():
        raise ValidationError("rejection_reason is required")

    leave.status = "rejected"
    leave.rejection_reason = rejection_reason.strip()
    leave.decided_by_id = actor_user_id
    leave.decided_at = datetime.utcnow()
    db.session.commit()
    return leave


# ---------------------------------------------------------------------------
# Internal helpers — STUB IMPLEMENTATIONS for Task 4.
# Task 5 expands _actor_is_authorized_approver (admin fallback eligibility) and
# replaces the _sync_attendance_rows no-op with the real upsert.
# ---------------------------------------------------------------------------

def _get_or_404(leave_id: str) -> StudentLeave:
    tenant_id = get_tenant_id()
    leave = (
        db.session.query(StudentLeave)
        .filter(StudentLeave.id == leave_id, StudentLeave.tenant_id == tenant_id)
        .first()
    )
    if not leave:
        raise ValidationError("Leave not found")
    return leave


def _resolve_primary_class_teacher_id(
    tenant_id: str, class_id: str, on_date: date
) -> Optional[str]:
    """Return the (teachers.id) class teacher for a class on a given date.

    Prefers ClassTeacherAssignment (role='primary', active, within effective dates).
    Falls back to Class.teacher_id (which is a users.id) → resolve to the
    corresponding teachers.id row.
    """
    try:
        from modules.academics.backbone.models import ClassTeacherAssignment
        rows = (
            db.session.query(ClassTeacherAssignment)
            .filter(
                ClassTeacherAssignment.tenant_id == tenant_id,
                ClassTeacherAssignment.class_id == class_id,
                ClassTeacherAssignment.role == "primary",
                ClassTeacherAssignment.is_active.is_(True),
                ClassTeacherAssignment.deleted_at.is_(None),
            )
            .all()
        )
        for r in rows:
            ef, et = r.effective_from, r.effective_to
            if ef and on_date < ef:
                continue
            if et and on_date > et:
                continue
            return r.teacher_id
    except ImportError:
        pass

    # Fallback to legacy classes.teacher_id (a users.id pointer).
    cls = (
        db.session.query(Class)
        .filter(Class.id == class_id, Class.tenant_id == tenant_id)
        .first()
    )
    if cls and getattr(cls, "teacher_id", None):
        # classes.teacher_id stores a users.id; resolve to teachers.id.
        from modules.teachers.models import Teacher
        teacher = (
            db.session.query(Teacher)
            .filter(Teacher.tenant_id == tenant_id, Teacher.user_id == cls.teacher_id)
            .first()
        )
        if teacher:
            return teacher.id
    return None


def _assert_attachment_belongs_to(
    tenant_id: str, student_id: str, document_id: str
) -> None:
    from modules.students.models import StudentDocument
    doc = (
        db.session.query(StudentDocument)
        .filter(
            StudentDocument.id == document_id,
            StudentDocument.tenant_id == tenant_id,
            StudentDocument.student_id == student_id,
        )
        .first()
    )
    if not doc:
        raise ValidationError(
            "attachment_document_id does not belong to this student"
        )


def _read_tenant_setting_admin_approval(tenant_id: str) -> bool:
    from modules.academics.backbone.models import AcademicSettings
    s = (
        db.session.query(AcademicSettings)
        .filter(AcademicSettings.tenant_id == tenant_id)
        .first()
    )
    if s is None:
        return False
    return bool(s.student_leave_admin_approval_required)


def _actor_is_authorized_approver(leave: StudentLeave, actor_user_id: str) -> bool:
    """Task 4 narrow check: actor.id == teacher.user_id for leave.class_teacher_id.

    Task 5 will expand to include strict admin-fallback eligibility (only when
    the class teacher is on approved leave today). The temporary catch-all for
    'student.leave.approve.all' permission here is what lets the admin-required
    flow tests reach pending_admin → approved; Task 5 tightens it.
    """
    from modules.teachers.models import Teacher
    if leave.class_teacher_id:
        teacher = (
            db.session.query(Teacher)
            .filter(Teacher.id == leave.class_teacher_id)
            .first()
        )
        if teacher and teacher.user_id == actor_user_id:
            return True

    # Temporary admin pass-through — replaced by strict eligibility in Task 5.
    try:
        from modules.rbac.services import has_permission
        if has_permission(actor_user_id, "student.leave.approve.all"):
            return True
    except Exception:
        # If rbac isn't importable in some narrow test path, deny rather than
        # silently approve.
        return False
    return False


def _sync_attendance_rows(leave: StudentLeave, actor_user_id: str) -> int:
    """No-op for Task 4. Task 5 implements the real upsert into attendance_records."""
    return 0
