"""Marks entry over GraphQL.

The register read and the write are one screen's two halves, so the tests that
matter are the ones proving the transport did not soften anything: the six mark
states survive the wire, the write stays all-or-nothing, and a locked paper is
refused however it is reached.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from graphql_api import GRAPHQL_PATH
from modules.examinations import marks_service, services as exam_services
from modules.examinations.models import (
    MARK_ABSENT,
    MARK_EXEMPTED,
    MARK_MALPRACTICE,
    MARK_PRESENT,
    ExamMark,
)

from tests.test_examination_marks import (  # noqa: F401
    _enroll,
    _new_id,
    _student,
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

REGISTER = """
query Register($paperId: ID!) {
  markingRegister(examPaperId: $paperId) {
    paper { id maxMarks passMarks examDate componentLabel subjectName className marksLocked }
    examinationId examinationName examinationStatus
    openForMarking
    progress { eligible recorded outstanding locked cohortSource }
    students { studentId admissionNumber fullName rollNumber status marksObtained }
  }
}
"""

RECORD = """
mutation Record($paperId: ID!, $rows: [MarkEntryInput!]!) {
  recordMarks(examPaperId: $paperId, rows: $rows) {
    progress { eligible recorded outstanding }
    students { studentId status marksObtained }
  }
}
"""


@pytest.fixture
def marker(db_session, tenant):
    """Somebody who runs assessment — `assessment.manage` clears ADR-014."""
    return _signed_in(
        db_session, tenant,
        permissions=["assessment.manage", "assessment.read.class"],
    )


@pytest.fixture
def reader_only(db_session, tenant):
    return _signed_in(db_session, tenant, permissions=["assessment.read.class"])


@pytest.fixture
def open_paper(ctx, tenant, cycles, exam_type, school):
    examination = _exam(
        tenant, cycles, exam_type, school,
        [_paper_spec(school["maths"], 100, pass_marks=35)],
    )
    return {"examination": examination, "paper": _papers(examination, tenant)[0]}


def _register(client, tenant, token, paper):
    return _data(
        _post(client, tenant, token, REGISTER, {"paperId": paper.id})
    )["markingRegister"]


def test_the_register_lists_every_eligible_student_with_no_status(
    client, tenant, school, open_paper, marker, ctx
):
    """Three enrolled children, none marked: all three appear, and 'not yet
    entered' arrives as a null status rather than as absent or a zero."""
    _user, token = marker
    register = _register(client, tenant, token, open_paper["paper"])

    assert register["openForMarking"] is True
    assert register["progress"] == {
        "eligible": 3, "recorded": 0, "outstanding": 3,
        "locked": False, "cohortSource": "enrollment",
    }
    assert len(register["students"]) == 3
    assert all(row["status"] is None for row in register["students"])
    assert all(row["marksObtained"] is None for row in register["students"])
    assert {row["fullName"] for row in register["students"]} == {
        "Riya Patel", "Dev Sharma", "Meera Joshi",
    }
    assert all(row["admissionNumber"] for row in register["students"])


def test_the_paper_header_carries_what_a_teacher_reads(
    client, tenant, school, open_paper, marker, ctx
):
    _user, token = marker
    register = _register(client, tenant, token, open_paper["paper"])
    assert register["paper"]["maxMarks"] == 100.0
    assert register["paper"]["passMarks"] == 35.0
    assert register["paper"]["subjectName"] is not None
    assert register["paper"]["className"] is not None
    assert register["examinationStatus"] == "marks_entry"


def test_all_six_states_survive_the_wire(
    client, tenant, school, open_paper, marker, ctx
):
    """Present-with-a-number, a genuine zero, absent, exempted, malpractice —
    and one student left unentered, who must not become any of them."""
    _user, token = marker
    paper = open_paper["paper"]
    rows = [
        {"studentId": school["riya"].id, "status": MARK_PRESENT, "marksObtained": 88},
        {"studentId": school["dev"].id, "status": MARK_PRESENT, "marksObtained": 0},
        {"studentId": school["meera"].id, "status": MARK_ABSENT},
    ]
    written = _data(
        _post(client, tenant, token, RECORD, {"paperId": paper.id, "rows": rows})
    )["recordMarks"]

    by_student = {row["studentId"]: row for row in written["students"]}
    assert by_student[school["riya"].id] == {
        "studentId": school["riya"].id, "status": "present", "marksObtained": 88.0,
    }
    # A genuine zero stays present with zero — never absent.
    assert by_student[school["dev"].id]["status"] == "present"
    assert by_student[school["dev"].id]["marksObtained"] == 0.0
    assert by_student[school["meera"].id]["status"] == "absent"
    assert by_student[school["meera"].id]["marksObtained"] is None
    assert written["progress"]["recorded"] == 3


@pytest.mark.parametrize("status", [MARK_EXEMPTED, MARK_MALPRACTICE])
def test_exempted_and_malpractice_stay_distinct(
    client, tenant, school, open_paper, marker, ctx, status
):
    _user, token = marker
    written = _data(_post(client, tenant, token, RECORD, {
        "paperId": open_paper["paper"].id,
        "rows": [{"studentId": school["riya"].id, "status": status}],
    }))["recordMarks"]
    row = next(r for r in written["students"] if r["studentId"] == school["riya"].id)
    assert row["status"] == status
    assert row["marksObtained"] is None


def test_one_bad_row_writes_none_of_them(
    client, tenant, school, open_paper, marker, ctx
):
    """The service's atomicity, reached through the transport."""
    _user, token = marker
    response = _post(client, tenant, token, RECORD, {
        "paperId": open_paper["paper"].id,
        "rows": [
            {"studentId": school["riya"].id, "status": MARK_PRESENT, "marksObtained": 88},
            {"studentId": school["dev"].id, "status": MARK_PRESENT, "marksObtained": 5000},
        ],
    })
    assert "MARKS_ABOVE_MAX" in _codes(response)
    _read_as(tenant)
    assert ExamMark.query.filter_by(exam_paper_id=open_paper["paper"].id).count() == 0


def test_a_non_finite_mark_is_refused(
    client, tenant, school, open_paper, marker, ctx
):
    """`Float` carries NaN over JSON, so the guard has to hold at the service."""
    _user, token = marker
    response = _post(client, tenant, token, RECORD, {
        "paperId": open_paper["paper"].id,
        "rows": [{
            "studentId": school["riya"].id, "status": MARK_PRESENT,
            "marksObtained": float("nan"),
        }],
    })
    assert response.get_json().get("errors"), "NaN was accepted"


def test_an_absent_student_may_not_carry_a_mark(
    client, tenant, school, open_paper, marker, ctx
):
    _user, token = marker
    response = _post(client, tenant, token, RECORD, {
        "paperId": open_paper["paper"].id,
        "rows": [{
            "studentId": school["riya"].id, "status": MARK_ABSENT, "marksObtained": 0,
        }],
    })
    assert "MARKS_NOT_ALLOWED" in _codes(response)


def test_a_student_from_another_class_is_refused(
    client, tenant, school, open_paper, marker, ctx
):
    _user, token = marker
    response = _post(client, tenant, token, RECORD, {
        "paperId": open_paper["paper"].id,
        "rows": [{
            "studentId": school["outsider"].id, "status": MARK_PRESENT,
            "marksObtained": 50,
        }],
    })
    assert "STUDENT_NOT_ELIGIBLE" in _codes(response)


def test_a_repeated_student_is_refused(
    client, tenant, school, open_paper, marker, ctx
):
    _user, token = marker
    response = _post(client, tenant, token, RECORD, {
        "paperId": open_paper["paper"].id,
        "rows": [
            {"studentId": school["riya"].id, "status": MARK_PRESENT, "marksObtained": 10},
            {"studentId": school["riya"].id, "status": MARK_PRESENT, "marksObtained": 20},
        ],
    })
    assert "STUDENT_REPEATED" in _codes(response)


def test_a_locked_paper_is_read_only_and_says_so(
    client, tenant, school, open_paper, marker, ctx
):
    """The race a teacher can actually hit: the register was open when it
    loaded, and closed by the time they saved."""
    _user, token = marker
    paper = open_paper["paper"]
    _data(_post(client, tenant, token, RECORD, {
        "paperId": paper.id,
        "rows": [{"studentId": school["riya"].id, "status": MARK_PRESENT,
                  "marksObtained": 88}],
    }))

    _read_as(tenant)
    marks_service.lock_paper(paper.id, tenant.id, actor_user_id=_user.id, commit=False)

    register = _register(client, tenant, token, paper)
    assert register["openForMarking"] is False
    assert register["progress"]["locked"] is True
    # Its cohort is now its own register, so `outstanding` is unanswerable.
    assert register["progress"]["outstanding"] is None
    assert register["progress"]["cohortSource"] == "register"

    response = _post(client, tenant, token, RECORD, {
        "paperId": paper.id,
        "rows": [{"studentId": school["riya"].id, "status": MARK_PRESENT,
                  "marksObtained": 90}],
    })
    assert "PAPER_LOCKED" in _codes(response)
    assert _errors(response) == ["CONFLICT"]


def test_reading_a_register_needs_an_assessment_key(
    client, tenant, db_session, school, open_paper, ctx
):
    _user, token = _signed_in(db_session, tenant, permissions=["examination.read"])
    response = _post(client, tenant, token, REGISTER,
                     {"paperId": open_paper["paper"].id})
    assert "FORBIDDEN" in _errors(response)


def test_reading_is_not_writing(
    client, tenant, school, open_paper, reader_only, ctx
):
    """`assessment.read.class` shows the register; it does not mark it."""
    _user, token = reader_only
    assert _register(client, tenant, token, open_paper["paper"]) is not None

    response = _post(client, tenant, token, RECORD, {
        "paperId": open_paper["paper"].id,
        "rows": [{"studentId": school["riya"].id, "status": MARK_PRESENT,
                  "marksObtained": 50}],
    })
    assert "FORBIDDEN" in _errors(response)
    _read_as(tenant)
    assert ExamMark.query.filter_by(exam_paper_id=open_paper["paper"].id).count() == 0


def test_a_teacher_without_authority_over_the_paper_is_refused(
    client, tenant, db_session, school, open_paper, ctx
):
    """ADR-014 still decides. Holding `assessment.enter` is not authority over
    *this* paper, and the transport does not restate that rule — it inherits it."""
    _user, token = _signed_in(
        db_session, tenant, permissions=["assessment.enter", "assessment.read.class"]
    )
    response = _post(client, tenant, token, RECORD, {
        "paperId": open_paper["paper"].id,
        "rows": [{"studentId": school["riya"].id, "status": MARK_PRESENT,
                  "marksObtained": 50}],
    })
    assert "NOT_THE_MARKER" in _codes(response)


def test_another_schools_register_is_invisible(
    client, db_session, tenant, school, open_paper, marker, ctx
):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex[:10]}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
        feature_flags=EXAMINATIONS_ON,
    )
    db_session.add(other)
    db_session.flush()
    _outsider, outsider_token = _signed_in_at(
        db_session, other, permissions=["assessment.manage", "assessment.read.class"]
    )
    paper = open_paper["paper"]

    body = _data(_post(client, other, outsider_token, REGISTER, {"paperId": paper.id}))
    assert body["markingRegister"] is None

    response = _post(client, other, outsider_token, RECORD, {
        "paperId": paper.id,
        "rows": [{"studentId": school["riya"].id, "status": MARK_PRESENT,
                  "marksObtained": 50}],
    })
    assert "PAPER_NOT_FOUND" in _codes(response)
    _read_as(tenant)
    assert ExamMark.query.filter_by(exam_paper_id=paper.id).count() == 0


def test_saving_twice_updates_rather_than_duplicating(
    client, tenant, school, open_paper, marker, ctx
):
    """The register is re-read from the server after a write, so a screen never
    has to guess what its own save produced."""
    _user, token = marker
    paper = open_paper["paper"]
    for marks in (61, 75):
        written = _data(_post(client, tenant, token, RECORD, {
            "paperId": paper.id,
            "rows": [{"studentId": school["riya"].id, "status": MARK_PRESENT,
                      "marksObtained": marks}],
        }))["recordMarks"]

    riya = next(r for r in written["students"] if r["studentId"] == school["riya"].id)
    assert riya["marksObtained"] == 75.0
    assert written["progress"]["recorded"] == 1
    _read_as(tenant)
    assert ExamMark.query.filter_by(
        exam_paper_id=paper.id, student_id=school["riya"].id
    ).count() == 1


def test_the_register_survives_a_reload_exactly(
    client, tenant, school, open_paper, marker, ctx
):
    """The acceptance loop: enter a mixed register, save, read it back."""
    _user, token = marker
    paper = open_paper["paper"]
    _data(_post(client, tenant, token, RECORD, {
        "paperId": paper.id,
        "rows": [
            {"studentId": school["riya"].id, "status": MARK_PRESENT, "marksObtained": 78},
            {"studentId": school["dev"].id, "status": MARK_PRESENT, "marksObtained": 0},
            {"studentId": school["meera"].id, "status": MARK_EXEMPTED},
        ],
    }))

    register = _register(client, tenant, token, paper)
    states = {
        row["studentId"]: (row["status"], row["marksObtained"])
        for row in register["students"]
    }
    assert states[school["riya"].id] == ("present", 78.0)
    assert states[school["dev"].id] == ("present", 0.0)
    assert states[school["meera"].id] == ("exempted", None)
    assert register["progress"] == {
        "eligible": 3, "recorded": 3, "outstanding": 0,
        "locked": False, "cohortSource": "enrollment",
    }
