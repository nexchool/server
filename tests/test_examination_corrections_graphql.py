"""Corrections over GraphQL.

The domain was verified in EX-02B/EX-03C, so what is tested here is the
transport: that the two authorities stay separate through the wire, that the
queue carries enough context to decide on without a second query, and that a
decided request cannot be decided twice however it is reached.
"""

from __future__ import annotations

import uuid

import pytest

from modules.examinations import corrections_service, marks_service, services as exam_services
from modules.examinations.models import MARK_ABSENT, MARK_PRESENT, ExamMark

from tests.test_examination_marks import (  # noqa: F401
    _new_id,
    _teacher_of_maths,
    ctx,
    cycles,
    exam_type,
    school,
    year,
)
from tests.test_examination_graphql import (  # noqa: F401
    EXAMINATIONS_ON,
    examinations_enabled,
    _codes,
    _data,
    _errors,
    _post,
    _read_as,
    _signed_in,
    _signed_in_at,
    client,
)
from tests.test_examination_results import _exam, _paper_spec, _papers  # noqa: F401

QUEUE = """
query Queue($status: String) {
  markCorrections(status: $status) {
    id status fromStatus toStatus fromMarks toMarks reason
    admissionNumber fullName className subjectName examinationName maxMarks
    requestedByName requestedAt decidedByName decidedAt decisionNote
  }
}
"""

HISTORY = """
query History($markId: ID!) {
  correctionsForMark(examMarkId: $markId) { id status fromMarks toMarks }
}
"""

REQUEST = """
mutation Request($markId: ID!, $toStatus: String!, $toMarks: Float, $reason: String!) {
  requestMarkCorrection(
    examMarkId: $markId, toStatus: $toStatus, toMarks: $toMarks, reason: $reason
  ) { id status fromMarks toMarks reason fullName }
}
"""

APPROVE = """
mutation Approve($id: ID!, $note: String) {
  approveMarkCorrection(correctionId: $id, note: $note) {
    id status decidedByName decisionNote
  }
}
"""

REJECT = """
mutation Reject($id: ID!, $note: String) {
  rejectMarkCorrection(correctionId: $id, note: $note) {
    id status decidedByName decisionNote
  }
}
"""


@pytest.fixture
def manager(db_session, tenant):
    """Runs assessment: may mark, may decide. `assessment.manage` clears ADR-014."""
    return _signed_in(
        db_session, tenant,
        permissions=["assessment.manage", "assessment.update", "assessment.read.class"],
    )


@pytest.fixture
def requester_only(db_session, tenant):
    """May ask for a correction, may not decide one."""
    return _signed_in(db_session, tenant, permissions=["assessment.update"])


@pytest.fixture
def closed(ctx, tenant, cycles, exam_type, school, manager):
    """Riya marked 72 on a paper that has since been closed."""
    _user, _token = manager
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    recorded = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=paper.id, student_id=school["riya"].id,
        status=MARK_PRESENT, marks_obtained=72, actor_user_id=_user.id, commit=False,
    )
    assert recorded["success"] is True, recorded
    assert marks_service.lock_paper(
        paper.id, tenant.id, actor_user_id=_user.id, commit=False
    )["success"] is True
    return {"examination": examination, "paper": paper, "mark": recorded["mark"]}


def _request(client, tenant, token, mark_id, *, to_marks=75, reason="Re-totalled"):
    return _post(client, tenant, token, REQUEST, {
        "markId": mark_id, "toStatus": MARK_PRESENT,
        "toMarks": to_marks, "reason": reason,
    })


# ---------------------------------------------------------------------------
# Raising a request
# ---------------------------------------------------------------------------

def test_a_correction_can_be_raised_and_carries_its_before_state(
    client, tenant, school, closed, manager, ctx
):
    _user, token = manager
    body = _data(_request(client, tenant, token, closed["mark"].id))[
        "requestMarkCorrection"
    ]
    assert body["status"] == "requested"
    assert body["fromMarks"] == 72.0
    assert body["toMarks"] == 75.0
    assert body["fullName"] == "Riya Patel"

    # The mark itself has not moved.
    _read_as(tenant)
    assert float(closed["mark"].marks_obtained) == 72.0


def test_a_correction_needs_a_reason(client, tenant, closed, manager, ctx):
    _user, token = manager
    response = _request(client, tenant, token, closed["mark"].id, reason="   ")
    assert "REASON_REQUIRED" in _codes(response)


def test_an_open_paper_takes_no_corrections(
    client, tenant, cycles, exam_type, school, manager, ctx
):
    _user, token = manager
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    recorded = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=paper.id, student_id=school["riya"].id,
        status=MARK_PRESENT, marks_obtained=72, actor_user_id=_user.id, commit=False,
    )
    response = _request(client, tenant, token, recorded["mark"].id)
    assert "PAPER_NOT_LOCKED" in _codes(response)
    assert _errors(response) == ["CONFLICT"]


def test_a_mark_that_does_not_exist_is_not_found(client, tenant, closed, manager, ctx):
    _user, token = manager
    response = _request(client, tenant, token, "em-nope")
    assert "MARK_NOT_FOUND" in _codes(response)
    assert _errors(response) == ["NOT_FOUND"]


def test_an_invalid_proposal_is_refused(client, tenant, closed, manager, ctx):
    """The service's own validation, unchanged: absent carries no mark."""
    _user, token = manager
    response = _post(client, tenant, token, REQUEST, {
        "markId": closed["mark"].id, "toStatus": MARK_ABSENT,
        "toMarks": 40.0, "reason": "wrong",
    })
    assert "MARKS_NOT_ALLOWED" in _codes(response)


def test_a_teacher_without_standing_over_the_paper_cannot_ask(
    client, tenant, school, closed, requester_only, ctx
):
    """ADR-014 decides, through the service — the resolver does not restate it."""
    _user, token = requester_only
    response = _request(client, tenant, token, closed["mark"].id)
    assert "NOT_THE_MARKER" in _codes(response)


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------

def test_the_queue_carries_enough_to_decide_on(
    client, tenant, school, closed, manager, ctx
):
    """A reviewer must not need a second query to know who and what this is."""
    _user, token = manager
    _request(client, tenant, token, closed["mark"].id)

    queue = _data(_post(client, tenant, token, QUEUE, {"status": "requested"}))[
        "markCorrections"
    ]
    assert len(queue) == 1
    entry = queue[0]
    assert entry["fullName"] == "Riya Patel"
    assert entry["admissionNumber"]
    assert entry["className"] and entry["subjectName"]
    assert entry["examinationName"] == closed["examination"].name
    assert entry["maxMarks"] == 100.0
    assert entry["fromMarks"] == 72.0 and entry["toMarks"] == 75.0
    assert entry["reason"] == "Re-totalled"
    assert entry["requestedByName"] and entry["requestedAt"]


def test_the_queue_shows_only_what_is_still_undecided(
    client, tenant, school, closed, manager, ctx
):
    _user, token = manager
    first = _data(_request(client, tenant, token, closed["mark"].id))[
        "requestMarkCorrection"
    ]
    _data(_post(client, tenant, token, APPROVE, {"id": first["id"], "note": "ok"}))

    assert _data(_post(client, tenant, token, QUEUE, {"status": "requested"}))[
        "markCorrections"
    ] == []
    approved = _data(_post(client, tenant, token, QUEUE, {"status": "approved"}))[
        "markCorrections"
    ]
    assert [entry["id"] for entry in approved] == [first["id"]]


def test_deciding_needs_the_manage_key(
    client, tenant, school, closed, manager, requester_only, ctx
):
    """Asking and deciding are different authorities."""
    _manager_user, manager_token = manager
    raised = _data(_request(client, tenant, manager_token, closed["mark"].id))[
        "requestMarkCorrection"
    ]

    _user, token = requester_only
    assert "FORBIDDEN" in _errors(
        _post(client, tenant, token, APPROVE, {"id": raised["id"]})
    )
    assert "FORBIDDEN" in _errors(
        _post(client, tenant, token, REJECT, {"id": raised["id"]})
    )
    # And the queue itself is not readable without it.
    assert "FORBIDDEN" in _errors(_post(client, tenant, token, QUEUE, {}))


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------

def test_approving_moves_the_mark_once_and_records_the_event(
    client, tenant, school, closed, manager, ctx
):
    _user, token = manager
    raised = _data(_request(client, tenant, token, closed["mark"].id))[
        "requestMarkCorrection"
    ]
    decided = _data(_post(client, tenant, token, APPROVE, {
        "id": raised["id"], "note": "Re-checked with the answer sheet",
    }))["approveMarkCorrection"]

    assert decided["status"] == "approved"
    assert decided["decisionNote"] == "Re-checked with the answer sheet"
    assert decided["decidedByName"]

    _read_as(tenant)
    assert float(closed["mark"].marks_obtained) == 75.0
    assert ExamMark.query.filter_by(
        exam_paper_id=closed["paper"].id, student_id=school["riya"].id
    ).count() == 1
    events = [
        e.event_name
        for e in exam_services.timeline_for(closed["examination"].id, tenant.id)
    ]
    assert events.count(corrections_service.EVENT_MARKS_CORRECTED) == 1


def test_rejecting_leaves_the_mark_and_emits_no_event(
    client, tenant, school, closed, manager, ctx
):
    _user, token = manager
    raised = _data(_request(client, tenant, token, closed["mark"].id))[
        "requestMarkCorrection"
    ]
    decided = _data(_post(client, tenant, token, REJECT, {
        "id": raised["id"], "note": "The answer sheet agrees with 72",
    }))["rejectMarkCorrection"]

    assert decided["status"] == "rejected"
    assert decided["decisionNote"] == "The answer sheet agrees with 72"

    _read_as(tenant)
    assert float(closed["mark"].marks_obtained) == 72.0
    assert corrections_service.EVENT_MARKS_CORRECTED not in [
        e.event_name
        for e in exam_services.timeline_for(closed["examination"].id, tenant.id)
    ]


@pytest.mark.parametrize("first,second", [
    (APPROVE, APPROVE), (APPROVE, REJECT), (REJECT, REJECT), (REJECT, APPROVE),
], ids=["approve-twice", "approve-then-reject", "reject-twice", "reject-then-approve"])
def test_a_decided_request_cannot_be_decided_again(
    client, tenant, closed, manager, ctx, first, second
):
    """The strongest deterministic form of the two-managers race this suite can
    run: a second decision on a settled request is refused, whichever way it
    was settled. A genuine two-connection race is not testable here — the suite
    runs inside one transaction that is rolled back."""
    _user, token = manager
    raised = _data(_request(client, tenant, token, closed["mark"].id))[
        "requestMarkCorrection"
    ]
    _data(_post(client, tenant, token, first, {"id": raised["id"]}))

    response = _post(client, tenant, token, second, {"id": raised["id"]})
    assert "ALREADY_DECIDED" in _codes(response)
    assert _errors(response) == ["CONFLICT"]


def test_a_stale_request_cannot_be_approved(
    client, tenant, school, closed, manager, ctx
):
    """Two requests against 72; approving the first makes the second's
    arithmetic apply to a number nobody is looking at any more."""
    _user, token = manager
    first = _data(_request(client, tenant, token, closed["mark"].id, to_marks=74))[
        "requestMarkCorrection"
    ]
    second = _data(_request(
        client, tenant, token, closed["mark"].id, to_marks=78, reason="Also re-checked"
    ))["requestMarkCorrection"]

    _data(_post(client, tenant, token, APPROVE, {"id": first["id"]}))
    response = _post(client, tenant, token, APPROVE, {"id": second["id"]})

    assert "STALE_CORRECTION" in _codes(response)
    _read_as(tenant)
    assert float(closed["mark"].marks_obtained) == 74.0


def test_the_history_of_a_mark_is_kept(
    client, tenant, school, closed, manager, ctx
):
    _user, token = manager
    first = _data(_request(client, tenant, token, closed["mark"].id, to_marks=74))[
        "requestMarkCorrection"
    ]
    _data(_post(client, tenant, token, APPROVE, {"id": first["id"]}))
    _data(_request(client, tenant, token, closed["mark"].id, to_marks=80,
                   reason="Again"))

    history = _data(_post(client, tenant, token, HISTORY,
                          {"markId": closed["mark"].id}))["correctionsForMark"]
    assert [entry["status"] for entry in history] == ["approved", "requested"]
    assert history[0]["fromMarks"] == 72.0
    # The second request was raised against the new truth.
    assert history[1]["fromMarks"] == 74.0


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------

def test_another_school_sees_and_decides_nothing(
    client, db_session, tenant, school, closed, manager, ctx
):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    _user, token = manager
    raised = _data(_request(client, tenant, token, closed["mark"].id))[
        "requestMarkCorrection"
    ]

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex[:10]}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
        feature_flags=EXAMINATIONS_ON,
    )
    db_session.add(other)
    db_session.flush()
    _outsider, outsider_token = _signed_in_at(
        db_session, other,
        permissions=["assessment.manage", "assessment.update"],
    )

    assert _data(_post(client, other, outsider_token, QUEUE, {"status": "requested"}))[
        "markCorrections"
    ] == []

    response = _post(client, other, outsider_token, APPROVE, {"id": raised["id"]})
    assert "NOT_FOUND" in _errors(response)

    _read_as(tenant)
    assert float(closed["mark"].marks_obtained) == 72.0
    assert corrections_service.correction_queue(
        tenant.id, status="requested"
    )[0]["correction"].status == "requested"


def test_the_acceptance_journey(
    client, tenant, school, closed, manager, ctx
):
    """Locked paper → teacher asks → manager sees it → approves → the register
    shows the corrected mark and the request stays as approved history."""
    _user, token = manager
    raised = _data(_request(client, tenant, token, closed["mark"].id))[
        "requestMarkCorrection"
    ]

    queue = _data(_post(client, tenant, token, QUEUE, {"status": "requested"}))[
        "markCorrections"
    ]
    assert [entry["id"] for entry in queue] == [raised["id"]]

    _data(_post(client, tenant, token, APPROVE, {"id": raised["id"], "note": "Upheld"}))

    _read_as(tenant)
    register = marks_service.marking_register(closed["paper"].id, tenant.id)
    riya = next(
        row for row in register["students"] if row["student_id"] == school["riya"].id
    )
    assert riya["marks_obtained"] == 75.0
    assert riya["status"] == MARK_PRESENT

    history = _data(_post(client, tenant, token, HISTORY,
                          {"markId": closed["mark"].id}))["correctionsForMark"]
    assert [entry["status"] for entry in history] == ["approved"]
