"""Tests for student_leaves services state machine (Task 4).

Covers create_request / approve / reject, the validation guards, and the
state transitions including the admin-approval-required branch.
"""

from datetime import date, timedelta

import pytest

from modules.student_leaves.services import (
    create_request,
    approve,
    reject,
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
    tenant_ctx, student_user, class_with_teacher, admin_user, enable_admin_approval
):
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
