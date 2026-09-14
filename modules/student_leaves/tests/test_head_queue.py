"""The principal's approval queue.

The stage exists to be acted on, so the work has to be visible to somebody.
Before the authority split it was not: `admin_fallback_queue` selected only
leaves whose class teacher was away, which a leave the teacher had just
approved never is.
"""

import pytest

from modules.student_leaves.services import (
    admin_fallback_queue,
    approve,
    create_request,
)
from modules.student_leaves.tests.test_services_state_machine import _sample_payload


def test_pending_admin_rows_reach_the_head_queue(
    tenant_ctx, student_user, class_with_teacher, admin_user, enable_admin_approval
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    ids = [row.id for row in admin_fallback_queue(admin_user)]
    assert leave.id in ids


def test_head_queue_says_why_each_row_is_there(
    tenant_ctx, student_user, class_with_teacher, admin_user, enable_admin_approval
):
    """"Needs your approval" and "the teacher is away" are different jobs, and
    the screen has to be able to tell them apart."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    row = next(r for r in admin_fallback_queue(admin_user) if r.id == leave.id)
    assert row.to_dict()["queue_reason"] == "awaiting_head"


def test_teacher_away_rows_are_marked_as_a_stand_in(
    tenant_ctx,
    student_user,
    class_with_teacher,
    admin_user,
    teacher_on_leave_today,
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)

    row = next(r for r in admin_fallback_queue(admin_user) if r.id == leave.id)
    assert row.to_dict()["queue_reason"] == "teacher_away"


def test_queue_rows_carry_the_applicant(
    tenant_ctx, student_user, class_with_teacher, admin_user, enable_admin_approval
):
    """An approver who cannot tell which child this is cannot decide."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    row = next(r for r in admin_fallback_queue(admin_user) if r.id == leave.id)
    applicant = row.to_dict()["applicant"]
    assert applicant["display_name"]
    assert applicant["admission_number"]
    assert applicant["class_name"]


def test_escalation_notifies_only_heads_over_that_campus(
    tenant_ctx,
    student_user,
    class_with_teacher,
    admin_user,
    other_campus_admin_user,
    enable_admin_approval,
    monkeypatch,
):
    """A head of another campus has no authority here and no reason to be told.

    In a trust running twenty campuses, telling every administrator about every
    child's leave is how a notification list stops being read.

    The candidate list is stubbed because `_admin_user_ids_for_tenant` selects
    on the role *named* "Admin" and the fixtures here build uniquely-named test
    roles. What is under test is the branch filter applied to whatever that
    lookup returns.
    """
    from modules.student_leaves import services

    monkeypatch.setattr(
        services,
        "_admin_user_ids_for_tenant",
        lambda tenant_id: [admin_user.id, other_campus_admin_user.id],
    )

    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    recipients = services._admin_user_ids_for_leave(leave)

    # `admin_user` holds no UserSchoolUnit rows — unrestricted, so every campus.
    assert admin_user.id in recipients
    # Bound to North Campus; the child is on Main.
    assert other_campus_admin_user.id not in recipients
