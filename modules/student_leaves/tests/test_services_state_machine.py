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
    result = approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
    assert result.status == "approved"
    assert result.decided_by_id == class_with_teacher.teacher_row.user_id


def test_approve_admin_required_routes_through_pending_admin(
    tenant_ctx,
    student_user,
    class_with_teacher,
    enable_admin_approval,
):
    """With the rule on, the class teacher's approval escalates rather than grants.

    This used to request `teacher_on_leave_today` and only passed because of it
    — the admin could finish the leave solely because the class teacher was
    away. That hid the fact that the principal's stage was unreachable in the
    ordinary case. See the design doc, 2026-09-14.
    """
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    assert leave.requires_admin_approval is True

    after_teacher = approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
    assert after_teacher.status == "pending_admin"
    assert after_teacher.class_teacher_decided_by_id == class_with_teacher.teacher_row.user_id
    assert after_teacher.class_teacher_decided_at is not None


def test_head_approves_pending_admin_with_class_teacher_present(
    tenant_ctx,
    student_user,
    class_with_teacher,
    admin_user,
    enable_admin_approval,
):
    """The principal finishes the leave while the class teacher is at work.

    This is the ordinary case — the teacher just approved, so they are plainly
    not away — and it was impossible before the authority split: the request
    sat at `pending_admin` with nobody able to move it.
    """
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    final = approve(leave.id, actor_user_id=admin_user.id)
    assert final.status == "approved"
    assert final.decided_by_id == admin_user.id
    # The class teacher's approval survives the principal's.
    assert final.class_teacher_decided_by_id == class_with_teacher.teacher_row.user_id


def test_class_teacher_cannot_approve_at_pending_admin(
    tenant_ctx,
    student_user,
    class_with_teacher,
    enable_admin_approval,
):
    """A teacher may not wave through the escalation they just created."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    with pytest.raises(AuthorizationError):
        approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)


def test_head_approves_both_steps_when_class_teacher_away(
    tenant_ctx,
    student_user,
    class_with_teacher,
    admin_user,
    enable_admin_approval,
    teacher_on_leave_today,
):
    """Teacher away: one head action completes the request.

    The head is senior to the teacher, so a second signature from the same
    person is theatre — and a child's leave must not wait a week for somebody
    to come back.
    """
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    final = approve(leave.id, actor_user_id=admin_user.id)
    assert final.status == "approved"
    assert final.class_teacher_decided_by_id == admin_user.id


def test_head_can_reject_at_pending_admin(
    tenant_ctx,
    student_user,
    class_with_teacher,
    admin_user,
    enable_admin_approval,
):
    """Whoever may approve a stage may also refuse it."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    result = reject(leave.id, actor_user_id=admin_user.id, rejection_reason="Exams week")
    assert result.status == "rejected"
    assert result.rejection_reason == "Exams week"


def test_flag_flip_does_not_reroute_in_flight_request(
    tenant_ctx,
    student_user,
    class_with_teacher,
    db_session,
):
    """A request is judged by the rule in force when it was filed.

    Turning the rule on must not reach back and re-route work a teacher is
    already holding.
    """
    from modules.academics.backbone.models import AcademicSettings

    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    assert leave.requires_admin_approval is False

    settings = (
        db_session.query(AcademicSettings)
        .filter(AcademicSettings.tenant_id == leave.tenant_id)
        .first()
    )
    if settings is None:
        settings = AcademicSettings(
            tenant_id=leave.tenant_id, student_leave_admin_approval_required=True
        )
        db_session.add(settings)
    else:
        settings.student_leave_admin_approval_required = True
    db_session.flush()

    result = approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
    assert result.status == "approved"


def test_reject_with_reason(tenant_ctx, student_user, class_with_teacher):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    result = reject(
        leave.id,
        actor_user_id=class_with_teacher.teacher_row.user_id,
        rejection_reason="Insufficient documentation",
    )
    assert result.status == "rejected"
    assert result.rejection_reason == "Insufficient documentation"


def test_reject_requires_reason(tenant_ctx, student_user, class_with_teacher):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    with pytest.raises(ValidationError):
        reject(
            leave.id,
            actor_user_id=class_with_teacher.teacher_row.user_id,
            rejection_reason="",
        )


def test_approve_already_decided_raises_state_error(
    tenant_ctx, student_user, class_with_teacher
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
    with pytest.raises(StateError):
        approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)


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
        actor_user_id=class_with_teacher.teacher_row.user_id,
        rejection_reason="No",
    )
    with pytest.raises(StateError):
        request_cancel(leave.id, actor_user_id=student_user.id, reason="x")


def test_approve_cancel_after_approval_reverses_attendance(
    tenant_ctx, student_user, class_with_teacher
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
    request_cancel(leave.id, actor_user_id=student_user.id, reason="ok")

    from modules.attendance.models import Attendance
    rows_before = db.session.query(Attendance).filter_by(leave_id=leave.id).count()
    assert rows_before > 0  # leave was approved → attendance rows exist

    approve_cancel(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
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
    result = reject_cancel(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
    assert result.cancel_requested_at is None
    assert result.cancel_requested_reason is None
    assert result.status == "pending_class_teacher"


def test_approve_cancel_before_approval_does_not_touch_attendance(
    tenant_ctx, student_user, class_with_teacher
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    # NO approve() call — leave is still pending
    request_cancel(leave.id, actor_user_id=student_user.id, reason="ok")
    approve_cancel(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
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

def _next_school_days(count=2):
    """The next `count` weekdays, so a leave lands on days the school runs.

    "Tomorrow and the day after" is not a fixed thing: run on a Friday it means
    Saturday and Sunday, no attendance is taken, and a test asserting that
    approval created attendance rows fails for reasons that have nothing to do
    with approval. Tests must not depend on the day they run.
    """
    days = []
    day = date.today()
    while len(days) < count:
        day += timedelta(days=1)
        if day.weekday() < 5:
            days.append(day)
    return days


def _sample_payload(student_user):
    school_days = _next_school_days(2)
    return {
        "student_id": student_user.student.id,
        "leave_type": "sick",
        "start_date": school_days[0].isoformat(),
        "end_date": school_days[-1].isoformat(),
        "reason": "x",
    }


# ---------------------------------------------------------------------------
# A section with nobody assigned to it
# ---------------------------------------------------------------------------

@pytest.fixture
def class_without_a_class_teacher(db_session, class_with_teacher):
    """A section whose primary class teacher has left mid-year.

    Ordinary in a trust of any size, and the leave module had no answer for
    it: the request was accepted and then could not be decided by anybody.
    """
    from modules.academics.backbone.models import ClassTeacherAssignment

    db_session.query(ClassTeacherAssignment).filter(
        ClassTeacherAssignment.class_id == class_with_teacher.id
    ).delete()
    db_session.flush()
    return class_with_teacher


def test_a_leave_with_no_class_teacher_falls_to_the_head(
    tenant_ctx, student_user, class_without_a_class_teacher, admin_user
):
    """A child's request must never be left with nobody able to answer it.

    The school already agreed the head stands in while the class teacher is
    away; a section with no class teacher at all is that situation, permanently.
    """
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    assert leave.class_teacher_id is None

    final = approve(leave.id, actor_user_id=admin_user.id)
    assert final.status == "approved"


def test_a_leave_with_no_class_teacher_reaches_the_head_queue(
    tenant_ctx, student_user, class_without_a_class_teacher, admin_user
):
    from modules.student_leaves.services import admin_fallback_queue

    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)

    row = next(r for r in admin_fallback_queue(admin_user) if r.id == leave.id)
    assert row.to_dict()["queue_reason"] == "no_class_teacher"


def test_an_unrelated_teacher_still_cannot_decide_an_unassigned_leave(
    tenant_ctx, student_user, class_without_a_class_teacher, other_teacher_user
):
    """Falling to the head is not the same as falling to anybody."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)

    with pytest.raises(AuthorizationError):
        approve(leave.id, actor_user_id=other_teacher_user.id)


# ---------------------------------------------------------------------------
# The class teacher hears the verdict
# ---------------------------------------------------------------------------

def test_the_class_teacher_is_told_the_principal_approved(
    tenant_ctx, student_user, class_with_teacher, admin_user, enable_admin_approval,
    monkeypatch,
):
    """They endorsed it and passed it up; they own the register it affects."""
    from modules.student_leaves import services

    sent = []
    monkeypatch.setattr(
        services, "_notify",
        lambda **kw: sent.append(kw),
    )

    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
    sent.clear()
    approve(leave.id, actor_user_id=admin_user.id)

    teacher_user_id = class_with_teacher.teacher_row.user_id
    assert any(
        teacher_user_id in n["recipient_user_ids"] for n in sent
    ), "the class teacher was not told the outcome of a leave they approved"


def test_the_class_teacher_is_told_the_principal_refused(
    tenant_ctx, student_user, class_with_teacher, admin_user, enable_admin_approval,
    monkeypatch,
):
    """The child is expected in class on Monday, and the teacher marks that register."""
    from modules.student_leaves import services

    sent = []
    monkeypatch.setattr(services, "_notify", lambda **kw: sent.append(kw))

    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
    sent.clear()
    reject(leave.id, actor_user_id=admin_user.id, rejection_reason="Exams week")

    teacher_user_id = class_with_teacher.teacher_row.user_id
    assert any(teacher_user_id in n["recipient_user_ids"] for n in sent)


# ---------------------------------------------------------------------------
# "Pending" is a word a school uses, not a column value
# ---------------------------------------------------------------------------

@pytest.fixture
def _reads_own_leaves(monkeypatch):
    """Grant `student.leave.read.own` for the list tests below.

    The `student_user` fixture builds a person and a login, not an authority
    profile, so `list_visible_for_user` would short-circuit to an empty page
    and the filter under test would never run.
    """
    from modules.rbac import services as rbac

    monkeypatch.setattr(
        rbac, "has_permission",
        lambda user_id, perm: perm == "student.leave.read.own",
    )


def test_pending_filter_covers_both_waiting_stages(
    tenant_ctx, student_user, class_with_teacher, enable_admin_approval,
    _reads_own_leaves,
):
    """A child whose request is with the principal is still waiting.

    The filter used to take a status verbatim, so a screen offering "Pending"
    sent `pending_class_teacher` and a request that had moved on to the
    principal vanished from the applicant's own list — alive, and invisible to
    the person who filed it.
    """
    from modules.student_leaves.services import list_visible_for_user

    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
    assert leave.status == "pending_admin"

    page = list_visible_for_user(student_user, status="pending")
    assert [row.id for row in page["items"]] == [leave.id]


def test_a_specific_stage_can_still_be_asked_for(
    tenant_ctx, student_user, class_with_teacher, enable_admin_approval,
    _reads_own_leaves,
):
    """The broad word does not take the precise one away."""
    from modules.student_leaves.services import list_visible_for_user

    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    assert list_visible_for_user(student_user, status="pending_class_teacher")["items"] == []
    assert [r.id for r in list_visible_for_user(student_user, status="pending_admin")["items"]] == [leave.id]
