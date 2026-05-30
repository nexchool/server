"""Tests for student_leaves services state machine (Task 4).

Covers create_request / approve / reject, the validation guards, and the
state transitions including the admin-approval-required branch.
"""

from datetime import date, timedelta

import pytest

from core.database import db
from modules.student_leaves.models import StudentLeave
from modules.student_leaves.services import (
    create_request,
    approve,
    reject,
    request_cancel,
    approve_cancel,
    reject_cancel,
    ValidationError,
    StateError,
    AuthorizationError,
)


# ---------------------------------------------------------------------------
# create_request
# ---------------------------------------------------------------------------

def test_create_request_minimal(tenant_ctx, student_user, class_with_teacher):
    payload = {
        "student_id": student_user.student.id,
        "leave_type": "sick",
        "start_date": (date.today() + timedelta(days=1)).isoformat(),
        "end_date": (date.today() + timedelta(days=2)).isoformat(),
        "reason": "Fever",
    }
    leave = create_request(payload, actor_user_id=student_user.id)
    assert leave.status == "pending_class_teacher"
    assert leave.class_id == student_user.student.class_id
    assert leave.class_teacher_id == class_with_teacher.class_teacher_id
    assert leave.requires_admin_approval is False


def test_create_request_rejects_past_start_date(tenant_ctx, student_user):
    payload = {
        "student_id": student_user.student.id,
        "leave_type": "sick",
        "start_date": (date.today() - timedelta(days=1)).isoformat(),
        "end_date": date.today().isoformat(),
        "reason": "Late submission",
    }
    with pytest.raises(ValidationError):
        create_request(payload, actor_user_id=student_user.id)


def test_create_request_rejects_end_before_start(tenant_ctx, student_user):
    payload = {
        "student_id": student_user.student.id,
        "leave_type": "sick",
        "start_date": (date.today() + timedelta(days=2)).isoformat(),
        "end_date": (date.today() + timedelta(days=1)).isoformat(),
        "reason": "x",
    }
    with pytest.raises(ValidationError):
        create_request(payload, actor_user_id=student_user.id)


def test_create_request_rejects_half_day_on_multi_day(tenant_ctx, student_user):
    payload = {
        "student_id": student_user.student.id,
        "leave_type": "sick",
        "start_date": (date.today() + timedelta(days=1)).isoformat(),
        "end_date": (date.today() + timedelta(days=2)).isoformat(),
        "reason": "x",
        "half_day": "am",
    }
    with pytest.raises(ValidationError):
        create_request(payload, actor_user_id=student_user.id)


def test_create_request_rejects_bad_leave_type(tenant_ctx, student_user):
    payload = {
        "student_id": student_user.student.id,
        "leave_type": "vacation",  # not in LEAVE_TYPES
        "start_date": (date.today() + timedelta(days=1)).isoformat(),
        "end_date": (date.today() + timedelta(days=1)).isoformat(),
        "reason": "x",
    }
    with pytest.raises(ValidationError):
        create_request(payload, actor_user_id=student_user.id)


# ---------------------------------------------------------------------------
# approve / reject
# ---------------------------------------------------------------------------

def test_approve_no_admin_required_goes_directly_to_approved(
    tenant_ctx, student_user, class_with_teacher
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    result = approve(leave.id, actor_user_id=class_with_teacher.teacher.user_id)
    assert result.status == "approved"
    assert result.decided_by_id == class_with_teacher.teacher.user_id


def test_approve_admin_required_routes_through_pending_admin(
    tenant_ctx,
    student_user,
    class_with_teacher,
    admin_user,
    enable_admin_approval,
    teacher_on_leave_today,
):
    """Admin completing pending_admin → approved requires class teacher to be
    on approved leave today (Task 5 tightened admin-fallback eligibility)."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    assert leave.requires_admin_approval is True

    after_teacher = approve(leave.id, actor_user_id=class_with_teacher.teacher.user_id)
    assert after_teacher.status == "pending_admin"

    final = approve(leave.id, actor_user_id=admin_user.id)
    assert final.status == "approved"


def test_reject_with_reason(tenant_ctx, student_user, class_with_teacher):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    result = reject(
        leave.id,
        actor_user_id=class_with_teacher.teacher.user_id,
        rejection_reason="Insufficient documentation",
    )
    assert result.status == "rejected"
    assert result.rejection_reason == "Insufficient documentation"


def test_reject_requires_reason(tenant_ctx, student_user, class_with_teacher):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    with pytest.raises(ValidationError):
        reject(
            leave.id,
            actor_user_id=class_with_teacher.teacher.user_id,
            rejection_reason="",
        )


def test_approve_already_decided_raises_state_error(
    tenant_ctx, student_user, class_with_teacher
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher.user_id)
    with pytest.raises(StateError):
        approve(leave.id, actor_user_id=class_with_teacher.teacher.user_id)


def test_unauthorized_approver_raises(tenant_ctx, student_user, other_teacher_user):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    with pytest.raises(AuthorizationError):
        approve(leave.id, actor_user_id=other_teacher_user.id)


# ---------------------------------------------------------------------------
# cancellation
# ---------------------------------------------------------------------------

def test_student_requests_cancel(tenant_ctx, student_user, class_with_teacher):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    result = request_cancel(leave.id, actor_user_id=student_user.id, reason="Plans changed")
    assert result.cancel_requested_at is not None
    assert result.cancel_requested_reason == "Plans changed"
    # Status itself does NOT flip — cancel is a parallel flag
    assert result.status == "pending_class_teacher"


def test_non_owner_cannot_request_cancel(
    tenant_ctx, student_user, class_with_teacher, other_teacher_user
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    with pytest.raises(AuthorizationError):
        request_cancel(leave.id, actor_user_id=other_teacher_user.id, reason="x")


def test_cannot_request_cancel_after_rejection(
    tenant_ctx, student_user, class_with_teacher
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    reject(
        leave.id,
        actor_user_id=class_with_teacher.teacher.user_id,
        rejection_reason="No",
    )
    with pytest.raises(StateError):
        request_cancel(leave.id, actor_user_id=student_user.id, reason="x")


def test_approve_cancel_after_approval_reverses_attendance(
    tenant_ctx, student_user, class_with_teacher
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher.user_id)
    request_cancel(leave.id, actor_user_id=student_user.id, reason="ok")

    from modules.attendance.models import Attendance
    rows_before = db.session.query(Attendance).filter_by(leave_id=leave.id).count()
    assert rows_before > 0  # leave was approved → attendance rows exist

    approve_cancel(leave.id, actor_user_id=class_with_teacher.teacher.user_id)
    rows_after = db.session.query(Attendance).filter_by(leave_id=leave.id).count()
    assert rows_after == 0

    db.session.expire_all()
    refetched = db.session.query(StudentLeave).filter_by(id=leave.id).first()
    assert refetched.status == "cancelled"


def test_reject_cancel_clears_flag_preserves_status(
    tenant_ctx, student_user, class_with_teacher
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    request_cancel(leave.id, actor_user_id=student_user.id, reason="x")
    result = reject_cancel(leave.id, actor_user_id=class_with_teacher.teacher.user_id)
    assert result.cancel_requested_at is None
    assert result.cancel_requested_reason is None
    assert result.status == "pending_class_teacher"


def test_approve_cancel_before_approval_does_not_touch_attendance(
    tenant_ctx, student_user, class_with_teacher
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    # NO approve() call — leave is still pending
    request_cancel(leave.id, actor_user_id=student_user.id, reason="ok")
    approve_cancel(leave.id, actor_user_id=class_with_teacher.teacher.user_id)
    from modules.attendance.models import Attendance
    assert db.session.query(Attendance).filter_by(leave_id=leave.id).count() == 0


# ---------------------------------------------------------------------------
# admin-fallback eligibility
# ---------------------------------------------------------------------------

def test_admin_can_approve_when_class_teacher_on_leave(
    tenant_ctx, student_user, class_with_teacher, admin_user, teacher_on_leave_today
):
    """When the class teacher has an approved teacher-leave overlapping today,
    an admin actor is authorized to approve a student leave for that class."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    result = approve(leave.id, actor_user_id=admin_user.id)
    assert result.status == "approved"


def test_admin_cannot_approve_when_class_teacher_available(
    tenant_ctx, student_user, class_with_teacher, admin_user
):
    """Without a class-teacher overlapping leave, admin gets AuthorizationError."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    with pytest.raises(AuthorizationError):
        approve(leave.id, actor_user_id=admin_user.id)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _sample_payload(student_user):
    return {
        "student_id": student_user.student.id,
        "leave_type": "sick",
        "start_date": (date.today() + timedelta(days=1)).isoformat(),
        "end_date": (date.today() + timedelta(days=2)).isoformat(),
        "reason": "x",
    }
