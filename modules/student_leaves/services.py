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

from sqlalchemy.orm import joinedload, selectinload

from core.branch_scope import filter_by_student_ids, student_is_allowed
from core.database import db
from core.tenant import get_tenant_id
from modules.attendance.models import Attendance
from modules.classes.models import Class
from modules.academics.calendar.holiday_services import get_holiday_for_date
from modules.students.models import Student
from modules.student_leaves.models import StudentLeave, LEAVE_TYPES
from modules.teachers.models import Teacher, TeacherLeave
from core.school_time import utc_now
from core.school_time import school_today


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
        from modules.notifications.realtime_pub import (
            InboxRealtimeEvent,
            publish_inbox_event,
        )
        if not recipient_user_ids:
            return
        # Default to in-app + push so the student/teacher/admin gets a phone alert.
        ch = channels or [NotificationChannel.IN_APP.value, NotificationChannel.PUSH.value]
        clean_ids = [u for u in recipient_user_ids if u]
        if not clean_ids:
            return
        if len(clean_ids) == 1:
            n = notification_service.create_notification(
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

        # `ch` asks for PUSH, but writing the rows does not send anything. The
        # dispatch worker is a separate process, so the rows have to be
        # committed before it is enqueued or it queries for a notification it
        # cannot see. (`send_notification` fills in the recipient row for the
        # single-recipient branch.)
        db.session.commit()
        notification_service.send_notification(n.id)
        publish_inbox_event(
            tenant_id,
            clean_ids,
            InboxRealtimeEvent.INBOX_CREATED,
            {"notification_id": n.id},
        )
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

    today = school_today()
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
        .options(joinedload(Student.person), joinedload(Student.user))
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
    student_display = student.display_name or "A student"
    body = (
        f"{student_display} applied for {leave_type} leave from {start_d} to {end_d}"
    )
    if leave.class_teacher_id:
        teacher = db.session.query(Teacher).filter(Teacher.id == leave.class_teacher_id).first()
        if teacher and teacher.user_id:
            _notify(
                tenant_id=leave.tenant_id,
                notification_type="student_leave.submitted",
                title="New student leave request",
                body=body,
                recipient_user_ids=[teacher.user_id],
                extra_data={"leave_id": leave.id, "kind": "student_leave.submitted"},
            )
    else:
        # Nobody holds the section, so the request would otherwise be filed in
        # silence. The heads who can act on it are the ones to tell.
        _notify(
            tenant_id=leave.tenant_id,
            notification_type="student_leave.submitted",
            title="Leave request with no class teacher",
            body=f"{body}. This section has no class teacher, so it needs you.",
            recipient_user_ids=_admin_user_ids_for_leave(leave),
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

    finalises = _assert_may_decide(leave, actor_user_id)
    now = utc_now()

    if leave.status == "pending_class_teacher":
        # Recorded whoever cleared this stage, including a head standing in for
        # an absent teacher — the school wants to see who agreed, not the title
        # the approval nominally belongs to.
        leave.class_teacher_decided_by_id = actor_user_id
        leave.class_teacher_decided_at = now
        if leave.requires_admin_approval and not finalises:
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

    # The class teacher who endorsed this and passed it up hears the outcome.
    if leave.status == "approved" and leave.class_teacher_decided_at is not None:
        _notify_class_teacher_of_outcome(leave, actor_user_id)

    # If it just transitioned to pending_admin, ping the admins.
    if leave.status == "pending_admin":
        admin_ids = _admin_user_ids_for_leave(leave)
        if admin_ids:
            student_name = (leave.student.display_name if leave.student else None) or "a student"
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
    _assert_may_decide(leave, actor_user_id)
    if not rejection_reason or not rejection_reason.strip():
        raise ValidationError("rejection_reason is required")

    leave.status = "rejected"
    leave.rejection_reason = rejection_reason.strip()
    leave.decided_by_id = actor_user_id
    leave.decided_at = utc_now()
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

    # A teacher who already approved this needs to know it was overturned.
    if leave.class_teacher_decided_at is not None:
        _notify_class_teacher_of_outcome(leave, actor_user_id)
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

    leave.cancel_requested_at = utc_now()
    leave.cancel_requested_reason = (reason or "").strip() or None
    db.session.commit()

    if leave.class_teacher_id:
        teacher = db.session.query(Teacher).filter(Teacher.id == leave.class_teacher_id).first()
        if teacher and teacher.user_id:
            student_name = (leave.student.display_name if leave.student else None) or "A student"
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
    # Cancellation stays the class teacher's call, exactly as before the
    # approval stages were separated: they own the register this leave came
    # out of. A head steps in only while that teacher is away — widening it to
    # every head would be a change to who may act, and no one asked for one.
    if not can_act_as_class_teacher(leave, actor_user_id):
        raise AuthorizationError("You are not authorized to approve this cancellation")

    was_approved = leave.status == "approved"
    if was_approved:
        # Reverse attendance in the same transaction as the status flip.
        _unsync_attendance_rows(leave, commit=False)

    leave.status = "cancelled"
    leave.decided_by_id = actor_user_id
    leave.decided_at = utc_now()
    db.session.commit()

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
    if not can_act_as_class_teacher(leave, actor_user_id):
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

    Asked of Teaching Assignment (ADR-014). The old fallback that read the
    `classes.teacher_id` cache is gone: migration 095 gave every cached class
    teacher an owner row, so the service's answer is the whole answer.
    """
    from modules.academics.teaching_assignment import class_teacher_of

    held = class_teacher_of(class_id, on=on_date)
    return held.teacher_id if held else None


def _assert_attachment_belongs_to(
    tenant_id: str, student_id: str, document_id: str
) -> None:
    from modules.documents.models import Document
    from modules.people.document_catalog import OWNER_KIND
    from modules.students.models import Student

    # A document belongs to the human, not the studentship (ADR-015), so the
    # question "is this the student's document" is asked of the person behind
    # the student.
    person_id = (
        db.session.query(Student.person_id).filter(Student.id == student_id).scalar()
    )
    doc = (
        db.session.query(Document)
        .filter(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
            Document.owner_kind == OWNER_KIND,
            Document.owner_id == person_id,
        )
        .first()
        if person_id
        else None
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


def _holds_head_authority(leave: StudentLeave, actor_user_id: str) -> bool:
    """Holds the school-wide leave permission *and* authority over this child.

    Both halves matter. The permission on its own would let the head of one
    campus decide for a child at a campus they do not run — approval is
    authority over the person, not a permission string (ADR-013).
    """
    try:
        from modules.rbac.services import has_permission

        if not has_permission(actor_user_id, "student.leave.approve.all"):
            return False
    except Exception:
        return False
    return student_is_allowed(leave.student_id)


def can_act_as_class_teacher(leave: StudentLeave, actor_user_id: str) -> bool:
    """The class teacher's stage — or a head standing in for them."""
    if not leave.class_teacher_id:
        # The section has no primary class teacher: one left mid-year, or the
        # assignment was never made. The request was accepted all the same, and
        # without this it could be decided by nobody at all — it sat in
        # `pending_class_teacher` forever, in no queue.
        #
        # The school already agreed the head stands in while a class teacher is
        # away. No class teacher at all is that situation, permanently.
        return _holds_head_authority(leave, actor_user_id)

    teacher = (
        db.session.query(Teacher).filter(Teacher.id == leave.class_teacher_id).first()
    )
    if teacher and teacher.user_id == actor_user_id:
        return True

    # Admin fallback — only while the class teacher is actually unavailable.
    if not _holds_head_authority(leave, actor_user_id):
        return False
    return _class_teacher_unavailable_today(leave.class_teacher_id, leave.tenant_id)


def can_act_as_head(leave: StudentLeave, actor_user_id: str) -> bool:
    """The principal's stage.

    The class teacher has no standing here. They may not wave through the
    escalation they themselves created — that is the whole point of a school
    asking for a second signature.
    """
    return _holds_head_authority(leave, actor_user_id)


def _assert_may_decide(leave: StudentLeave, actor_user_id: str) -> bool:
    """Authorise the actor for the leave's *current* stage.

    One predicate used to answer for both stages, which is why a leave that
    reached `pending_admin` could not be finished by anybody: the head was
    admitted only while the class teacher was away, and a teacher who has just
    approved is plainly not away.

    Returns True when this single action should finalise the leave — the head
    acting for an absent teacher, who is senior to them and need not sign
    twice.
    """
    if leave.status == "pending_admin":
        if not can_act_as_head(leave, actor_user_id):
            raise AuthorizationError("You are not authorized to decide this request")
        return True

    if not can_act_as_class_teacher(leave, actor_user_id):
        raise AuthorizationError("You are not authorized to decide this request")

    actor_is_the_class_teacher = (
        db.session.query(Teacher)
        .filter(
            Teacher.id == leave.class_teacher_id,
            Teacher.user_id == actor_user_id,
        )
        .first()
        is not None
    )
    return not actor_is_the_class_teacher


def _sync_attendance_rows(leave: StudentLeave, actor_user_id: str) -> int:
    """Upsert one Attendance row per school day in the leave range.

    School day = not weekend AND not a holiday for this tenant. If a row
    already exists for (date, class_id, student_id, tenant_id), its status is
    replaced with 'leave' and leave_id is set. Returns the number of rows
    inserted-or-updated.

    Re-resolves the student's current class_id at sync time — if the student
    was transferred between submit and approval, the live class is the right
    one for the unique-constraint key.
    """
    # Re-resolve the student's current class. Fall back to the snapshot if the
    # student is currently unenrolled (no class assigned).
    current_class_id = leave.student.class_id if leave.student and leave.student.class_id else leave.class_id

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
                    class_id=current_class_id,
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
                # Keep row.class_id as-is on the update path — it matches the
                # row's historical class context. Only INSERTs use
                # current_class_id.
            count += 1
        cursor += timedelta(days=1)
    db.session.commit()
    return count


def _unsync_attendance_rows(leave: StudentLeave, *, commit: bool = True) -> int:
    """Delete attendance rows synthesized for this leave. Returns row count.

    If commit=False, the caller is responsible for committing as part of a
    larger transaction.
    """
    deleted = (
        db.session.query(Attendance)
        .filter(
            Attendance.tenant_id == leave.tenant_id,
            Attendance.leave_id == leave.id,
        )
        .delete(synchronize_session=False)
    )
    if commit:
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

LEAVE_PAGE_SIZE = 25
LEAVE_MAX_PAGE_SIZE = 100


def _positive_int(value, *, default: int, maximum: Optional[int] = None) -> int:
    """Coerce a query-string number, falling back rather than raising."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    number = max(1, number)
    return min(number, maximum) if maximum else number


def eager_leaves(query):
    """Load what `StudentLeave.to_dict` reads, instead of a query per row.

    It touches the student, the student's person and login (for the name,
    admission number and photo), the class with its campus and medium, and
    both deciding users — eight lazy loads on every row of an approval queue
    otherwise. At 15,000 students a head's queue must not issue a query per
    row.
    """
    return query.options(
        selectinload(StudentLeave.student).selectinload(Student.person),
        selectinload(StudentLeave.student).selectinload(Student.user),
        # The applicant block names the class, its campus and its medium.
        selectinload(StudentLeave.class_ref).selectinload(Class.school_unit),
        selectinload(StudentLeave.class_ref).selectinload(Class.medium),
        selectinload(StudentLeave.class_ref).selectinload(Class.grade),
        selectinload(StudentLeave.decided_by),
        selectinload(StudentLeave.class_teacher_decided_by),
    )


def _empty_page() -> dict:
    return {"items": [], "total": 0, "page": 1, "per_page": 0, "total_pages": 1}


def _page(query, *, page, per_page) -> dict:
    """One page of leaves, newest first.

    The id breaks the tie on created_at: a class's leaves are often filed in
    one sitting, and LIMIT/OFFSET over a partial order serves some rows twice
    and skips others.
    """
    total = query.count()
    page = _positive_int(page, default=1)
    per_page = _positive_int(
        per_page, default=LEAVE_PAGE_SIZE, maximum=LEAVE_MAX_PAGE_SIZE
    )
    items = (
        eager_leaves(query)
        .order_by(StudentLeave.created_at.desc(), StudentLeave.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
        .all()
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


def list_visible_for_user(user, status: Optional[str] = None, page=None,
                          per_page=None) -> dict:
    """One page of the leaves ``user`` may see, as
    ``{items, total, page, per_page, total_pages}``.

    Scoping follows the read permission held by the user: read.all (admin) →
    all rows; read.class (teacher) → leaves where the user is the class
    teacher; read.own (student) → only their own leaves.

    Paged because of the first of those: for a student this is their own
    handful of leaves, but an admin sees every leave the school has recorded.
    """
    from modules.rbac.services import has_permission

    tenant_id = get_tenant_id()
    q = db.session.query(StudentLeave).filter(StudentLeave.tenant_id == tenant_id)
    if status:
        q = q.filter(StudentLeave.status == status)

    if has_permission(user.id, "student.leave.read.all"):
        # "All" means every leave the reader has authority over, not every
        # leave in the trust: a sub-admin restricted to one campus reads their
        # own campus. A leave is a fact about a child — and its reason is
        # routinely medical — so the child is the anchor.
        q = filter_by_student_ids(q, StudentLeave.student_id)
    elif has_permission(user.id, "student.leave.read.class"):
        teacher = (
            db.session.query(Teacher)
            .filter(Teacher.tenant_id == tenant_id, Teacher.user_id == user.id)
            .first()
        )
        if teacher:
            q = q.filter(StudentLeave.class_teacher_id == teacher.id)
        else:
            return _empty_page()
    elif has_permission(user.id, "student.leave.read.own"):
        student = (
            db.session.query(Student)
            .filter(Student.tenant_id == tenant_id, Student.user_id == user.id)
            .first()
        )
        if student:
            q = q.filter(StudentLeave.student_id == student.id)
        else:
            return _empty_page()
    else:
        return _empty_page()

    return _page(q, page=page, per_page=per_page)


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
    return eager_leaves(
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
    """Everything a head is the right person to decide.

    Two different jobs share this screen, and each row says which it is:

      ``awaiting_head``  the class teacher approved and the school's rule sends
                         the request on to the principal. This is the ordinary
                         second stage, and it was invisible until now — the
                         query selected only absent-teacher rows, so a leave
                         the teacher had just approved appeared nowhere.
      ``teacher_away``   the class teacher is on approved leave today, so the
                         head stands in for them at the first stage.
      ``no_class_teacher`` the section has no primary class teacher at all, so
                         there is no first stage to wait for.

    Both are branch-scoped: a head sees only children at campuses they run.
    """
    tenant_id = get_tenant_id()
    today = school_today()

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

    rows = eager_leaves(
        filter_by_student_ids(db.session.query(StudentLeave), StudentLeave.student_id)
        .filter(
            StudentLeave.tenant_id == tenant_id,
            db.or_(
                StudentLeave.status == "pending_admin",
                db.and_(
                    db.or_(
                        StudentLeave.class_teacher_id.in_(unavailable_teacher_ids),
                        StudentLeave.class_teacher_id.is_(None),
                    ),
                    db.or_(
                        StudentLeave.status.in_(
                            ("pending_class_teacher", "pending_admin")
                        ),
                        StudentLeave.cancel_requested_at.isnot(None),
                    ),
                ),
            ),
        )
        .order_by(StudentLeave.created_at.desc())
    ).all()

    for row in rows:
        if row.status == "pending_admin":
            row.queue_reason = "awaiting_head"
        elif row.class_teacher_id is None:
            row.queue_reason = "no_class_teacher"
        else:
            row.queue_reason = "teacher_away"
        # These queues exist only for people who may decide, so the rows carry
        # the guardian's number.
        row.viewer_may_decide = True
    return rows


def _admin_user_ids_for_tenant(tenant_id: str) -> list:
    """All users with the Admin role for this tenant."""
    try:
        from modules.rbac.authority_service import user_ids_holding_profiles

        # Administrators are expected to act on these, so anyone who cannot is
        # left out rather than asked.
        return sorted(
            user_ids_holding_profiles(
                tenant_id, ("Admin",), must_be_able_to_act=True
            )
        )
    except Exception:
        return []


def _notify_class_teacher_of_outcome(leave: StudentLeave, actor_user_id: str) -> None:
    """Tell the class teacher what the head decided about a leave they endorsed.

    They approved it and passed it up, and without this they hear nothing back.
    The class teacher owns the register: if the head refuses a leave the
    teacher endorsed, the child is expected in class on Monday and the teacher
    is the person who has to know that.

    Skipped when the head *is* the person who cleared the first stage — nobody
    needs telling what they just did.
    """
    if not leave.class_teacher_id:
        return
    teacher = (
        db.session.query(Teacher).filter(Teacher.id == leave.class_teacher_id).first()
    )
    if not teacher or not teacher.user_id or teacher.user_id == actor_user_id:
        return

    student_display = (leave.student.display_name if leave.student else None) or "A student"
    if leave.status == "approved":
        title = "Leave you approved was granted"
        body = f"{student_display}'s {leave.leave_type} leave was approved by the principal"
    else:
        reason = leave.rejection_reason or ""
        title = "Leave you approved was refused"
        body = (
            f"{student_display}'s {leave.leave_type} leave was rejected by the "
            f"principal: {reason}"
        ).strip()

    _notify(
        tenant_id=leave.tenant_id,
        notification_type="student_leave.status_changed",
        title=title,
        body=body,
        recipient_user_ids=[teacher.user_id],
        extra_data={"leave_id": leave.id, "status": leave.status},
    )


def _admin_user_ids_for_leave(leave: StudentLeave) -> list:
    """Administrators who could actually decide this leave.

    `_admin_user_ids_for_tenant` answers a different question — every admin in
    the trust. For a trust running twenty campuses that means telling twenty
    people about a child nineteen of them have no authority over, which is how
    a notification list stops being read.
    """
    from core.branch_scope import user_may_act_on_student

    return [
        user_id
        for user_id in _admin_user_ids_for_tenant(leave.tenant_id)
        if user_may_act_on_student(user_id, leave.student_id)
    ]


def _class_teacher_unavailable_today(teacher_id: str, tenant_id: str) -> bool:
    today = school_today()
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
