"""Changing a mark on a paper that has already been closed.

The fixtures are imported from the EX-02A marks tests rather than rebuilt — the
school (two cycles, two teachers, a child enrolled in a section and a batch) is
the same one, and a second copy would drift.
"""

from __future__ import annotations

import uuid

import pytest

from modules.examinations import (
    corrections_service,
    marks_service,
    services as exam_services,
)
from modules.examinations.models import (
    CORRECTION_APPROVED,
    CORRECTION_REJECTED,
    CORRECTION_REQUESTED,
    MARK_ABSENT,
    MARK_PRESENT,
    ExamMark,
    ExamMarkCorrection,
)

# Fixtures: ctx, year, cycles, school, exam_type, marking, anyone_may,
# only_teachers_may, and the helpers.
from tests.test_examination_marks import (  # noqa: F401
    _new_id,
    _teacher_of_maths,
    anyone_may,
    ctx,
    cycles,
    exam_type,
    marking,
    only_teachers_may,
    school,
    year,
)


@pytest.fixture
def closed(ctx, tenant, school, marking, only_teachers_may):
    """Riya marked 72 on a paper that has since been closed."""
    recorded = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=72,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert recorded["success"] is True, recorded
    locked = marks_service.lock_paper(
        marking["paper"].id, tenant.id,
        actor_user_id=school["head"]["user"].id, commit=False,
    )
    assert locked["success"] is True, locked
    return {
        "mark": recorded["mark"],
        "paper": marking["paper"],
        "examination": marking["examination"],
    }


def _request(tenant, school, closed, **kwargs):
    payload = {
        "to_status": MARK_PRESENT,
        "to_marks": 75,
        "reason": "Question 7 was added up twice",
        "requested_by_user_id": _teacher_of_maths(school),
        "commit": False,
    }
    payload.update(kwargs)
    return corrections_service.request_correction(
        tenant.id, closed["mark"].id, **payload
    )


# ---------------------------------------------------------------------------
# Raising a request
# ---------------------------------------------------------------------------

def test_a_closed_mark_can_be_corrected_by_request(
    ctx, tenant, school, closed, only_teachers_may
):
    result = _request(tenant, school, closed)
    assert result["success"] is True, result

    correction = result["correction"]
    assert correction.status == CORRECTION_REQUESTED
    # What it is changing *from* is captured now, not read at approval.
    assert correction.from_status == MARK_PRESENT
    assert float(correction.from_marks) == 72.0
    assert float(correction.to_marks) == 75.0
    assert correction.requested_by_user_id == _teacher_of_maths(school)
    assert correction.requested_at is not None

    # Nothing has moved yet. That is the whole point of a request.
    assert float(closed["mark"].marks_obtained) == 72.0


def test_an_open_paper_takes_no_corrections(
    ctx, tenant, school, marking, only_teachers_may
):
    """Routing an open register through an approval queue would make marking a
    class of forty a forty-request backlog."""
    recorded = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=72,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    result = corrections_service.request_correction(
        tenant.id, recorded["mark"].id, to_status=MARK_PRESENT, to_marks=75,
        reason="typo", requested_by_user_id=_teacher_of_maths(school),
        commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "PAPER_NOT_LOCKED"


def test_a_correction_needs_a_reason(ctx, tenant, school, closed, only_teachers_may):
    result = _request(tenant, school, closed, reason="   ")
    assert result["success"] is False
    assert result["code"] == "REASON_REQUIRED"


def test_a_correction_that_changes_nothing_is_refused(
    ctx, tenant, school, closed, only_teachers_may
):
    result = _request(tenant, school, closed, to_marks=72)
    assert result["success"] is False
    assert result["code"] == "NO_CHANGE"


def test_correcting_an_unmarked_student_is_refused(
    ctx, tenant, school, closed, only_teachers_may
):
    """There is nothing to correct — Dev has no mark on this paper."""
    result = corrections_service.request_correction(
        tenant.id, _new_id("em-"), to_status=MARK_PRESENT, to_marks=50,
        reason="Missing", requested_by_user_id=_teacher_of_maths(school),
        commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "MARK_NOT_FOUND"


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------

def test_requesting_needs_the_update_permission(
    ctx, monkeypatch, tenant, school, closed
):
    import modules.rbac.services as rbac

    monkeypatch.setattr(
        rbac, "has_permission",
        lambda user_id, name: name != marks_service.PERM_UPDATE,
    )
    result = _request(tenant, school, closed)
    assert result["success"] is False
    assert result["code"] == "FORBIDDEN"


def test_a_teacher_of_another_subject_cannot_request(
    ctx, tenant, school, closed, only_teachers_may
):
    """ADR-014 standing is required for a correction exactly as it is for the
    original mark — holding `assessment.update` is not authority over *this*
    paper."""
    result = _request(
        tenant, school, closed,
        requested_by_user_id=school["science_teacher"]["user"].id,
    )
    assert result["success"] is False
    assert result["code"] == "NOT_THE_MARKER"


def test_deciding_needs_the_manage_permission(
    ctx, tenant, school, closed, only_teachers_may
):
    """The teacher who asked cannot also approve. That separation is the
    control; without it a correction is an edit with paperwork."""
    correction = _request(tenant, school, closed)["correction"]

    result = corrections_service.approve_correction(
        tenant.id, correction.id,
        decided_by_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "FORBIDDEN"

    rejected = corrections_service.reject_correction(
        tenant.id, correction.id,
        decided_by_user_id=_teacher_of_maths(school), commit=False,
    )
    assert rejected["success"] is False
    assert rejected["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------

def test_an_approved_correction_moves_the_mark_once(
    ctx, tenant, school, closed, only_teachers_may
):
    correction = _request(tenant, school, closed)["correction"]

    result = corrections_service.approve_correction(
        tenant.id, correction.id,
        decided_by_user_id=school["head"]["user"].id,
        note="Re-checked with the answer sheet", commit=False,
    )
    assert result["success"] is True, result

    assert correction.status == CORRECTION_APPROVED
    assert correction.decided_by_user_id == school["head"]["user"].id
    assert correction.decided_at is not None
    assert correction.decision_note == "Re-checked with the answer sheet"

    assert float(closed["mark"].marks_obtained) == 75.0
    assert closed["mark"].status == MARK_PRESENT
    # One mark, still. A correction changes a row; it does not add one.
    assert ExamMark.query.filter_by(
        exam_paper_id=closed["paper"].id, student_id=school["riya"].id
    ).count() == 1


def test_approval_records_the_business_event(
    ctx, tenant, school, closed, only_teachers_may
):
    correction = _request(tenant, school, closed)["correction"]
    corrections_service.approve_correction(
        tenant.id, correction.id,
        decided_by_user_id=school["head"]["user"].id, commit=False,
    )

    events = exam_services.timeline_for(closed["examination"].id, tenant.id)
    named = [e for e in events
             if e.event_name == corrections_service.EVENT_MARKS_CORRECTED]
    assert len(named) == 1
    # Enough context to understand what moved, without copying the mark in.
    assert closed["mark"].id in named[0].note
    assert school["riya"].id in named[0].note
    assert named[0].actor_user_id == school["head"]["user"].id


def test_a_correction_can_change_a_status_as_well_as_a_number(
    ctx, tenant, school, closed, only_teachers_may
):
    """Present 72 → absent. The number has to go with the status, which is what
    the database CHECK insists on too."""
    correction = _request(
        tenant, school, closed, to_status=MARK_ABSENT, to_marks=None,
        reason="Was recorded against the wrong child",
    )["correction"]

    result = corrections_service.approve_correction(
        tenant.id, correction.id,
        decided_by_user_id=school["head"]["user"].id, commit=False,
    )
    assert result["success"] is True, result
    assert closed["mark"].status == MARK_ABSENT
    assert closed["mark"].marks_obtained is None


def test_zero_is_a_valid_correction(ctx, tenant, school, closed, only_teachers_may):
    """A genuine zero is a mark, and must stay distinguishable from absence."""
    correction = _request(
        tenant, school, closed, to_marks=0, reason="Scored nothing",
    )["correction"]
    result = corrections_service.approve_correction(
        tenant.id, correction.id,
        decided_by_user_id=school["head"]["user"].id, commit=False,
    )
    assert result["success"] is True, result
    assert float(closed["mark"].marks_obtained) == 0.0
    assert closed["mark"].status == MARK_PRESENT


# ---------------------------------------------------------------------------
# The stale request — the reason from_* is stored
# ---------------------------------------------------------------------------

def test_a_stale_correction_cannot_be_approved(
    ctx, tenant, school, closed, only_teachers_may
):
    """Two requests against 72. Approving the first makes the second's "72 → 78"
    an instruction computed against a number nobody is looking at any more."""
    first = _request(tenant, school, closed, to_marks=74)["correction"]
    second = _request(
        tenant, school, closed, to_marks=78, reason="Also re-checked",
    )["correction"]

    assert corrections_service.approve_correction(
        tenant.id, first.id, decided_by_user_id=school["head"]["user"].id,
        commit=False,
    )["success"] is True
    assert float(closed["mark"].marks_obtained) == 74.0

    result = corrections_service.approve_correction(
        tenant.id, second.id, decided_by_user_id=school["head"]["user"].id,
        commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "STALE_CORRECTION"

    # The mark stands at the first correction's value, not the stale one's.
    assert float(closed["mark"].marks_obtained) == 74.0
    assert second.status == CORRECTION_REQUESTED


def test_a_second_correction_is_a_new_request(
    ctx, tenant, school, closed, only_teachers_may
):
    """Never mutate a decided request — the history is the point."""
    first = _request(tenant, school, closed, to_marks=74)["correction"]
    corrections_service.approve_correction(
        tenant.id, first.id, decided_by_user_id=school["head"]["user"].id,
        commit=False,
    )

    second = _request(
        tenant, school, closed, to_marks=76, reason="Re-totalled again",
    )
    assert second["success"] is True, second
    assert second["correction"].id != first.id
    assert float(second["correction"].from_marks) == 74.0   # the new truth

    history = corrections_service.corrections_for_mark(closed["mark"].id, tenant.id)
    assert len(history) == 2
    assert history[0].status == CORRECTION_APPROVED


def test_a_decided_correction_cannot_be_decided_again(
    ctx, tenant, school, closed, only_teachers_may
):
    correction = _request(tenant, school, closed)["correction"]
    head = school["head"]["user"].id
    corrections_service.approve_correction(
        tenant.id, correction.id, decided_by_user_id=head, commit=False
    )

    again = corrections_service.approve_correction(
        tenant.id, correction.id, decided_by_user_id=head, commit=False
    )
    assert again["success"] is False
    assert again["code"] == "ALREADY_DECIDED"


# ---------------------------------------------------------------------------
# Rejection
# ---------------------------------------------------------------------------

def test_a_rejected_correction_leaves_the_mark_alone(
    ctx, tenant, school, closed, only_teachers_may
):
    correction = _request(tenant, school, closed)["correction"]

    result = corrections_service.reject_correction(
        tenant.id, correction.id,
        decided_by_user_id=school["head"]["user"].id,
        note="The answer sheet agrees with 72", commit=False,
    )
    assert result["success"] is True, result

    assert correction.status == CORRECTION_REJECTED
    assert correction.decided_by_user_id == school["head"]["user"].id
    assert correction.decided_at is not None
    assert correction.decision_note == "The answer sheet agrees with 72"
    assert float(closed["mark"].marks_obtained) == 72.0


def test_a_rejected_correction_is_kept(
    ctx, tenant, school, closed, only_teachers_may
):
    """A school asked why a mark was *not* changed has an answer, with a name."""
    correction = _request(tenant, school, closed)["correction"]
    corrections_service.reject_correction(
        tenant.id, correction.id,
        decided_by_user_id=school["head"]["user"].id, commit=False,
    )
    history = corrections_service.corrections_for_mark(closed["mark"].id, tenant.id)
    assert [c.status for c in history] == [CORRECTION_REJECTED]


def test_rejection_writes_no_correction_event(
    ctx, tenant, school, closed, only_teachers_may
):
    correction = _request(tenant, school, closed)["correction"]
    corrections_service.reject_correction(
        tenant.id, correction.id,
        decided_by_user_id=school["head"]["user"].id, commit=False,
    )
    events = exam_services.timeline_for(closed["examination"].id, tenant.id)
    assert corrections_service.EVENT_MARKS_CORRECTED not in [
        e.event_name for e in events
    ]


# ---------------------------------------------------------------------------
# A correction cannot write what marking could not
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "to_marks,code",
    [
        (float("nan"), "MARKS_INVALID"),
        ("nan", "MARKS_INVALID"),
        (float("inf"), "MARKS_INVALID"),
        (float("-inf"), "MARKS_INVALID"),
        (-1, "MARKS_INVALID"),
        (101, "MARKS_ABOVE_MAX"),
        (None, "MARKS_REQUIRED"),
    ],
    ids=["nan", "s-nan", "inf", "-inf", "negative", "above-max", "missing"],
)
def test_an_invalid_correction_is_refused_at_request(
    ctx, tenant, school, closed, only_teachers_may, to_marks, code
):
    result = _request(tenant, school, closed, to_marks=to_marks)
    assert result["success"] is False, f"{to_marks!r} was accepted"
    assert result["code"] == code
    assert float(closed["mark"].marks_obtained) == 72.0


def test_a_correction_cannot_give_an_absent_student_a_mark(
    ctx, tenant, school, closed, only_teachers_may
):
    result = _request(
        tenant, school, closed, to_status=MARK_ABSENT, to_marks=40,
        reason="Wrong",
    )
    assert result["success"] is False
    assert result["code"] == "MARKS_NOT_ALLOWED"


def test_approval_revalidates_rather_than_trusting_the_request(
    ctx, db_session, tenant, school, closed, only_teachers_may
):
    """The request was valid when raised. If the row is tampered with in the
    meantime, approval must still refuse it — the rules are re-run, not
    remembered."""
    correction = _request(tenant, school, closed)["correction"]
    correction.to_marks = 500          # above the paper's 100
    db_session.flush()

    result = corrections_service.approve_correction(
        tenant.id, correction.id,
        decided_by_user_id=school["head"]["user"].id, commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "MARKS_ABOVE_MAX"
    assert float(closed["mark"].marks_obtained) == 72.0
    assert correction.status == CORRECTION_REQUESTED


def test_a_failed_approval_writes_no_event(
    ctx, db_session, tenant, school, closed, only_teachers_may
):
    """The mark, the decision and the event are one unit."""
    correction = _request(tenant, school, closed)["correction"]
    correction.to_marks = 500
    db_session.flush()

    before = len(exam_services.timeline_for(closed["examination"].id, tenant.id))
    corrections_service.approve_correction(
        tenant.id, correction.id,
        decided_by_user_id=school["head"]["user"].id, commit=False,
    )
    after = exam_services.timeline_for(closed["examination"].id, tenant.id)
    assert len(after) == before
    assert corrections_service.EVENT_MARKS_CORRECTED not in [
        e.event_name for e in after
    ]


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------

def test_another_schools_mark_cannot_be_corrected(
    ctx, db_session, tenant, school, closed, only_teachers_may
):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    result = corrections_service.request_correction(
        other.id, closed["mark"].id, to_status=MARK_PRESENT, to_marks=75,
        reason="Theirs", requested_by_user_id=_teacher_of_maths(school),
        commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "MARK_NOT_FOUND"


def test_another_schools_correction_cannot_be_decided(
    ctx, db_session, tenant, school, closed, only_teachers_may
):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    correction = _request(tenant, school, closed)["correction"]
    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    result = corrections_service.approve_correction(
        other.id, correction.id,
        decided_by_user_id=school["head"]["user"].id, commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "NOT_FOUND"
    assert correction.status == CORRECTION_REQUESTED


def test_the_pending_queue_holds_only_undecided_requests(
    ctx, tenant, school, closed, only_teachers_may
):
    correction = _request(tenant, school, closed)["correction"]
    assert correction.id in [
        c.id for c in corrections_service.pending_corrections(tenant.id)
    ]

    corrections_service.reject_correction(
        tenant.id, correction.id,
        decided_by_user_id=school["head"]["user"].id, commit=False,
    )
    assert correction.id not in [
        c.id for c in corrections_service.pending_corrections(tenant.id)
    ]


def test_the_correction_table_refuses_an_impossible_state(
    ctx, db_session, tenant, closed
):
    """Belt to the service's braces: absent with a number cannot be stored."""
    from sqlalchemy.exc import IntegrityError

    db_session.add(ExamMarkCorrection(
        id=_new_id("mc-"), tenant_id=tenant.id, exam_mark_id=closed["mark"].id,
        from_status=MARK_PRESENT, from_marks=72,
        to_status=MARK_ABSENT, to_marks=40,
        reason="impossible", status=CORRECTION_REQUESTED,
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
