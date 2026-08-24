"""Results over GraphQL — the last examination domain to get a door.

The domain was verified across earlier slices, so these test the transport and
the one thing a screen can most easily get wrong: keeping **official** apart
from **current**. The acceptance journey at the end is the whole lifecycle.
"""

from __future__ import annotations

import uuid

import pytest

from modules.examinations import (
    corrections_service,
    marks_service,
    results_service,
    services as exam_services,
)
from modules.examinations.models import MARK_PRESENT, ExamResult

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
from tests.test_examination_results import (  # noqa: F401
    _band,
    _exam,
    _mark,
    _paper_spec,
    _papers,
    _scheme,
)

RESULTS = """
query Results($id: ID!) {
  examinationResults(examinationId: $id) {
    examinationStatus readyToPublish
    cohort calculated published revisionPending
    blocked { studentId code }
    students {
      studentId fullName admissionNumber hasResult revisionPending
      official { version percentage gradeLabel isPass publishedAt }
      current { version percentage publishedAt isCurrent }
      versions { version percentage publishedAt isCurrent revisionReason }
    }
  }
}
"""

CALCULATE = """
mutation Calc($id: ID!) {
  calculateExaminationResults(examinationId: $id) { calculated readyToPublish }
}
"""
PUBLISH = """
mutation Publish($id: ID!) {
  publishExaminationResults(examinationId: $id) { examinationStatus published }
}
"""
REVISE = """
mutation Revise($id: ID!, $student: ID!, $reason: String!) {
  reviseStudentResult(examinationId: $id, studentId: $student, reason: $reason) {
    revisionPending
    students { studentId revisionPending
      official { version percentage } current { version percentage publishedAt } }
  }
}
"""
PUBLISH_REVISION = """
mutation PublishRevision($id: ID!, $student: ID!) {
  publishStudentRevision(examinationId: $id, studentId: $student) {
    students { studentId revisionPending official { version percentage } }
  }
}
"""


@pytest.fixture
def officer(db_session, tenant):
    """Runs examinations *and* assessment — calculation checks both."""
    return _signed_in(
        db_session, tenant,
        permissions=[
            "examination.read", "examination.publish",
            "assessment.manage", "assessment.update",
        ],
    )


@pytest.fixture
def marked(ctx, tenant, cycles, exam_type, school, officer):
    """Three students marked on one paper, with a grading scheme."""
    _user, _token = officer
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A", 60, 100, is_pass=True, sequence=1)
    _band(tenant, scheme, "F", 0, 59.99, is_pass=False, sequence=2)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    marks = {}
    for student, score in ((school["riya"], 88), (school["dev"], 70),
                           (school["meera"], 50)):
        marks[student.id] = _mark(tenant, paper, student, MARK_PRESENT, score)
    return {"examination": examination, "paper": paper, "marks": marks,
            "scheme": scheme}


def _board(client, tenant, token, examination):
    return _data(_post(client, tenant, token, RESULTS, {"id": examination.id}))[
        "examinationResults"
    ]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def test_before_calculation_the_board_shows_the_cohort_and_blocks(
    client, tenant, school, marked, officer, ctx
):
    _user, token = officer
    board = _board(client, tenant, token, marked["examination"])

    assert board["cohort"] == 3
    assert board["calculated"] == 0
    assert board["published"] == 0
    assert board["readyToPublish"] is False
    assert {b["code"] for b in board["blocked"]} == {"RESULT_MISSING"}
    assert all(row["hasResult"] is False for row in board["students"])
    assert all(row["fullName"] for row in board["students"])


def test_calculating_fills_the_board_without_publishing_anything(
    client, tenant, school, marked, officer, ctx
):
    _user, token = officer
    calculated = _data(_post(client, tenant, token, CALCULATE,
                             {"id": marked["examination"].id}))[
        "calculateExaminationResults"
    ]
    assert calculated["calculated"] == 3
    assert calculated["readyToPublish"] is True

    board = _board(client, tenant, token, marked["examination"])
    assert board["published"] == 0
    riya = next(r for r in board["students"] if r["studentId"] == school["riya"].id)
    # Calculated, but nobody has been told: current exists, official does not.
    assert riya["current"]["percentage"] == 88.0
    assert riya["current"]["publishedAt"] is None
    assert riya["official"] is None


def test_an_incomplete_result_blocks_publication_and_says_who(
    client, tenant, cycles, exam_type, school, officer, ctx
):
    _user, token = officer
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)
    _data(_post(client, tenant, token, CALCULATE, {"id": examination.id}))

    board = _board(client, tenant, token, examination)
    assert board["readyToPublish"] is False
    blocked = {b["studentId"]: b["code"] for b in board["blocked"]}
    assert blocked[school["dev"].id] == "RESULT_INCOMPLETE"

    response = _post(client, tenant, token, PUBLISH, {"id": examination.id})
    assert "RESULT_INCOMPLETE" in _codes(response)
    assert _errors(response) == ["CONFLICT"]


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------

def test_publishing_makes_every_result_official(
    client, tenant, school, marked, officer, ctx
):
    _user, token = officer
    _data(_post(client, tenant, token, CALCULATE, {"id": marked["examination"].id}))
    before = _board(client, tenant, token, marked["examination"])
    snapshots = {
        row["studentId"]: row["current"]["percentage"] for row in before["students"]
    }

    published = _data(_post(client, tenant, token, PUBLISH,
                            {"id": marked["examination"].id}))[
        "publishExaminationResults"
    ]
    assert published["examinationStatus"] == "published"
    assert published["published"] == 3

    board = _board(client, tenant, token, marked["examination"])
    for row in board["students"]:
        assert row["official"]["publishedAt"] is not None
        assert row["official"]["version"] == 1
        # Publication says *when*, never *what*.
        assert row["official"]["percentage"] == snapshots[row["studentId"]]

    _read_as(tenant)
    events = [
        e.event_name
        for e in exam_services.timeline_for(marked["examination"].id, tenant.id)
    ]
    assert events.count("ResultsPublished") == 1


def test_publishing_twice_is_refused(client, tenant, marked, officer, ctx):
    _user, token = officer
    _data(_post(client, tenant, token, CALCULATE, {"id": marked["examination"].id}))
    _data(_post(client, tenant, token, PUBLISH, {"id": marked["examination"].id}))

    response = _post(client, tenant, token, PUBLISH, {"id": marked["examination"].id})
    assert "INVALID_TRANSITION" in _codes(response)


def test_a_published_result_refuses_recalculation(
    client, tenant, marked, officer, ctx
):
    _user, token = officer
    _data(_post(client, tenant, token, CALCULATE, {"id": marked["examination"].id}))
    _data(_post(client, tenant, token, PUBLISH, {"id": marked["examination"].id}))

    response = _post(client, tenant, token, CALCULATE,
                     {"id": marked["examination"].id})
    assert "RESULT_PUBLISHED" in _codes(response)


# ---------------------------------------------------------------------------
# Authorization and tenancy
# ---------------------------------------------------------------------------

def test_reading_results_needs_the_examination_read_key(
    client, tenant, db_session, marked, ctx
):
    _user, token = _signed_in(db_session, tenant, permissions=["assessment.manage"])
    response = _post(client, tenant, token, RESULTS, {"id": marked["examination"].id})
    assert "FORBIDDEN" in _errors(response)


def test_assessment_manage_does_not_publish_results(
    client, tenant, db_session, marked, officer, ctx
):
    """Running marking is not the authority to tell parents."""
    _officer_user, officer_token = officer
    _data(_post(client, tenant, officer_token, CALCULATE,
                {"id": marked["examination"].id}))

    _user, token = _signed_in(
        db_session, tenant,
        permissions=["examination.read", "assessment.manage"],
    )
    for mutation in (CALCULATE, PUBLISH):
        assert "FORBIDDEN" in _errors(
            _post(client, tenant, token, mutation, {"id": marked["examination"].id})
        )

    _read_as(tenant)
    assert marked["examination"].status == "marks_entry"
    assert all(
        row.published_at is None
        for row in ExamResult.query.filter_by(
            examination_id=marked["examination"].id
        ).all()
    )


def test_another_school_sees_and_publishes_nothing(
    client, db_session, tenant, marked, officer, ctx
):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    _user, token = officer
    _data(_post(client, tenant, token, CALCULATE, {"id": marked["examination"].id}))

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex[:10]}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
        feature_flags=EXAMINATIONS_ON,
    )
    db_session.add(other)
    db_session.flush()
    _outsider, outsider_token = _signed_in_at(
        db_session, other,
        permissions=["examination.read", "examination.publish", "assessment.manage"],
    )
    examination_id = marked["examination"].id

    assert _data(_post(client, other, outsider_token, RESULTS,
                       {"id": examination_id}))["examinationResults"] is None
    assert "NOT_FOUND" in _errors(
        _post(client, other, outsider_token, PUBLISH, {"id": examination_id})
    )
    assert "NOT_FOUND" in _errors(
        _post(client, other, outsider_token, REVISE, {
            "id": examination_id, "student": "s-1", "reason": "theirs",
        })
    )

    _read_as(tenant)
    assert marked["examination"].status == "marks_entry"


# ---------------------------------------------------------------------------
# The acceptance journey
# ---------------------------------------------------------------------------

def test_calculate_publish_correct_revise_republish(
    client, tenant, school, marked, officer, ctx
):
    """The whole lifecycle, ending with v1 intact and v2 official."""
    _user, token = officer
    examination = marked["examination"]

    _data(_post(client, tenant, token, CALCULATE, {"id": examination.id}))
    # The paper is closed before publication — `lock_paper` needs the
    # examination still in marks entry, which is also the order a school
    # works in: finish the register, then tell people.
    _read_as(tenant)
    assert marks_service.lock_paper(
        marked["paper"].id, tenant.id, actor_user_id=_user.id, commit=False
    )["success"] is True
    _data(_post(client, tenant, token, PUBLISH, {"id": examination.id}))

    # A published mark is corrected.
    _read_as(tenant)
    raised = corrections_service.request_correction(
        tenant.id, marked["marks"][school["riya"].id].id,
        to_status=MARK_PRESENT, to_marks=95, reason="Re-totalled",
        requested_by_user_id=_user.id, commit=False,
    )
    assert raised["success"] is True, raised
    assert corrections_service.approve_correction(
        tenant.id, raised["correction"].id, decided_by_user_id=_user.id, commit=False
    )["success"] is True

    # The board now says a revision is owed — and still shows the official v1.
    board = _board(client, tenant, token, examination)
    riya = next(r for r in board["students"] if r["studentId"] == school["riya"].id)
    assert board["revisionPending"] == 1
    assert riya["revisionPending"] is True
    assert riya["official"]["percentage"] == 88.0

    revised = _data(_post(client, tenant, token, REVISE, {
        "id": examination.id, "student": school["riya"].id,
        "reason": "Correction approved",
    }))["reviseStudentResult"]
    riya = next(r for r in revised["students"] if r["studentId"] == school["riya"].id)
    # v2 exists and is current, but nobody has been told: official is still v1.
    assert riya["current"]["version"] == 2
    assert riya["current"]["percentage"] == 95.0
    assert riya["current"]["publishedAt"] is None
    assert riya["official"]["version"] == 1
    assert riya["official"]["percentage"] == 88.0

    _data(_post(client, tenant, token, PUBLISH_REVISION, {
        "id": examination.id, "student": school["riya"].id,
    }))

    final = _board(client, tenant, token, examination)
    riya = next(r for r in final["students"] if r["studentId"] == school["riya"].id)
    assert riya["official"]["version"] == 2
    assert riya["official"]["percentage"] == 95.0
    assert riya["revisionPending"] is False

    # v1 is still there, still published, still saying what it said.
    history = {v["version"]: v for v in riya["versions"]}
    assert history[1]["percentage"] == 88.0
    assert history[1]["publishedAt"] is not None
    assert history[1]["isCurrent"] is False
    assert history[2]["revisionReason"] == "Correction approved"

    _read_as(tenant)
    events = [
        e.event_name for e in exam_services.timeline_for(examination.id, tenant.id)
    ]
    assert events.count("ResultsRevised") == 1
    assert events.count("ResultsPublished") == 2      # first, then the revision


def test_revising_without_a_correction_is_refused(
    client, tenant, school, marked, officer, ctx
):
    _user, token = officer
    _data(_post(client, tenant, token, CALCULATE, {"id": marked["examination"].id}))
    _data(_post(client, tenant, token, PUBLISH, {"id": marked["examination"].id}))

    response = _post(client, tenant, token, REVISE, {
        "id": marked["examination"].id, "student": school["riya"].id,
        "reason": "no reason to",
    })
    assert "NOTHING_TO_REVISE" in _codes(response)
