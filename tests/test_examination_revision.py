"""Revising a result that has already been published.

The point of every test here is that version 1 does not move. A revision that
quietly rewrote history would satisfy any test that only looked at "the
result", so these look at the version, the snapshot and the timestamps of the
row that was published — after the revision exists.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from core.database import db
from modules.examinations import (
    corrections_service,
    marks_service,
    publication_service,
    results_service,
    revision_service,
    services as exam_services,
)
from modules.examinations.models import (
    EXAM_MARKS_ENTRY,
    EXAM_PUBLISHED,
    MARK_ABSENT,
    MARK_PRESENT,
    ExamMark,
    ExamResult,
)

from tests.test_examination_marks import (  # noqa: F401
    _new_id,
    _teacher_of_maths,
    ctx,
    cycles,
    exam_type,
    school,
    year,
)
from tests.test_examination_results import (  # noqa: F401
    _band,
    _calc,
    _exam,
    _mark,
    _paper_spec,
    _papers,
    _scheme,
    anyone_manages,
    head,
)


def _history(tenant, examination, student):
    return revision_service.result_history(examination.id, student.id, tenant.id)


def _snapshot_of(tenant, examination, student, version):
    return next(
        r for r in _history(tenant, examination, student) if r.version == version
    ).snapshot


@pytest.fixture
def published(ctx, tenant, cycles, exam_type, school, head, anyone_manages):
    """Three students marked, calculated, the paper locked and the examination
    published — the state a real correction arrives into."""
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A", 80, 100, is_pass=True, sequence=1)
    _band(tenant, scheme, "B", 60, 79.99, is_pass=True, sequence=2)
    _band(tenant, scheme, "F", 0, 59.99, is_pass=False, sequence=3)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100, pass_marks=35)],
                        scheme=scheme)
    paper = _papers(examination, tenant)[0]
    marks = {}
    for student, score in ((school["riya"], 70), (school["dev"], 90),
                           (school["meera"], 50)):
        marks[student.id] = _mark(tenant, paper, student, MARK_PRESENT, score)

    assert results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )["success"] is True
    assert marks_service.lock_paper(
        paper.id, tenant.id, actor_user_id=head, commit=False
    )["success"] is True
    assert publication_service.publish_results(
        examination.id, tenant.id, actor_user_id=head, commit=False
    )["success"] is True

    return {
        "examination": examination, "paper": paper, "scheme": scheme,
        "marks": marks,
    }


def _correct(tenant, published, student, to_marks, school, *, approve=True):
    """Raise, and usually approve, a correction against a published mark."""
    mark = published["marks"][student.id]
    raised = corrections_service.request_correction(
        tenant.id, mark.id, to_status=MARK_PRESENT, to_marks=to_marks,
        reason="Question 7 was added up twice",
        requested_by_user_id=_teacher_of_maths(school), commit=False,
    )
    assert raised["success"] is True, raised
    if approve:
        decided = corrections_service.approve_correction(
            tenant.id, raised["correction"].id,
            decided_by_user_id=school["head"]["user"].id, commit=False,
        )
        assert decided["success"] is True, decided
    return raised["correction"]


def _revise(tenant, published, student, head, reason="Re-check upheld"):
    return revision_service.revise_result(
        published["examination"].id, student.id, tenant.id,
        reason=reason, actor_user_id=head, commit=False,
    )


# ---------------------------------------------------------------------------
# The published version does not move
# ---------------------------------------------------------------------------

def test_a_revision_adds_a_version_and_leaves_the_published_one_alone(
    ctx, tenant, school, published, head, anyone_manages
):
    examination, riya = published["examination"], school["riya"]
    original = results_service.current_result(examination.id, riya.id, tenant.id)
    frozen = {
        "version": original.version,
        "snapshot": dict(original.snapshot),
        "percentage": float(original.percentage),
        "total_obtained": float(original.total_obtained),
        "total_max": float(original.total_max),
        "grade": original.grade_label,
        "is_pass": original.is_pass,
        "published_at": original.published_at,
        "published_by": original.published_by_user_id,
        "revision_reason": original.revision_reason,
    }

    _correct(tenant, published, riya, 85, school)
    outcome = _revise(tenant, published, riya, head)
    assert outcome["success"] is True, outcome
    assert outcome["superseded_version"] == 1

    history = _history(tenant, examination, riya)
    assert [r.version for r in history] == [1, 2]
    first, second = history

    # Version 1: every field exactly as published.
    assert first.version == frozen["version"]
    assert first.snapshot == frozen["snapshot"]
    assert float(first.percentage) == frozen["percentage"]
    assert float(first.total_obtained) == frozen["total_obtained"]
    assert float(first.total_max) == frozen["total_max"]
    assert first.grade_label == frozen["grade"]
    assert first.is_pass == frozen["is_pass"]
    assert first.published_at == frozen["published_at"]
    assert first.published_by_user_id == frozen["published_by"]
    assert first.revision_reason == frozen["revision_reason"]
    assert first.is_current is False

    # Version 2: the corrected arithmetic, not yet stated.
    assert second.is_current is True
    assert second.published_at is None
    assert second.published_by_user_id is None
    assert second.revision_reason == "Re-check upheld"
    assert float(second.percentage) == 85.0
    assert second.grade_label == "A"          # was B at 70
    assert second.snapshot["papers"][0]["marks"] == 85.0


def test_the_school_word_stays_version_one_until_the_revision_is_published(
    ctx, tenant, school, published, head, anyone_manages
):
    """The distinction Part 6 turns on. `current_result` is the working figure;
    `official_result` is what a parent has been told."""
    examination, riya = published["examination"], school["riya"]
    _correct(tenant, published, riya, 85, school)
    _revise(tenant, published, riya, head)

    assert results_service.current_result(
        examination.id, riya.id, tenant.id
    ).version == 2
    official = revision_service.official_result(examination.id, riya.id, tenant.id)
    assert official.version == 1
    assert float(official.percentage) == 70.0

    # And the examination-level reader still shows the stated result, which an
    # `is_current` filter would have hidden the moment the revision existed.
    stated = publication_service.published_results(examination.id, tenant.id)
    assert {r.student_id: r.version for r in stated}[riya.id] == 1


def test_publishing_the_revision_makes_it_the_school_word(
    ctx, tenant, school, published, head, anyone_manages
):
    examination, riya = published["examination"], school["riya"]
    _correct(tenant, published, riya, 85, school)
    _revise(tenant, published, riya, head)

    outcome = revision_service.publish_revision(
        examination.id, riya.id, tenant.id, actor_user_id=head, commit=False,
    )
    assert outcome["success"] is True, outcome

    official = revision_service.official_result(examination.id, riya.id, tenant.id)
    assert official.version == 2
    assert official.published_at is not None
    assert official.published_by_user_id == head

    first = _history(tenant, examination, riya)[0]
    assert first.version == 1
    assert first.published_at is not None       # still records its own moment
    assert float(first.percentage) == 70.0

    stated = publication_service.published_results(examination.id, tenant.id)
    assert {r.student_id: r.version for r in stated}[riya.id] == 2


def test_the_examination_lifecycle_does_not_move_for_a_revision(
    ctx, tenant, school, published, head, anyone_manages
):
    """It is already published; a second transition would be a second state
    machine for the same fact."""
    examination, riya = published["examination"], school["riya"]
    _correct(tenant, published, riya, 85, school)
    _revise(tenant, published, riya, head)
    revision_service.publish_revision(
        examination.id, riya.id, tenant.id, actor_user_id=head, commit=False,
    )
    assert examination.status == EXAM_PUBLISHED


# ---------------------------------------------------------------------------
# Scope: one student
# ---------------------------------------------------------------------------

def test_revising_one_student_leaves_every_other_result_untouched(
    ctx, tenant, school, published, head, anyone_manages
):
    """Provable rather than assumed: `_compute` reads one student's marks, so
    no other child's figures can depend on this one's."""
    examination = published["examination"]
    others = {
        student.id: results_service.current_result(
            examination.id, student.id, tenant.id
        )
        for student in (school["dev"], school["meera"])
    }
    before = {
        sid: (r.version, dict(r.snapshot), float(r.percentage), r.published_at)
        for sid, r in others.items()
    }

    _correct(tenant, published, school["riya"], 85, school)
    _revise(tenant, published, school["riya"], head)

    for student in (school["dev"], school["meera"]):
        history = _history(tenant, examination, student)
        assert [r.version for r in history] == [1], "another student was versioned"
        row = history[0]
        version, snapshot, percentage, published_at = before[student.id]
        assert row.version == version
        assert row.snapshot == snapshot
        assert float(row.percentage) == percentage
        assert row.published_at == published_at
        assert row.is_current is True


# ---------------------------------------------------------------------------
# What a revision requires
# ---------------------------------------------------------------------------

def test_a_revision_needs_an_approved_correction_behind_it(
    ctx, tenant, school, published, head, anyone_manages
):
    """An official statement is not reissued because somebody pressed a button."""
    outcome = _revise(tenant, published, school["riya"], head)
    assert outcome["success"] is False
    assert outcome["code"] == "NOTHING_TO_REVISE"
    assert [r.version for r in _history(
        tenant, published["examination"], school["riya"]
    )] == [1]


def test_a_pending_correction_does_not_justify_a_revision(
    ctx, tenant, school, published, head, anyone_manages
):
    _correct(tenant, published, school["riya"], 85, school, approve=False)
    outcome = _revise(tenant, published, school["riya"], head)
    assert outcome["success"] is False
    assert outcome["code"] == "NOTHING_TO_REVISE"


def test_a_rejected_correction_does_not_justify_a_revision(
    ctx, tenant, school, published, head, anyone_manages
):
    correction = _correct(
        tenant, published, school["riya"], 85, school, approve=False
    )
    assert corrections_service.reject_correction(
        tenant.id, correction.id,
        decided_by_user_id=school["head"]["user"].id, commit=False,
    )["success"] is True

    outcome = _revise(tenant, published, school["riya"], head)
    assert outcome["success"] is False
    assert outcome["code"] == "NOTHING_TO_REVISE"
    assert float(results_service.current_result(
        published["examination"].id, school["riya"].id, tenant.id
    ).percentage) == 70.0


def test_a_revision_must_say_why(
    ctx, tenant, school, published, head, anyone_manages
):
    _correct(tenant, published, school["riya"], 85, school)
    outcome = _revise(tenant, published, school["riya"], head, reason="   ")
    assert outcome["success"] is False
    assert outcome["code"] == "REASON_REQUIRED"


def test_an_unpublished_result_is_recalculated_not_revised(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 70)
    _calc(tenant, examination, school["riya"], head)

    outcome = revision_service.revise_result(
        examination.id, school["riya"].id, tenant.id,
        reason="No", actor_user_id=head, commit=False,
    )
    assert outcome["success"] is False
    assert outcome["code"] == "WRONG_STATUS"      # examination is not published


def test_a_student_with_no_result_cannot_be_revised(
    ctx, db_session, tenant, year, school, published, head, anyone_manages
):
    from tests.test_examination_marks import _student

    stranger = _student(db_session, tenant, year, "Never Sat")
    outcome = revision_service.revise_result(
        published["examination"].id, stranger.id, tenant.id,
        reason="No", actor_user_id=head, commit=False,
    )
    assert outcome["success"] is False
    assert outcome["code"] == "RESULT_MISSING"


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------

def test_revising_needs_the_publish_permission(
    ctx, monkeypatch, tenant, school, published, head
):
    """Correcting a mark is one authority; reissuing the school's word is
    another. The catalogue calls this key "Publish and revise"."""
    _correct(tenant, published, school["riya"], 85, school)

    import modules.rbac.services as rbac

    monkeypatch.setattr(
        rbac, "has_permission",
        lambda user_id, name: name != revision_service.PERM_PUBLISH,
    )
    outcome = _revise(tenant, published, school["riya"], head)
    assert outcome["success"] is False
    assert outcome["code"] == "FORBIDDEN"
    assert [r.version for r in _history(
        tenant, published["examination"], school["riya"]
    )] == [1]


def test_publishing_a_revision_needs_the_publish_permission(
    ctx, monkeypatch, tenant, school, published, head, anyone_manages
):
    examination, riya = published["examination"], school["riya"]
    _correct(tenant, published, riya, 85, school)
    _revise(tenant, published, riya, head)

    import modules.rbac.services as rbac

    monkeypatch.setattr(rbac, "has_permission", lambda user_id, name: False)
    outcome = revision_service.publish_revision(
        examination.id, riya.id, tenant.id, actor_user_id=head, commit=False,
    )
    assert outcome["success"] is False
    assert outcome["code"] == "FORBIDDEN"
    assert results_service.current_result(
        examination.id, riya.id, tenant.id
    ).published_at is None


def test_another_schools_result_cannot_be_revised(
    ctx, db_session, tenant, school, published, head, anyone_manages
):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()
    _correct(tenant, published, school["riya"], 85, school)

    outcome = revision_service.revise_result(
        published["examination"].id, school["riya"].id, other.id,
        reason="Theirs", actor_user_id=head, commit=False,
    )
    assert outcome["success"] is False
    assert outcome["code"] == "NOT_FOUND"
    assert [r.version for r in _history(
        tenant, published["examination"], school["riya"]
    )] == [1]


# ---------------------------------------------------------------------------
# Versioning invariants
# ---------------------------------------------------------------------------

def test_versions_only_ever_go_up(
    ctx, tenant, school, published, head, anyone_manages
):
    examination, riya = published["examination"], school["riya"]

    _correct(tenant, published, riya, 85, school)
    assert _revise(tenant, published, riya, head)["success"] is True
    revision_service.publish_revision(
        examination.id, riya.id, tenant.id, actor_user_id=head, commit=False,
    )

    _correct(tenant, published, riya, 92, school)
    assert _revise(
        tenant, published, riya, head, reason="Second re-check"
    )["success"] is True

    history = _history(tenant, examination, riya)
    assert [r.version for r in history] == [1, 2, 3]
    assert [float(r.percentage) for r in history] == [70.0, 85.0, 92.0]
    assert [r.is_current for r in history] == [False, False, True]
    # Both earlier versions keep their own publication moment.
    assert history[0].published_at is not None
    assert history[1].published_at is not None
    assert history[2].published_at is None


def test_only_one_version_is_ever_current(
    ctx, tenant, school, published, head, anyone_manages
):
    examination, riya = published["examination"], school["riya"]
    _correct(tenant, published, riya, 85, school)
    _revise(tenant, published, riya, head)

    current = [
        r for r in _history(tenant, examination, riya) if r.is_current
    ]
    assert len(current) == 1
    assert current[0].version == 2


def test_a_second_current_row_is_refused_by_the_database(
    ctx, db_session, tenant, school, published
):
    """The partial unique index, not a service check, is the last line."""
    from sqlalchemy.exc import IntegrityError

    examination, riya = published["examination"], school["riya"]
    db_session.add(ExamResult(
        id=_new_id("r-"), tenant_id=tenant.id, examination_id=examination.id,
        student_id=riya.id, version=99, is_current=True,
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_republishing_an_already_published_version_is_refused(
    ctx, tenant, school, published, head, anyone_manages
):
    examination, riya = published["examination"], school["riya"]
    outcome = revision_service.publish_revision(
        examination.id, riya.id, tenant.id, actor_user_id=head, commit=False,
    )
    assert outcome["success"] is False
    assert outcome["code"] == "ALREADY_PUBLISHED"


def test_revising_twice_without_a_new_correction_is_refused(
    ctx, tenant, school, published, head, anyone_manages
):
    """The second revision has nothing behind it — the correction it would cite
    was already answered by version 2."""
    examination, riya = published["examination"], school["riya"]
    _correct(tenant, published, riya, 85, school)
    assert _revise(tenant, published, riya, head)["success"] is True

    again = _revise(tenant, published, riya, head)
    assert again["success"] is False
    assert again["code"] == "RESULT_NOT_PUBLISHED"
    assert [r.version for r in _history(tenant, examination, riya)] == [1, 2]


# ---------------------------------------------------------------------------
# A revision inherits every calculation guard
# ---------------------------------------------------------------------------

def test_a_revision_cannot_write_a_non_finite_mark(
    ctx, db_session, tenant, school, published, head, anyone_manages
):
    """The EX-03A hole must not reopen through a different door."""
    examination, riya = published["examination"], school["riya"]
    _correct(tenant, published, riya, 85, school)

    published["marks"][riya.id].marks_obtained = Decimal("NaN")
    db_session.flush()

    outcome = _revise(tenant, published, riya, head)
    assert outcome["success"] is False
    assert outcome["code"] == "MARKS_NOT_FINITE"
    assert [r.version for r in _history(tenant, examination, riya)] == [1]
    assert results_service.current_result(
        examination.id, riya.id, tenant.id
    ).version == 1


def test_a_revision_cannot_write_a_weighted_result(
    ctx, db_session, tenant, school, published, head, anyone_manages
):
    examination, riya = published["examination"], school["riya"]
    _correct(tenant, published, riya, 85, school)

    published["paper"].weight = Decimal("70")
    db_session.flush()

    outcome = _revise(tenant, published, riya, head)
    assert outcome["success"] is False
    assert outcome["code"] == "WEIGHTED_CALCULATION_UNSUPPORTED"
    assert [r.version for r in _history(tenant, examination, riya)] == [1]


def test_a_revision_regrades_against_the_bands_as_they_are_now(
    ctx, db_session, tenant, school, published, head, anyone_manages
):
    """Version 1 keeps the band it froze; version 2 resolves afresh. That is
    the same rule, not a different one — each version freezes what it saw."""
    examination, riya = published["examination"], school["riya"]
    assert _snapshot_of(tenant, examination, riya, 1)["grading"]["grade_label"] == "B"

    from modules.examinations.models import GradingBand

    band = GradingBand.query.filter_by(
        grading_scheme_id=published["scheme"].id, label="A"
    ).first()
    band.min_value = Decimal("84")
    db_session.flush()

    _correct(tenant, published, riya, 85, school)
    _revise(tenant, published, riya, head)

    assert _snapshot_of(tenant, examination, riya, 1)["grading"]["grade_label"] == "B"
    assert _snapshot_of(tenant, examination, riya, 1)["grading"]["min_value"] == 60.0
    assert _snapshot_of(tenant, examination, riya, 2)["grading"]["grade_label"] == "A"
    assert _snapshot_of(tenant, examination, riya, 2)["grading"]["min_value"] == 84.0


def test_a_correction_to_absent_revises_correctly(
    ctx, tenant, school, published, head, anyone_manages
):
    """Status changes travel through revision like any other correction."""
    examination, riya = published["examination"], school["riya"]
    mark = published["marks"][riya.id]
    raised = corrections_service.request_correction(
        tenant.id, mark.id, to_status=MARK_ABSENT, to_marks=None,
        reason="Recorded against the wrong child",
        requested_by_user_id=_teacher_of_maths(school), commit=False,
    )
    corrections_service.approve_correction(
        tenant.id, raised["correction"].id,
        decided_by_user_id=school["head"]["user"].id, commit=False,
    )

    assert _revise(tenant, published, riya, head)["success"] is True
    second = _history(tenant, examination, riya)[1]
    assert float(second.percentage) == 0.0
    assert second.grade_label == "F"
    assert second.is_pass is False
    row = second.snapshot["papers"][0]
    assert row["status"] == MARK_ABSENT
    assert row["marks"] is None
    assert row["obtained"] == 0.0


# ---------------------------------------------------------------------------
# Atomicity and events
# ---------------------------------------------------------------------------

def test_a_failed_revision_leaves_nothing_behind(
    ctx, monkeypatch, tenant, school, published, head, anyone_manages
):
    examination, riya = published["examination"], school["riya"]
    _correct(tenant, published, riya, 85, school)

    def _explode():
        raise RuntimeError("database went away mid-revision")

    monkeypatch.setattr(db.session, "flush", _explode)
    with pytest.raises(RuntimeError):
        _revise(tenant, published, riya, head)
    monkeypatch.undo()

    rows = ExamResult.query.filter_by(
        examination_id=examination.id, student_id=riya.id
    ).all()
    assert [r.version for r in rows] == [1]
    assert rows[0].is_current is True
    assert not [
        e for e in exam_services.timeline_for(examination.id, tenant.id)
        if e.event_name == revision_service.EVENT_RESULTS_REVISED
    ]


def test_a_revision_records_one_results_revised_event(
    ctx, tenant, school, published, head, anyone_manages
):
    examination, riya = published["examination"], school["riya"]
    _correct(tenant, published, riya, 85, school)
    _revise(tenant, published, riya, head)

    revised = [
        e for e in exam_services.timeline_for(examination.id, tenant.id)
        if e.event_name == revision_service.EVENT_RESULTS_REVISED
    ]
    assert len(revised) == 1
    assert revised[0].actor_user_id == head
    assert "version 1 → 2" in revised[0].note
    assert riya.id in revised[0].note


def test_publishing_a_revision_records_results_published(
    ctx, tenant, school, published, head, anyone_manages
):
    """Three distinct events, three distinct facts."""
    examination, riya = published["examination"], school["riya"]
    _correct(tenant, published, riya, 85, school)
    _revise(tenant, published, riya, head)
    revision_service.publish_revision(
        examination.id, riya.id, tenant.id, actor_user_id=head, commit=False,
    )

    names = [
        e.event_name for e in exam_services.timeline_for(examination.id, tenant.id)
    ]
    assert names.count(corrections_service.EVENT_MARKS_CORRECTED) == 1
    assert names.count(revision_service.EVENT_RESULTS_REVISED) == 1
    assert names.count(revision_service.EVENT_RESULTS_PUBLISHED) == 2  # first + revision


def test_revision_takes_a_row_lock_on_the_examination(
    ctx, tenant, school, published, head, anyone_manages
):
    """As with publication, a genuine two-connection race is not testable in a
    suite that runs inside one rolled-back transaction. What is verifiable is
    that the guarding read asks for the lock."""
    _correct(tenant, published, school["riya"], 85, school)
    statements = []

    from sqlalchemy import event

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db.session.get_bind()
    event.listen(engine, "before_cursor_execute", _record)
    try:
        assert _revise(tenant, published, school["riya"], head)["success"] is True
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert [
        s for s in statements
        if "FROM examinations" in s and "FOR UPDATE" in s
    ], "the examination was read without FOR UPDATE"


def test_a_cancelled_examination_has_nothing_to_revise(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    assert exam_services.cancel_examination(
        examination.id, tenant.id, reason="Flood", commit=False
    )["success"] is True

    outcome = revision_service.revise_result(
        examination.id, school["riya"].id, tenant.id,
        reason="No", actor_user_id=head, commit=False,
    )
    assert outcome["success"] is False
    assert outcome["code"] == "WRONG_STATUS"


def test_revision_pending_reports_the_disagreement_window(
    ctx, tenant, school, published, head, anyone_manages
):
    examination, riya = published["examination"], school["riya"]
    assert revision_service.revision_pending(
        examination.id, riya.id, tenant.id
    ) is False

    _correct(tenant, published, riya, 85, school)
    assert revision_service.revision_pending(
        examination.id, riya.id, tenant.id
    ) is True

    _revise(tenant, published, riya, head)
    # Version 2 is unpublished, so there is no published result to disagree with.
    assert revision_service.revision_pending(
        examination.id, riya.id, tenant.id
    ) is False
