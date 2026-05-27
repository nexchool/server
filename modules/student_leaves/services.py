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

from datetime import date, datetime, timedelta
from typing import Any, Dict, List as _List, Optional

from sqlalchemy.orm import joinedload

from core.database import db
from core.tenant import get_tenant_id
from modules.attendance.models import Attendance
from modules.classes.models import Class
from modules.holidays.services import get_holiday_for_date
from modules.students.models import Student
from modules.student_leaves.models import StudentLeave, LEAVE_TYPES
from modules.teachers.models import Teacher, TeacherLeave


class ValidationError(Exception):
    """Raised on invalid request data — caller maps to 400."""


class StateError(Exception):
    """Raised on invalid state transition — caller maps to 409."""


class AuthorizationError(Exception):
    """Raised when actor is not allowed to perform the action — caller maps to 403."""


# ---------------------------------------------------------------------------
# Notification helper
# ---------------------------------------------------------------------------

def _notify(
    tenant_id: str,
    notification_type: str,
    title: str,
    body: str,
    recipient_user_ids: _List[str],
    extra_data: dict | None = None,
    channels: _List[str] | None = None,
) -> None:
    """Best-effort notification — swallows errors so notification failures can't
    roll back the leave transaction."""
    try:
        from modules.notifications import notification_service
        from modules.notifications.enums import NotificationChannel
        if not recipient_user_ids:
            return
        # Default to in-app + push so the student/teacher/admin gets a phone alert.
        ch = channels or [NotificationChannel.IN_APP.value, NotificationChannel.PUSH.value]
        clean_ids = [u for u in recipient_user_ids if u]
        if not clean_ids:
            return
        if len(clean_ids) == 1:
            notification_service.create_notification(
                tenant_id=tenant_id,
                notification_type=notification_type,
                title=title,
                body=body,
                extra_data=extra_data or {},
                channels=ch,
                user_id=clean_ids[0],
            )
        else:
            n = notification_service.create_notification(
                tenant_id=tenant_id,
                notification_type=notification_type,
                title=title,
                body=body,
                extra_data=extra_data or {},
                channels=ch,
                user_id=None,
            )
            notification_service.create_recipients(n.id, clean_ids)
    except Exception as exc:
        from flask import current_app
        current_app.logger.warning("student_leaves notification failed: %s", exc, exc_info=True)


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

    # Notify class teacher of the new request.
    if leave.class_teacher_id:
        teacher = db.session.query(Teacher).filter(Teacher.id == leave.class_teacher_id).first()
        if teacher and teacher.user_id:
            student_display = "A student"
            if student.user and getattr(student.user, "name", None):
                student_display = student.user.name
            _notify(
                tenant_id=leave.tenant_id,
                notification_type="student_leave.submitted",
                title="New student leave request",
                body=f"{student_display} applied for {leave_type} leave from {start_d} to {end_d}",
                recipient_user_ids=[teacher.user_id],
                extra_data={"leave_id": leave.id, "kind": "student_leave.submitted"},
            )
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

    # Notify the student of the decision.
    if leave.student and getattr(leave.student, "user_id", None):
        if leave.status == "approved":
            title = "Leave approved"
            body = f"Your {leave.leave_type} leave for {leave.start_date} to {leave.end_date} was approved"
        else:  # pending_admin
            title = "Leave moved to admin review"
            body = f"Your {leave.leave_type} leave is now awaiting admin approval"
        _notify(
            tenant_id=leave.tenant_id,
            notification_type="student_leave.status_changed",
            title=title,
            body=body,
            recipient_user_ids=[leave.student.user_id],
            extra_data={"leave_id": leave.id, "status": leave.status},
        )

    # If it just transitioned to pending_admin, ping the admins.
    if leave.status == "pending_admin":
        admin_ids = _admin_user_ids_for_tenant(leave.tenant_id)
        if admin_ids:
            student_name = leave.student.user.name if (leave.student and leave.student.user and getattr(leave.student.user, "name", None)) else "a student"
            _notify(
                tenant_id=leave.tenant_id,
                notification_type="student_leave.pending_admin",
                title="Student leave needs your approval",
                body=f"A student leave for {student_name} needs final approval",
                recipient_user_ids=admin_ids,
                extra_data={"leave_id": leave.id},
            )
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

    if leave.student and getattr(leave.student, "user_id", None):
        _notify(
            tenant_id=leave.tenant_id,
            notification_type="student_leave.status_changed",
            title="Leave rejected",
            body=f"Your {leave.leave_type} leave was rejected: {leave.rejection_reason}",
            recipient_user_ids=[leave.student.user_id],
            extra_data={"leave_id": leave.id, "status": "rejected"},
        )
    return leave


def request_cancel(leave_id: str, actor_user_id: str, reason: str) -> StudentLeave:
    """Student-owned request to cancel a leave.

    Sets cancel_requested_at + cancel_requested_reason. Status is not changed
    until an approver acts via approve_cancel / reject_cancel.
    """
    leave = _get_or_404(leave_id)
    if leave.status in ("rejected", "cancelled"):
        raise StateError("Leave is already in a terminal state")
    if not _actor_is_owning_student(leave, actor_user_id):
        raise AuthorizationError("Only the student can request cancellation")

    leave.cancel_requested_at = datetime.utcnow()
    leave.cancel_requested_reason = (reason or "").strip() or None
    db.session.commit()

    if leave.class_teacher_id:
        teacher = db.session.query(Teacher).filter(Teacher.id == leave.class_teacher_id).first()
        if teacher and teacher.user_id:
            student_name = leave.student.user.name if (leave.student and leave.student.user and getattr(leave.student.user, "name", None)) else "A student"
            _notify(
                tenant_id=leave.tenant_id,
                notification_type="student_leave.cancel_requested",
                title="Student wants to cancel leave",
                body=f"{student_name} wants to cancel their {leave.start_date}–{leave.end_date} leave",
                recipient_user_ids=[teacher.user_id],
                extra_data={"leave_id": leave.id},
            )
    return leave


def approve_cancel(leave_id: str, actor_user_id: str) -> StudentLeave:
    """Approve a pending cancellation request.

    Flips status to 'cancelled'. If the prior status was 'approved', the
    attendance rows synced at approval time are removed.
    """
    leave = _get_or_404(leave_id)
    if leave.cancel_requested_at is None:
        raise StateError("No cancellation has been requested for this leave")
    if not _actor_is_authorized_approver(leave, actor_user_id):
        raise AuthorizationError("You are not authorized to approve this cancellation")

    was_approved = leave.status == "approved"
    leave.status = "cancelled"
    leave.decided_by_id = actor_user_id
    leave.decided_at = datetime.utcnow()
    db.session.commit()

    if was_approved:
        _unsync_attendance_rows(leave)

    if leave.student and getattr(leave.student, "user_id", None):
        _notify(
            tenant_id=leave.tenant_id,
            notification_type="student_leave.cancel_approved",
            title="Leave cancelled",
            body=f"Your {leave.leave_type} leave for {leave.start_date}–{leave.end_date} has been cancelled",
            recipient_user_ids=[leave.student.user_id],
            extra_data={"leave_id": leave.id},
        )
    return leave


def reject_cancel(leave_id: str, actor_user_id: str) -> StudentLeave:
    """Reject a pending cancellation request.

    Clears the cancel flags; original status is preserved.
    """
    leave = _get_or_404(leave_id)
    if leave.cancel_requested_at is None:
        raise StateError("No cancellation has been requested for this leave")
    if not _actor_is_authorized_approver(leave, actor_user_id):
        raise AuthorizationError("You are not authorized to reject this cancellation")

    leave.cancel_requested_at = None
    leave.cancel_requested_reason = None
    db.session.commit()

    if leave.student and getattr(leave.student, "user_id", None):
        _notify(
            tenant_id=leave.tenant_id,
            notification_type="student_leave.cancel_rejected",
            title="Cancellation rejected",
            body="Your cancellation request was not approved",
            recipient_user_ids=[leave.student.user_id],
            extra_data={"leave_id": leave.id},
        )
    return leave


# ---------------------------------------------------------------------------
# Internal helpers
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
    """Class teacher always authorized; admin only when class teacher is on
    approved teacher-leave overlapping today.

    Removes Task 4's loose admin shortcut (any holder of
    student.leave.approve.all could approve). Admin fallback is now eligibility-
    gated.
    """
    if not leave.class_teacher_id:
        return False

    teacher = (
        db.session.query(Teacher)
        .filter(Teacher.id == leave.class_teacher_id)
        .first()
    )
    if teacher and teacher.user_id == actor_user_id:
        return True

    # Admin fallback — only when class teacher is unavailable today.
    try:
        from modules.rbac.services import has_permission
        if not has_permission(actor_user_id, "student.leave.approve.all"):
            return False
    except Exception:
        return False
    if not _class_teacher_unavailable_today(leave.class_teacher_id, leave.tenant_id):
        return False
    return True


def _sync_attendance_rows(leave: StudentLeave, actor_user_id: str) -> int:
    """Upsert one Attendance row per school day in the leave range.

    School day = not weekend AND not a holiday for this tenant. If a row
    already exists for (date, class_id, student_id, tenant_id), its status is
    replaced with 'leave' and leave_id is set. Returns the number of rows
    inserted-or-updated.
    """
    count = 0
    cursor = leave.start_date
    while cursor <= leave.end_date:
        if _is_school_day(leave.tenant_id, cursor):
            row = (
                db.session.query(Attendance)
                .filter(
                    Attendance.tenant_id == leave.tenant_id,
                    Attendance.date == cursor,
                    Attendance.student_id == leave.student_id,
                )
                .first()
            )
            if row is None:
                row = Attendance(
                    tenant_id=leave.tenant_id,
                    date=cursor,
                    class_id=leave.class_id,
                    student_id=leave.student_id,
                    status="leave",
                    marked_by=actor_user_id,
                    leave_id=leave.id,
                )
                db.session.add(row)
            else:
                row.status = "leave"
                row.leave_id = leave.id
                row.marked_by = actor_user_id
            count += 1
        cursor += timedelta(days=1)
    db.session.commit()
    return count


def _unsync_attendance_rows(leave: StudentLeave) -> int:
    """Remove attendance rows previously synced for this leave."""
    deleted = (
        db.session.query(Attendance)
        .filter(
            Attendance.tenant_id == leave.tenant_id,
            Attendance.leave_id == leave.id,
        )
        .delete(synchronize_session=False)
    )
    db.session.commit()
    return deleted


def _is_school_day(tenant_id: str, d: date) -> bool:
    if d.weekday() >= 5:  # Sat=5, Sun=6
        return False
    if get_holiday_for_date(d, tenant_id) is not None:
        return False
    return True


def _actor_is_owning_student(leave: StudentLeave, actor_user_id: str) -> bool:
    if not leave.student or not getattr(leave.student, "user_id", None):
        return False
    return leave.student.user_id == actor_user_id


# ---------------------------------------------------------------------------
# Query helpers (Task 6)
# ---------------------------------------------------------------------------

def list_visible_for_user(user, status: Optional[str] = None):
    """Return leaves visible to ``user`` within their tenant, optionally filtered
    by ``status``. Scoping follows the read permission held by the user:
    read.all (admin) → all rows; read.class (teacher) → leaves where the user
    is the class teacher; read.own (student) → only their own leaves.
    """
    from modules.rbac.services import has_permission

    tenant_id = get_tenant_id()
    q = db.session.query(StudentLeave).filter(StudentLeave.tenant_id == tenant_id)
    if status:
        q = q.filter(StudentLeave.status == status)

    if has_permission(user.id, "student.leave.read.all"):
        pass
    elif has_permission(user.id, "student.leave.read.class"):
        teacher = (
            db.session.query(Teacher)
            .filter(Teacher.tenant_id == tenant_id, Teacher.user_id == user.id)
            .first()
        )
        if teacher:
            q = q.filter(StudentLeave.class_teacher_id == teacher.id)
        else:
            return []
    elif has_permission(user.id, "student.leave.read.own"):
        student = (
            db.session.query(Student)
            .filter(Student.tenant_id == tenant_id, Student.user_id == user.id)
            .first()
        )
        if student:
            q = q.filter(StudentLeave.student_id == student.id)
        else:
            return []
    else:
        return []

    return q.order_by(StudentLeave.created_at.desc()).all()


def get_for_user(leave_id: str, user) -> StudentLeave:
    """Fetch a leave the user is allowed to see. Raises AuthorizationError if not."""
    from modules.rbac.services import has_permission

    leave = _get_or_404(leave_id)
    tenant_id = get_tenant_id()

    if has_permission(user.id, "student.leave.read.all"):
        return leave

    if has_permission(user.id, "student.leave.read.class"):
        teacher = (
            db.session.query(Teacher)
            .filter(Teacher.tenant_id == tenant_id, Teacher.user_id == user.id)
            .first()
        )
        if teacher and leave.class_teacher_id == teacher.id:
            return leave

    if has_permission(user.id, "student.leave.read.own"):
        if leave.student and getattr(leave.student, "user_id", None) == user.id:
            return leave

    raise AuthorizationError("Not allowed to view this leave")


def teacher_queue(user):
    """Pending approvals (including cancel requests) for ``user`` as the class
    teacher of the related student.
    """
    tenant_id = get_tenant_id()
    teacher = (
        db.session.query(Teacher)
        .filter(Teacher.tenant_id == tenant_id, Teacher.user_id == user.id)
        .first()
    )
    if not teacher:
        return []
    return (
        db.session.query(StudentLeave)
        .filter(
            StudentLeave.tenant_id == tenant_id,
            StudentLeave.class_teacher_id == teacher.id,
            db.or_(
                StudentLeave.status.in_(("pending_class_teacher", "pending_admin")),
                StudentLeave.cancel_requested_at.isnot(None),
            ),
        )
        .order_by(StudentLeave.created_at.desc())
        .all()
    )


def admin_fallback_queue(user):
    """Pending leaves whose class teacher is on approved teacher-leave today —
    surfaced to admins as the fallback approver queue.
    """
    tenant_id = get_tenant_id()
    today = date.today()
    unavailable_teacher_ids = (
        db.session.query(TeacherLeave.teacher_id)
        .filter(
            TeacherLeave.tenant_id == tenant_id,
            TeacherLeave.status == "approved",
            TeacherLeave.start_date <= today,
            TeacherLeave.end_date >= today,
        )
        .subquery()
    )
    return (
        db.session.query(StudentLeave)
        .filter(
            StudentLeave.tenant_id == tenant_id,
            StudentLeave.class_teacher_id.in_(unavailable_teacher_ids),
            db.or_(
                StudentLeave.status.in_(("pending_class_teacher", "pending_admin")),
                StudentLeave.cancel_requested_at.isnot(None),
            ),
        )
        .order_by(StudentLeave.created_at.desc())
        .all()
    )


def _admin_user_ids_for_tenant(tenant_id: str) -> list:
    """All users with the Admin role for this tenant."""
    try:
        from modules.rbac.models import UserRole, Role
        from modules.auth.models import User
        rows = (
            db.session.query(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .filter(User.tenant_id == tenant_id, Role.name.in_(("Admin", "admin")))
            .all()
        )
        return [r[0] for r in rows]
    except Exception:
        return []


def _class_teacher_unavailable_today(teacher_id: str, tenant_id: str) -> bool:
    today = date.today()
    overlap = (
        db.session.query(TeacherLeave)
        .filter(
            TeacherLeave.tenant_id == tenant_id,
            TeacherLeave.teacher_id == teacher_id,
            TeacherLeave.status == "approved",
            TeacherLeave.start_date <= today,
            TeacherLeave.end_date >= today,
        )
        .first()
    )
    return overlap is not None
