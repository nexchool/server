"""Publishing an examination's results.

Every test here asserts what is in the database afterwards, not what the call
returned. A refusal that still stamped half a cohort would pass a
return-value-only test and be exactly the bug worth catching.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from core.database import db
from modules.examinations import (
    publication_service,
    results_service,
    services as exam_services,
)
from modules.examinations.models import (
    EXAM_CANCELLED,
    EXAM_DRAFT,
    EXAM_MARKS_ENTRY,
    EXAM_PUBLISHED,
    EXAM_SCHEDULED,
    MARK_ABSENT,
    MARK_EXEMPTED,
    MARK_MALPRACTICE,
    MARK_PRESENT,
    ExamMark,
    ExamResult,
)

from tests.test_examination_marks import (  # noqa: F401
    _new_id,
    _offering,
    _student,
    _enroll,
    _teacher_of_maths,
    ctx,
    cycles,
    exam_type,
    only_teachers_may,
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

EVENT_PUBLISHED = exam_services.EVENT_RESULTS_PUBLISHED


def _publish(tenant, examination, actor):
    return publication_service.publish_results(
        examination.id, tenant.id, actor_user_id=actor, commit=False,
    )


def _events(tenant, examination, name=EVENT_PUBLISHED):
    return [
        e for e in exam_services.timeline_for(examination.id, tenant.id)
        if e.event_name == name
    ]


def _results(tenant, examination):
    return ExamResult.query.filter_by(
        tenant_id=tenant.id, examination_id=examination.id
    ).all()



def _second_section(db_session, tenant, year, cycles, label="10B"):
    """Another section of the same cycle, so one examination can span two."""
    from modules.classes.models import Class

    row = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section=label,
        name=f"Section {label}", academic_year_id=year.id,
        academic_cycle_id=cycles["main"].id,
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def marked(ctx, tenant, cycles, exam_type, school, head, anyone_manages):
    """An examination in marks_entry with every student marked and calculated.

    Riya, Dev and Meera are all enrolled in 10A, so all three are the cohort.
    """
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A", 60, 100, is_pass=True, sequence=1)
    _band(tenant, scheme, "F", 0, 59.999, is_pass=False, sequence=2)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    for student, marks in ((school["riya"], 88), (school["dev"], 70),
                           (school["meera"], 50)):
        _mark(tenant, paper, student, MARK_PRESENT, marks)

    assert results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )["success"] is True
    return {"examination": examination, "paper": paper, "scheme": scheme}


# ---------------------------------------------------------------------------
# A. Successful publication
# ---------------------------------------------------------------------------

def test_publishing_stamps_every_result_and_moves_the_examination(
    ctx, tenant, school, marked, head, anyone_manages
):
    examination = marked["examination"]
    before = {r.student_id: dict(r.snapshot) for r in _results(tenant, examination)}

    outcome = _publish(tenant, examination, head)
    assert outcome["success"] is True, outcome
    assert outcome["published"] == 3

    rows = _results(tenant, examination)
    assert len(rows) == 3
    for row in rows:
        assert row.published_at is not None
        assert row.published_by_user_id == head
        assert row.is_current is True
        assert row.version == 1
        # Publication says *when*, never *what*.
        assert row.snapshot == before[row.student_id]

    assert examination.status == EXAM_PUBLISHED
    assert len(_events(tenant, examination)) == 1


def test_every_result_carries_the_same_publication_moment(
    ctx, tenant, marked, head, anyone_manages
):
    """One act, one timestamp — a cohort published in a loop with `utc_now()`
    per row would disagree with itself by milliseconds."""
    _publish(tenant, marked["examination"], head)
    stamps = {r.published_at for r in _results(tenant, marked["examination"])}
    assert len(stamps) == 1


# ---------------------------------------------------------------------------
# B/C/D. What refuses, and what the database looks like afterwards
# ---------------------------------------------------------------------------

def test_an_incomplete_result_stops_the_whole_publication(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """Riya and Dev are markable; Meera's paper has no mark. 'Not yet entered'
    cannot become the school's word, and neither can the other two."""
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)
    _mark(tenant, paper, school["dev"], MARK_PRESENT, 70)
    results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )

    outcome = _publish(tenant, examination, head)
    assert outcome["success"] is False
    assert outcome["code"] == "RESULT_INCOMPLETE"

    assert examination.status == EXAM_MARKS_ENTRY
    assert all(r.published_at is None for r in _results(tenant, examination))
    assert _events(tenant, examination) == []


def test_a_grade_the_scheme_could_not_produce_stops_publication(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """Bands covering 91-100 and 0-32.99 leave a gap. A school that configured
    a scheme and got no grade out of it must not publish that as official."""
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A1", 91, 100, sequence=1)
    _band(tenant, scheme, "F", 0, 32.99, is_pass=False, sequence=2)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    for student in (school["riya"], school["dev"], school["meera"]):
        _mark(tenant, paper, student, MARK_PRESENT, 60)     # in the gap
    results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )

    outcome = _publish(tenant, examination, head)
    assert outcome["success"] is False
    assert outcome["code"] == "GRADE_UNRESOLVED"
    assert examination.status == EXAM_MARKS_ENTRY
    assert _events(tenant, examination) == []


def test_no_pass_rule_configured_still_publishes(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """The other side of that rule, and the reason it is not a blunt "refuse
    when is_pass is None": a school reporting marks only has configured no
    grading scheme and no pass marks, so `is_pass` is None by its own choice
    (ADR-020 §B). Refusing here would leave it unable to publish anything.
    """
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    for student, marks in ((school["riya"], 88), (school["dev"], 70),
                           (school["meera"], 50)):
        _mark(tenant, paper, student, MARK_PRESENT, marks)
    results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )

    outcome = _publish(tenant, examination, head)
    assert outcome["success"] is True, outcome
    rows = _results(tenant, examination)
    assert all(r.is_pass is None for r in rows)
    assert all(r.published_at is not None for r in rows)


def test_a_missing_result_stops_publication(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """Publication never calculates on somebody's behalf — that would make it a
    moment when the figures can still change."""
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    for student, marks in ((school["riya"], 88), (school["dev"], 70),
                           (school["meera"], 50)):
        _mark(tenant, paper, student, MARK_PRESENT, marks)
    # Only one student calculated.
    _calc(tenant, examination, school["riya"], head)

    outcome = _publish(tenant, examination, head)
    assert outcome["success"] is False
    assert outcome["code"] == "RESULT_MISSING"
    assert examination.status == EXAM_MARKS_ENTRY
    assert all(r.published_at is None for r in _results(tenant, examination))


def test_the_readiness_report_lists_everyone_who_blocks(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """A cohort refused one student at a time is a screen nobody can use."""
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)
    results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )

    readiness = publication_service.publication_readiness(examination.id, tenant.id)
    assert readiness["ready"] is False
    assert readiness["cohort"] == 3
    blocked = {b["student_id"]: b["code"] for b in readiness["blocked"]}
    assert blocked == {
        school["dev"].id: "RESULT_INCOMPLETE",
        school["meera"].id: "RESULT_INCOMPLETE",
    }


# ---------------------------------------------------------------------------
# E/F. Authorization and tenancy
# ---------------------------------------------------------------------------

def test_publishing_needs_the_publish_permission(
    ctx, monkeypatch, tenant, marked, head
):
    """`assessment.manage` runs marking; it does not tell the parents."""
    import modules.rbac.services as rbac

    monkeypatch.setattr(
        rbac, "has_permission",
        lambda user_id, name: name != publication_service.PERM_PUBLISH,
    )
    examination = marked["examination"]
    outcome = _publish(tenant, examination, head)

    assert outcome["success"] is False
    assert outcome["code"] == "FORBIDDEN"
    assert examination.status == EXAM_MARKS_ENTRY
    assert all(r.published_at is None for r in _results(tenant, examination))
    assert _events(tenant, examination) == []


def test_another_schools_examination_cannot_be_published(
    ctx, db_session, tenant, marked, head, anyone_manages
):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    examination = marked["examination"]
    outcome = publication_service.publish_results(
        examination.id, other.id, actor_user_id=head, commit=False,
    )
    assert outcome["success"] is False
    assert outcome["code"] == "NOT_FOUND"
    assert examination.status == EXAM_MARKS_ENTRY
    assert all(r.published_at is None for r in _results(tenant, examination))


# ---------------------------------------------------------------------------
# G. Lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stop_at", [EXAM_DRAFT, EXAM_SCHEDULED])
def test_publishing_before_marking_is_refused(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages, stop_at
):
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], open_marks=False)
    if stop_at == EXAM_SCHEDULED:
        exam_services.schedule_examination(examination.id, tenant.id, commit=False)

    outcome = _publish(tenant, examination, head)
    assert outcome["success"] is False
    assert outcome["code"] == "INVALID_TRANSITION"
    assert examination.status == stop_at
    assert _events(tenant, examination) == []


def test_a_cancelled_examination_cannot_be_published(
    ctx, tenant, marked, head, anyone_manages
):
    examination = marked["examination"]
    assert exam_services.cancel_examination(
        examination.id, tenant.id, reason="Flood", commit=False
    )["success"] is True

    outcome = _publish(tenant, examination, head)
    assert outcome["success"] is False
    assert outcome["code"] == "INVALID_TRANSITION"
    assert examination.status == EXAM_CANCELLED
    assert all(r.published_at is None for r in _results(tenant, examination))


def test_publishing_twice_is_refused_and_adds_no_second_event(
    ctx, tenant, marked, head, anyone_manages
):
    examination = marked["examination"]
    assert _publish(tenant, examination, head)["success"] is True
    stamps = {r.id: r.published_at for r in _results(tenant, examination)}

    again = _publish(tenant, examination, head)
    assert again["success"] is False
    assert again["code"] == "INVALID_TRANSITION"

    assert len(_events(tenant, examination)) == 1
    assert {r.id: r.published_at for r in _results(tenant, examination)} == stamps


# ---------------------------------------------------------------------------
# H/I. What publication froze stays frozen
# ---------------------------------------------------------------------------

def test_changing_a_mark_after_publication_does_not_move_the_result(
    ctx, db_session, tenant, school, marked, head, anyone_manages
):
    examination = marked["examination"]
    _publish(tenant, examination, head)

    riya = results_service.current_result(
        examination.id, school["riya"].id, tenant.id
    )
    frozen = dict(riya.snapshot)

    mark = ExamMark.query.filter_by(
        exam_paper_id=marked["paper"].id, student_id=school["riya"].id
    ).first()
    mark.marks_obtained = Decimal("12")
    db_session.flush()

    # EX-03A already refuses; this is the regression test that it still does.
    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["success"] is False
    assert outcome["code"] == "RESULT_PUBLISHED"

    db_session.refresh(riya)
    assert float(riya.percentage) == 88.0
    assert riya.grade_label == "A"
    assert riya.snapshot == frozen


def test_redrawing_the_grading_bands_after_publication_changes_nothing(
    ctx, db_session, tenant, school, marked, head, anyone_manages
):
    examination = marked["examination"]
    _publish(tenant, examination, head)

    meera = results_service.current_result(
        examination.id, school["meera"].id, tenant.id
    )
    assert meera.grade_label == "F"          # 50% under the 60 pass line
    frozen = dict(meera.snapshot)

    from modules.examinations.models import GradingBand

    for band in GradingBand.query.filter_by(
        grading_scheme_id=marked["scheme"].id
    ).all():
        band.min_value = Decimal("0")
        band.max_value = Decimal("100")
        band.label = "REDRAWN"
        band.is_pass = True
    db_session.flush()
    db_session.refresh(meera)

    assert meera.grade_label == "F"
    assert meera.is_pass is False
    assert meera.snapshot == frozen
    # 60.00, not 59.999: band bounds are Numeric(6,2) — see the precision
    # test below. What matters here is that the frozen value did not move.
    assert meera.snapshot["grading"]["max_value"] == 60.0


def test_publication_leaves_the_raw_marks_alone(
    ctx, tenant, school, marked, head, anyone_manages
):
    paper_id = marked["paper"].id
    before = {
        m.student_id: (m.status, m.marks_obtained)
        for m in ExamMark.query.filter_by(exam_paper_id=paper_id).all()
    }
    _publish(tenant, marked["examination"], head)
    after = {
        m.student_id: (m.status, m.marks_obtained)
        for m in ExamMark.query.filter_by(exam_paper_id=paper_id).all()
    }
    assert after == before


# ---------------------------------------------------------------------------
# J/K/L/M. Real examination shapes
# ---------------------------------------------------------------------------

def test_theory_and_practical_publish_as_one_result(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 70, component="Theory", day=6),
        _paper_spec(school["maths"], 30, component="Practical", day=7),
    ])
    theory, practical = _papers(examination, tenant)
    for student in (school["riya"], school["dev"], school["meera"]):
        _mark(tenant, theory, student, MARK_PRESENT, 56)
        _mark(tenant, practical, student, MARK_PRESENT, 24)
    results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )

    assert _publish(tenant, examination, head)["published"] == 3
    riya = results_service.current_result(
        examination.id, school["riya"].id, tenant.id
    )
    assert float(riya.percentage) == 80.0
    assert len(riya.snapshot["papers"]) == 2


def test_one_examination_across_two_classes_publishes_both(
    ctx, db_session, tenant, year, cycles, exam_type, school, head, anyone_manages
):
    """Grade 10A and the JEE batch sit different papers of the same event; each
    student's result carries only their own."""
    other_section = _second_section(db_session, tenant, year, cycles)
    other_offering = _offering(db_session, tenant, other_section, "Physics")
    batch_student = _student(db_session, tenant, year, "Other Section Only")
    _enroll(db_session, tenant, batch_student, other_section, year)
    # Meera holds a second, additional enrollment, so she sits both sections'
    # papers — the EX-02A rule, unchanged.
    _enroll(db_session, tenant, school["meera"], other_section, year,
            kind="additional")

    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 100, day=6),
        {"class_subject_id": other_offering.id, "max_marks": 200,
         "pass_marks": None, "component_label": "",
         "exam_date": date(2026, 7, 7)},
    ], open_marks=False)
    exam_services.schedule_examination(examination.id, tenant.id, commit=False)
    exam_services.open_marks_entry(examination.id, tenant.id, commit=False)

    maths, physics = _papers(examination, tenant)
    for student in (school["riya"], school["dev"], school["meera"]):
        _mark(tenant, maths, student, MARK_PRESENT, 80)
    for student in (school["meera"], batch_student):
        _mark(tenant, physics, student, MARK_PRESENT, 150)
    results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )

    outcome = _publish(tenant, examination, head)
    assert outcome["success"] is True, outcome
    assert outcome["published"] == 4          # three in 10A plus the batch-only child

    batch = results_service.current_result(
        examination.id, batch_student.id, tenant.id
    )
    assert [p["paper_id"] for p in batch.snapshot["papers"]] == [physics.id]

    # Meera sits both, because she holds both enrollments.
    meera = results_service.current_result(
        examination.id, school["meera"].id, tenant.id
    )
    assert len(meera.snapshot["papers"]) == 2


def test_absent_exempted_and_malpractice_publish_exactly_as_calculated(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 100, day=6),
        _paper_spec(school["science"], 100, day=8),
    ])
    maths, science = _papers(examination, tenant)
    _mark(tenant, maths, school["riya"], MARK_PRESENT, 80)
    _mark(tenant, science, school["riya"], MARK_ABSENT)
    _mark(tenant, maths, school["dev"], MARK_PRESENT, 80)
    _mark(tenant, science, school["dev"], MARK_EXEMPTED)
    _mark(tenant, maths, school["meera"], MARK_PRESENT, 80)
    _mark(tenant, science, school["meera"], MARK_MALPRACTICE)
    results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )
    before = {
        r.student_id: dict(r.snapshot) for r in _results(tenant, examination)
    }

    assert _publish(tenant, examination, head)["published"] == 3

    for row in _results(tenant, examination):
        assert row.snapshot == before[row.student_id]

    riya = results_service.current_result(
        examination.id, school["riya"].id, tenant.id
    )
    dev = results_service.current_result(
        examination.id, school["dev"].id, tenant.id
    )
    assert float(riya.percentage) == 40.0     # absent keeps its denominator
    assert float(dev.percentage) == 80.0      # exempted leaves the calculation


# ---------------------------------------------------------------------------
# The degenerate case, stated rather than stumbled into
# ---------------------------------------------------------------------------

def test_an_examination_nobody_sits_can_still_close(
    ctx, db_session, tenant, year, cycles, exam_type, school, head, anyone_manages
):
    """A section with no students has an empty cohort, so there is nothing to
    refuse. Publishing is allowed — the alternative would strand such an
    examination in marks entry forever with only cancellation available — and
    the event says plainly that it published nothing.
    """
    empty_section = _second_section(db_session, tenant, year, cycles, "10Z")
    empty = _offering(db_session, tenant, empty_section, "Nobody")
    examination = _exam(tenant, cycles, exam_type, school, [
        {"class_subject_id": empty.id, "max_marks": 100, "pass_marks": None,
         "component_label": "", "exam_date": date(2026, 7, 6)},
    ])

    outcome = _publish(tenant, examination, head)
    assert outcome["success"] is True, outcome
    assert outcome["published"] == 0
    assert examination.status == EXAM_PUBLISHED
    assert _results(tenant, examination) == []
    assert "no results" in _events(tenant, examination)[0].note


def test_publication_is_recorded_once_with_a_count(
    ctx, tenant, marked, head, anyone_manages
):
    _publish(tenant, marked["examination"], head)
    events = _events(tenant, marked["examination"])
    assert len(events) == 1
    assert events[0].actor_user_id == head
    assert "3 result(s) published" in events[0].note


def test_band_bounds_are_stored_at_two_decimals_while_percentages_carry_three(
    ctx, db_session, tenant, cycles, exam_type, school, head, anyone_manages
):
    """A precision mismatch the schema allows and no school would expect.

    `grading_bands.min_value`/`max_value` are Numeric(6,2); `exam_results.
    percentage` is Numeric(6,3). So a school writing the common "up to 59.999"
    upper bound gets **60.00** stored, which silently overlaps the band that
    starts at 60 — an overlap it never authored.

    Publication is not the place to fix this (grading configuration has no
    surface yet, debt 53), but the behaviour must be defined and stated:
    the overlap resolves by lowest `sequence`, exactly as an authored one does,
    so a student on the boundary gets the higher band rather than an error.
    """
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A", 60, 100, is_pass=True, sequence=1)
    _band(tenant, scheme, "F", 0, 59.999, is_pass=False, sequence=2)
    db_session.flush()

    stored = {b.label: float(b.max_value) for b in scheme.bands}
    assert stored["F"] == 60.0, "the schema rounded the bound the school wrote"

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    for student in (school["riya"], school["dev"], school["meera"]):
        _mark(tenant, paper, student, MARK_PRESENT, 60)      # exactly 60.000%
    results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )

    riya = results_service.current_result(
        examination.id, school["riya"].id, tenant.id
    )
    assert float(riya.percentage) == 60.0
    assert riya.grade_label == "A"           # lowest sequence of the two matches
    assert riya.snapshot["grading"]["band_warning"] is not None

    # And because the grade resolved, the result is still publishable — the
    # overlap is a configuration smell, not an unresolvable one.
    assert _publish(tenant, examination, head)["success"] is True


def test_publication_seals_the_published_result_not_the_marks(
    ctx, tenant, school, marked, head, anyone_manages
):
    """What publication seals, and what it does not (EX-03C changed this).

    A correction against a published examination is now **allowed** — it is the
    first half of a revision, and refusing it was the dead end debt 55 named.
    What stays sealed is the published *result*: approving the correction moves
    the mark and leaves the figures exactly as published, and recalculation
    still refuses. Only a revision creates a new version.
    """
    from modules.examinations import corrections_service, marks_service, revision_service

    examination = marked["examination"]
    mark = ExamMark.query.filter_by(
        exam_paper_id=marked["paper"].id, student_id=school["riya"].id
    ).first()
    marks_service.lock_paper(
        marked["paper"].id, tenant.id,
        actor_user_id=school["head"]["user"].id, commit=False,
    )
    assert _publish(tenant, examination, head)["success"] is True
    assert revision_service.revision_pending(
        examination.id, school["riya"].id, tenant.id
    ) is False

    correction = corrections_service.request_correction(
        tenant.id, mark.id, to_status=MARK_PRESENT, to_marks=95,
        reason="Re-totalled after publication",
        requested_by_user_id=_teacher_of_maths(school), commit=False,
    )
    assert correction["success"] is True, correction
    assert corrections_service.approve_correction(
        tenant.id, correction["correction"].id,
        decided_by_user_id=school["head"]["user"].id, commit=False,
    )["success"] is True

    # The mark moved. The published result did not.
    assert float(mark.marks_obtained) == 95.0
    riya = results_service.current_result(
        examination.id, school["riya"].id, tenant.id
    )
    assert float(riya.percentage) == 88.0
    assert riya.version == 1

    # And recalculation still refuses to write over it.
    recalc = _calc(tenant, examination, school["riya"], head)
    assert recalc["success"] is False
    assert recalc["code"] == "RESULT_PUBLISHED"

    # The disagreement is visible rather than silent.
    assert revision_service.revision_pending(
        examination.id, school["riya"].id, tenant.id
    ) is True


# ---------------------------------------------------------------------------
# Edges named in the EX-03B brief that the first pass did not reach
# ---------------------------------------------------------------------------

def test_an_examination_with_no_papers_can_never_reach_publication(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """Publication needs no rule for this, because EX-01 already closed it
    upstream: `schedule_examination` refuses `NO_PAPERS`, so a paperless
    examination cannot leave draft, let alone reach marks entry."""
    created = exam_services.create_examination(
        tenant_id=tenant.id, academic_cycle_id=cycles["main"].id,
        exam_type_id=exam_type.id, name=f"Empty-{uuid.uuid4().hex[:6]}",
        commit=False,
    )
    assert created["success"] is True, created
    examination = created["examination"]

    scheduled = exam_services.schedule_examination(
        examination.id, tenant.id, commit=False
    )
    assert scheduled["success"] is False
    assert scheduled["code"] == "NO_PAPERS"
    assert examination.status == EXAM_DRAFT

    outcome = _publish(tenant, examination, head)
    assert outcome["success"] is False
    assert outcome["code"] == "INVALID_TRANSITION"


def test_a_student_exempted_from_everything_publishes(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """`total_max == 0`, so there is no percentage and no grade — and that is a
    complete result, not an incomplete one."""
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    for student in (school["riya"], school["dev"], school["meera"]):
        _mark(tenant, paper, student, MARK_EXEMPTED)
    results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )

    assert _publish(tenant, examination, head)["success"] is True
    riya = results_service.current_result(
        examination.id, school["riya"].id, tenant.id
    )
    assert float(riya.total_max) == 0.0
    assert riya.percentage is None
    assert riya.grade_label is None
    assert riya.published_at is not None
    assert riya.snapshot["complete"] is True


def test_publishing_one_examination_leaves_another_alone(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """Two examinations over the same students, in the same cycle."""
    first = _exam(tenant, cycles, exam_type, school,
                  [_paper_spec(school["maths"], 100, day=6)])
    second = _exam(tenant, cycles, exam_type, school,
                   [_paper_spec(school["science"], 100, day=9)])
    for examination in (first, second):
        paper = _papers(examination, tenant)[0]
        for student in (school["riya"], school["dev"], school["meera"]):
            _mark(tenant, paper, student, MARK_PRESENT, 70)
        results_service.calculate_results(
            examination.id, tenant_id=tenant.id, actor_user_id=head,
            commit=False,
        )

    assert _publish(tenant, first, head)["success"] is True

    assert second.status == EXAM_MARKS_ENTRY
    assert all(r.published_at is None for r in _results(tenant, second))
    assert _events(tenant, second) == []
    assert all(r.published_at is not None for r in _results(tenant, first))


def test_a_failure_after_validation_rolls_back_the_stamps(
    ctx, monkeypatch, tenant, marked, head, anyone_manages
):
    """The savepoint's real job. Validation passes, the transition is made and
    rows are stamped — then something fails. Nothing may survive."""
    examination = marked["examination"]
    examination_id = examination.id

    def _explode():
        raise RuntimeError("database went away mid-publication")

    monkeypatch.setattr(db.session, "flush", _explode)
    with pytest.raises(RuntimeError):
        _publish(tenant, examination, head)
    monkeypatch.undo()

    from modules.examinations.models import Examination

    reread = Examination.query.filter_by(id=examination_id).first()
    assert reread.status == EXAM_MARKS_ENTRY
    assert all(
        r.published_at is None
        for r in ExamResult.query.filter_by(examination_id=examination_id).all()
    )
    assert _events(tenant, reread) == []


def test_publication_takes_a_row_lock_on_the_examination(
    ctx, tenant, marked, head, anyone_manages
):
    """A genuine two-connection race is not testable here — the suite runs
    inside one transaction that is rolled back, so a second connection would
    never see the first's uncommitted rows. What *is* verifiable is that the
    read guarding the decision asks for the lock."""
    statements = []

    from sqlalchemy import event

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db.session.get_bind()
    event.listen(engine, "before_cursor_execute", _record)
    try:
        assert _publish(tenant, marked["examination"], head)["success"] is True
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    locking = [
        s for s in statements
        if "FROM examinations" in s and "FOR UPDATE" in s
    ]
    assert locking, "the examination was read without FOR UPDATE"
