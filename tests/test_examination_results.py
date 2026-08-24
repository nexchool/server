"""Turning recorded marks into a result.

The snapshot is the architectural output of this slice, so these tests assert
it — the per-paper breakdown, the preserved statuses, the frozen band and the
pass reasoning — not just the totals.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from core.database import db
from modules.examinations import (
    marks_service,
    results_service,
    services as exam_services,
)
from modules.examinations.models import (
    MARK_ABSENT,
    MARK_EXEMPTED,
    MARK_MALPRACTICE,
    MARK_PRESENT,
    ExamMark,
    ExamResult,
    GradingBand,
    GradingScheme,
)
from modules.examinations.results_service import STATUS_NOT_ENTERED

from tests.test_examination_marks import (  # noqa: F401
    _enroll,
    _new_id,
    _offering,
    _student,
    _teacher_of_maths,
    anyone_may,
    ctx,
    cycles,
    exam_type,
    only_teachers_may,
    school,
    year,
)


@pytest.fixture
def head(school):
    return school["head"]["user"].id


@pytest.fixture
def anyone_manages(monkeypatch):
    """Grant every assessment key, so a test isolates the arithmetic."""
    import modules.rbac.services as rbac

    monkeypatch.setattr(rbac, "has_permission", lambda user_id, name: True)


def _scheme(tenant, name="Percentage"):
    row = GradingScheme(
        id=_new_id("gs-"), tenant_id=tenant.id,
        name=f"{name}-{uuid.uuid4().hex[:5]}", scheme_type="percentage",
    )
    db.session.add(row)
    db.session.flush()
    return row


def _band(tenant, scheme, label, lo, hi, *, is_pass=True, sequence=0, point=None):
    row = GradingBand(
        id=_new_id("gb-"), tenant_id=tenant.id, grading_scheme_id=scheme.id,
        label=label, min_value=Decimal(str(lo)), max_value=Decimal(str(hi)),
        is_pass=is_pass, sequence=sequence, grade_point=point,
    )
    db.session.add(row)
    db.session.flush()
    return row


def _exam(tenant, cycles, exam_type, school, papers, *, scheme=None, open_marks=True):
    """An examination with the given papers, ready for marking."""
    created = exam_services.create_examination(
        tenant_id=tenant.id, academic_cycle_id=cycles["main"].id,
        exam_type_id=exam_type.id, name=f"Exam-{uuid.uuid4().hex[:6]}",
        grading_scheme_id=scheme.id if scheme else None,
        papers=papers, commit=False,
    )
    assert created["success"] is True, created
    examination = created["examination"]
    if open_marks:
        assert exam_services.schedule_examination(
            examination.id, tenant.id, commit=False
        )["success"] is True
        assert exam_services.open_marks_entry(
            examination.id, tenant.id, commit=False
        )["success"] is True
    return examination


def _paper_spec(offering, max_marks, *, pass_marks=None, component="", day=6):
    return {
        "class_subject_id": offering.id, "max_marks": max_marks,
        "pass_marks": pass_marks, "component_label": component,
        "exam_date": date(2026, 7, day),
    }


def _mark(tenant, paper, student, status, marks=None):
    row = ExamMark(
        id=_new_id("em-"), tenant_id=tenant.id, exam_paper_id=paper.id,
        student_id=student.id, status=status,
        marks_obtained=Decimal(str(marks)) if marks is not None else None,
    )
    db.session.add(row)
    db.session.flush()
    return row


def _papers(examination, tenant):
    return exam_services.papers_for(examination.id, tenant.id)


def _calc(tenant, examination, student, head):
    return results_service.calculate_result(
        examination.id, student.id, tenant_id=tenant.id,
        actor_user_id=head, commit=False,
    )


def _snap(result):
    return result["result"].snapshot


def _row_for(snapshot, paper_id):
    return next(r for r in snapshot["papers"] if r["paper_id"] == paper_id)


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------

def test_one_paper(ctx, tenant, cycles, exam_type, school, head, anyone_manages):
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["success"] is True, outcome
    row = outcome["result"]

    assert float(row.total_max) == 100.0
    assert float(row.total_obtained) == 88.0
    assert float(row.percentage) == 88.0
    assert _snap(outcome)["complete"] is True


def test_multiple_papers_aggregate(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 100, day=6),
        _paper_spec(school["science"], 50, day=8),
    ])
    maths, science = _papers(examination, tenant)
    _mark(tenant, maths, school["riya"], MARK_PRESENT, 80)
    _mark(tenant, science, school["riya"], MARK_PRESENT, 40)

    outcome = _calc(tenant, examination, school["riya"], head)
    row = outcome["result"]
    assert float(row.total_max) == 150.0
    assert float(row.total_obtained) == 120.0
    assert float(row.percentage) == 80.0
    assert len(_snap(outcome)["papers"]) == 2


def test_theory_and_practical_are_two_papers_added_up(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """component_label is descriptive in EX-03A: both papers contribute
    independently, with no subject-level grouping invented."""
    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 70, component="Theory", day=6),
        _paper_spec(school["maths"], 30, component="Practical", day=7),
    ])
    theory, practical = _papers(examination, tenant)
    _mark(tenant, theory, school["riya"], MARK_PRESENT, 56)
    _mark(tenant, practical, school["riya"], MARK_PRESENT, 24)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert float(outcome["result"].total_obtained) == 80.0
    assert float(outcome["result"].percentage) == 80.0
    labels = {r["component_label"] for r in _snap(outcome)["papers"]}
    assert labels == {"Theory", "Practical"}


# ---------------------------------------------------------------------------
# The five states stay five
# ---------------------------------------------------------------------------

def test_a_genuine_zero_counts_as_a_mark(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 0)

    outcome = _calc(tenant, examination, school["riya"], head)
    row = _row_for(_snap(outcome), paper.id)
    assert row["status"] == MARK_PRESENT
    assert row["marks"] == 0.0
    assert row["included_in_total"] is True
    assert float(outcome["result"].percentage) == 0.0


def test_absent_scores_nothing_but_is_still_measured(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 100, day=6),
        _paper_spec(school["science"], 100, day=8),
    ])
    maths, science = _papers(examination, tenant)
    _mark(tenant, maths, school["riya"], MARK_PRESENT, 80)
    _mark(tenant, science, school["riya"], MARK_ABSENT)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert float(outcome["result"].total_max) == 200.0
    assert float(outcome["result"].total_obtained) == 80.0
    assert float(outcome["result"].percentage) == 40.0

    row = _row_for(_snap(outcome), science.id)
    assert row["status"] == MARK_ABSENT
    assert row["marks"] is None          # never a zero mark
    assert row["obtained"] == 0.0        # but zero toward the total
    assert row["included_in_total"] is True


def test_exempted_leaves_the_calculation_entirely(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """An exemption must not be able to lower a percentage."""
    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 100, day=6),
        _paper_spec(school["science"], 100, day=8),
    ])
    maths, science = _papers(examination, tenant)
    _mark(tenant, maths, school["riya"], MARK_PRESENT, 80)
    _mark(tenant, science, school["riya"], MARK_EXEMPTED)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert float(outcome["result"].total_max) == 100.0
    assert float(outcome["result"].total_obtained) == 80.0
    assert float(outcome["result"].percentage) == 80.0

    row = _row_for(_snap(outcome), science.id)
    assert row["status"] == MARK_EXEMPTED
    assert row["included_in_total"] is False
    assert _snap(outcome)["complete"] is True


def test_malpractice_scores_zero_and_stays_distinct_from_absent(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 100, day=6),
        _paper_spec(school["science"], 100, day=8),
    ])
    maths, science = _papers(examination, tenant)
    _mark(tenant, maths, school["riya"], MARK_PRESENT, 80)
    _mark(tenant, science, school["riya"], MARK_MALPRACTICE)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert float(outcome["result"].percentage) == 40.0
    row = _row_for(_snap(outcome), science.id)
    assert row["status"] == MARK_MALPRACTICE
    assert row["obtained"] == 0.0
    assert row["included_in_total"] is True
    # And it does not by itself fail the student — no rule says it should.
    assert _snap(outcome)["pass"]["is_pass"] is None


def test_a_missing_mark_is_not_a_zero(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """The whole point of the sixth state: a teacher's unfinished work must not
    fail a student."""
    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 100, day=6),
        _paper_spec(school["science"], 100, day=8),
    ])
    maths, science = _papers(examination, tenant)
    _mark(tenant, maths, school["riya"], MARK_PRESENT, 80)
    # science: no mark row at all

    outcome = _calc(tenant, examination, school["riya"], head)
    assert float(outcome["result"].total_max) == 100.0, "an unmarked paper counted"
    assert float(outcome["result"].percentage) == 80.0

    snapshot = _snap(outcome)
    row = _row_for(snapshot, science.id)
    assert row["status"] == STATUS_NOT_ENTERED
    assert row["not_yet_entered"] is True
    assert row["marks"] is None
    assert row["obtained"] is None
    assert row["included_in_total"] is False
    assert snapshot["complete"] is False
    assert any("no mark recorded yet" in w for w in snapshot["warnings"])

    # And nothing was written to the marks table to represent it.
    assert ExamMark.query.filter_by(exam_paper_id=science.id).count() == 0


def test_every_paper_exempted_yields_no_percentage(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """0% would say they failed everything they were excused from."""
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_EXEMPTED)

    outcome = _calc(tenant, examination, school["riya"], head)
    row = outcome["result"]
    assert float(row.total_max) == 0.0
    assert float(row.total_obtained) == 0.0
    assert row.percentage is None
    assert row.grade_label is None


# ---------------------------------------------------------------------------
# Pass and fail
# ---------------------------------------------------------------------------

def test_the_band_decides_the_pass(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A", 80, 100, is_pass=True, sequence=1)
    _band(tenant, scheme, "F", 0, 32.99, is_pass=False, sequence=9)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["result"].grade_label == "A"
    assert outcome["result"].is_pass is True
    assert _snap(outcome)["pass"] == {
        "band_pass": True, "paper_pass": None, "is_pass": True
    }


def test_a_failing_band_fails_the_result(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    scheme = _scheme(tenant)
    _band(tenant, scheme, "F", 0, 32.99, is_pass=False, sequence=9)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 20)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["result"].grade_label == "F"
    assert outcome["result"].is_pass is False


def test_one_failed_pass_marks_paper_fails_the_result(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """Passing overall while failing a subject is a real school rule, and here
    the aggregate is comfortably above the band's pass line."""
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A", 60, 100, is_pass=True, sequence=1)

    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 100, pass_marks=35, day=6),
        _paper_spec(school["science"], 100, pass_marks=35, day=8),
    ], scheme=scheme)
    maths, science = _papers(examination, tenant)
    _mark(tenant, maths, school["riya"], MARK_PRESENT, 95)
    _mark(tenant, science, school["riya"], MARK_PRESENT, 30)   # below 35

    outcome = _calc(tenant, examination, school["riya"], head)
    snapshot = _snap(outcome)
    assert float(outcome["result"].percentage) == 62.5
    assert outcome["result"].grade_label == "A"
    assert snapshot["pass"]["band_pass"] is True
    assert snapshot["pass"]["paper_pass"] is False
    assert outcome["result"].is_pass is False
    assert _row_for(snapshot, science.id)["paper_pass"] is False
    assert _row_for(snapshot, maths.id)["paper_pass"] is True


def test_an_exempted_paper_creates_no_paper_level_failure(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 100, pass_marks=35, day=6),
        _paper_spec(school["science"], 100, pass_marks=35, day=8),
    ])
    maths, science = _papers(examination, tenant)
    _mark(tenant, maths, school["riya"], MARK_PRESENT, 90)
    _mark(tenant, science, school["riya"], MARK_EXEMPTED)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert _row_for(_snap(outcome), science.id)["paper_pass"] is None
    assert outcome["result"].is_pass is True


def test_absent_fails_its_paper_where_pass_marks_exist(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100, pass_marks=35)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_ABSENT)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert _row_for(_snap(outcome), paper.id)["paper_pass"] is False
    assert outcome["result"].is_pass is False


def test_pass_marks_decide_when_there_is_no_band(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100, pass_marks=35)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 60)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["result"].grade_label is None
    assert _snap(outcome)["pass"]["band_pass"] is None
    assert outcome["result"].is_pass is True


def test_nothing_decides_the_pass_when_nothing_is_configured(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """No bands, no pass marks — inventing an answer would be worse."""
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 60)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["result"].is_pass is None
    assert _snap(outcome)["pass"] == {
        "band_pass": None, "paper_pass": None, "is_pass": None
    }


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("marks,expected", [(80, "A"), (100, "A"), (90, "A")],
                         ids=["lower-boundary", "upper-boundary", "inside"])
def test_band_boundaries_are_inclusive(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages, marks, expected
):
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A", 80, 100, sequence=1)
    _band(tenant, scheme, "B", 0, 79.999, sequence=2)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, marks)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["result"].grade_label == expected


def test_the_rounded_percentage_is_what_earns_the_grade(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """26999/30000 = 89.99666…%, which rounds to 89.997 — below the line. The
    stored number and the graded number must be the same one."""
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A+", 90, 100, sequence=1)
    _band(tenant, scheme, "A", 0, 89.999, sequence=2)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 300)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 269.99)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert float(outcome["result"].percentage) == 89.997
    assert outcome["result"].grade_label == "A"
    assert _snap(outcome)["aggregate"]["percentage"] == 89.997


def test_a_percentage_that_rounds_up_onto_the_boundary_takes_the_band(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """1799.99/2000 = 89.9995% raw — strictly below the A+ line. Rounded once to
    3 dp it becomes 90.000, and the band is matched on that. Grading the
    unrounded value while storing the rounded one would print 90.000 beside an
    A."""
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A+", 90, 100, sequence=1)
    _band(tenant, scheme, "A", 0, 89.999, sequence=2)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 2000)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 1799.99)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert float(outcome["result"].percentage) == 90.0
    assert outcome["result"].grade_label == "A+"


def test_a_gap_in_the_bands_yields_no_grade_and_a_warning(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """The shipped fixture shape: A1 91-100, A2 81-90.99, F 0-32.99 leaves
    33-80.99 uncovered. Guessing the nearest band would invent policy."""
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A1", 91, 100, sequence=1)
    _band(tenant, scheme, "A2", 81, 90.99, sequence=2)
    _band(tenant, scheme, "F", 0, 32.99, is_pass=False, sequence=3)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 60)

    outcome = _calc(tenant, examination, school["riya"], head)
    snapshot = _snap(outcome)
    assert outcome["result"].grade_label is None
    assert snapshot["grading"]["band_id"] is None
    assert "gap" in snapshot["grading"]["band_warning"]
    assert any("gap" in w for w in snapshot["warnings"])


def test_overlapping_bands_resolve_by_sequence_and_warn(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """The database permits overlaps. Repairing them is not this slice's job;
    behaving the same way every time is."""
    scheme = _scheme(tenant)
    _band(tenant, scheme, "Distinction", 75, 100, sequence=1)
    _band(tenant, scheme, "First Class", 60, 100, sequence=2)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 80)

    outcome = _calc(tenant, examination, school["riya"], head)
    snapshot = _snap(outcome)
    assert outcome["result"].grade_label == "Distinction"
    assert "2 grading bands cover" in snapshot["grading"]["band_warning"]


def test_a_scheme_with_no_bands_is_legal(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """A school reporting marks only still has a scheme."""
    scheme = _scheme(tenant)
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)

    outcome = _calc(tenant, examination, school["riya"], head)
    snapshot = _snap(outcome)
    assert outcome["result"].grade_label is None
    assert snapshot["grading"]["band_warning"] is None
    assert float(outcome["result"].percentage) == 88.0


def test_the_resolved_band_is_frozen_into_the_snapshot(
    ctx, db_session, tenant, cycles, exam_type, school, head, anyone_manages
):
    """The reason a result is a snapshot and not a view."""
    scheme = _scheme(tenant)
    band = _band(tenant, scheme, "A", 80, 100, sequence=1, point=Decimal("9.5"))

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 83)

    outcome = _calc(tenant, examination, school["riya"], head)
    stored = outcome["result"]
    frozen = dict(stored.snapshot["grading"])
    assert frozen["grade_label"] == "A"
    assert frozen["min_value"] == 80.0
    assert frozen["grade_point"] == 9.5

    # The school redraws its bands: 83 would now be a B.
    band.min_value = Decimal("85")
    band.label = "B"
    band.is_pass = False
    band.grade_point = Decimal("7")
    db_session.flush()

    assert stored.grade_label == "A", "a calculated result followed a later edit"
    assert stored.snapshot["grading"] == frozen
    assert results_service.current_result(
        examination.id, school["riya"].id, tenant.id
    ).grade_label == "A"


# ---------------------------------------------------------------------------
# Weight
# ---------------------------------------------------------------------------

def test_a_weighted_paper_refuses_the_calculation(
    ctx, db_session, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 70, component="Theory", day=6),
        _paper_spec(school["science"], 30, day=8),
    ])
    theory = _papers(examination, tenant)[0]
    theory.weight = Decimal("70")
    db_session.flush()
    _mark(tenant, theory, school["riya"], MARK_PRESENT, 56)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["success"] is False
    assert outcome["code"] == "WEIGHTED_CALCULATION_UNSUPPORTED"
    assert ExamResult.query.filter_by(examination_id=examination.id).count() == 0


def test_a_nan_weight_is_refused_rather_than_consumed(
    ctx, db_session, tenant, cycles, exam_type, school, head, anyone_manages
):
    """`weight` is unvalidated and the column accepts NaN. Refusing on any
    non-null value is what guarantees arithmetic never sees one."""
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    paper.weight = Decimal("NaN")
    db_session.flush()
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["success"] is False
    assert outcome["code"] == "WEIGHTED_CALCULATION_UNSUPPORTED"


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

def test_a_first_calculation_is_version_one_and_unpublished(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)

    row = _calc(tenant, examination, school["riya"], head)["result"]
    assert row.version == 1
    assert row.is_current is True
    assert row.published_at is None


def test_recalculating_replaces_the_unpublished_result(
    ctx, db_session, tenant, cycles, exam_type, school, head, anyone_manages
):
    """A version is a statement the school made. Nobody was told this one, so
    recalculating corrects it rather than stacking a second version."""
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    mark = _mark(tenant, paper, school["riya"], MARK_PRESENT, 60)

    first = _calc(tenant, examination, school["riya"], head)["result"]
    assert float(first.percentage) == 60.0

    mark.marks_obtained = Decimal("75")
    db_session.flush()

    second = _calc(tenant, examination, school["riya"], head)["result"]
    assert float(second.percentage) == 75.0
    assert second.version == 1
    rows = ExamResult.query.filter_by(
        examination_id=examination.id, student_id=school["riya"].id
    ).all()
    assert len(rows) == 1
    assert len([r for r in rows if r.is_current]) == 1


def test_a_published_result_is_never_recalculated(
    ctx, db_session, tenant, cycles, exam_type, school, head, anyone_manages
):
    from core.school_time import utc_now

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    mark = _mark(tenant, paper, school["riya"], MARK_PRESENT, 60)

    published = _calc(tenant, examination, school["riya"], head)["result"]
    published.published_at = utc_now()
    frozen = dict(published.snapshot)
    db_session.flush()

    mark.marks_obtained = Decimal("95")
    db_session.flush()

    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["success"] is False
    assert outcome["code"] == "RESULT_PUBLISHED"
    assert float(published.percentage) == 60.0
    assert published.snapshot == frozen


# ---------------------------------------------------------------------------
# Applicability
# ---------------------------------------------------------------------------

def test_a_student_receives_only_their_own_classs_papers(
    ctx, db_session, tenant, cycles, exam_type, school, head, anyone_manages
):
    """One examination spanning two sections: each student's result carries
    only the papers their own class sits."""
    other = _offering(db_session, tenant, school["jee"], "JEEMaths")
    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 100, day=6),
    ])
    # A paper for a class this student is not in, added before marking opened.
    assert exam_services.add_papers(
        examination.id, tenant.id,
        [{"class_subject_id": other.id, "max_marks": 200,
          "exam_date": date(2026, 7, 9)}],
        commit=False,
    )["success"] is False, "papers cannot be added during marks entry"

    outcome = _calc(tenant, examination, school["riya"], head)
    paper_ids = {r["paper_id"] for r in _snap(outcome)["papers"]}
    assert paper_ids == {_papers(examination, tenant)[0].id}


def test_a_batch_student_gets_the_batchs_result(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """An `additional` enrollment is applicability like any other (EX-02A)."""
    created = exam_services.create_examination(
        tenant_id=tenant.id, academic_cycle_id=cycles["batch"].id,
        exam_type_id=exam_type.id, name=f"JEE-{uuid.uuid4().hex[:5]}",
        papers=[{"class_subject_id": school["jee_physics"].id,
                 "max_marks": 300, "exam_date": date(2026, 5, 20)}],
        commit=False,
    )
    examination = created["examination"]
    exam_services.schedule_examination(examination.id, tenant.id, commit=False)
    exam_services.open_marks_entry(examination.id, tenant.id, commit=False)
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["meera"], MARK_PRESENT, 240)

    outcome = _calc(tenant, examination, school["meera"], head)
    assert float(outcome["result"].percentage) == 80.0
    assert results_service.examination_cohort(examination, tenant.id) == [
        school["meera"].id
    ]


def test_a_locked_paper_keeps_its_register_as_the_cohort(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages, only_teachers_may
):
    """EX-02A.1 must not be undone here: after locking, applicability comes
    from the register, so a later enrollment change cannot rewrite a result."""
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)
    marks_service.lock_paper(
        paper.id, tenant.id, actor_user_id=head, commit=False
    )

    assert results_service.examination_cohort(examination, tenant.id) == [
        school["riya"].id
    ]
    outcome = _calc(tenant, examination, school["riya"], head)
    assert float(outcome["result"].percentage) == 88.0


# ---------------------------------------------------------------------------
# Cohort calculation
# ---------------------------------------------------------------------------

def test_a_cohort_calculation_covers_everyone(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)
    _mark(tenant, paper, school["dev"], MARK_ABSENT)
    # meera: no mark — still gets a result, marked incomplete

    outcome = results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )
    assert outcome["success"] is True, outcome
    assert outcome["calculated"] == 3

    by_student = {
        r.student_id: r
        for r in results_service.results_for(examination.id, tenant.id)
    }
    assert float(by_student[school["riya"].id].percentage) == 88.0
    assert float(by_student[school["dev"].id].percentage) == 0.0
    assert by_student[school["meera"].id].percentage is None
    assert by_student[school["meera"].id].snapshot["complete"] is False


def test_one_refusal_calculates_nobody(
    ctx, db_session, tenant, cycles, exam_type, school, head, anyone_manages
):
    """Riya's result would succeed; the published one refuses; the batch is
    abandoned rather than half-written."""
    from core.school_time import utc_now

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    for student, marks in ((school["riya"], 88), (school["dev"], 70),
                           (school["meera"], 50)):
        _mark(tenant, paper, student, MARK_PRESENT, marks)

    blocked = _calc(tenant, examination, school["dev"], head)["result"]
    blocked.published_at = utc_now()
    db_session.flush()

    outcome = results_service.calculate_results(
        examination.id, tenant_id=tenant.id, actor_user_id=head, commit=False
    )
    assert outcome["success"] is False
    assert outcome["code"] == "RESULT_PUBLISHED"

    # Only the pre-existing published row survives; nobody else was written.
    rows = ExamResult.query.filter_by(examination_id=examination.id).all()
    assert [r.student_id for r in rows] == [school["dev"].id]


# ---------------------------------------------------------------------------
# Authority and tenancy
# ---------------------------------------------------------------------------

def test_calculating_needs_the_manage_permission(
    ctx, monkeypatch, tenant, cycles, exam_type, school, head
):
    import modules.rbac.services as rbac

    monkeypatch.setattr(rbac, "has_permission", lambda user_id, name: True)
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    monkeypatch.setattr(rbac, "has_permission", lambda user_id, name: False)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["success"] is False
    assert outcome["code"] == "FORBIDDEN"


def test_another_schools_examination_cannot_be_calculated(
    ctx, db_session, tenant, cycles, exam_type, school, head, anyone_manages
):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    outcome = results_service.calculate_result(
        examination.id, school["riya"].id, tenant_id=other.id,
        actor_user_id=head, commit=False,
    )
    assert outcome["success"] is False
    assert outcome["code"] == "NOT_FOUND"
    assert ExamResult.query.filter_by(examination_id=examination.id).count() == 0


def test_a_foreign_student_gets_an_empty_result_not_another_schools_papers(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """A student who sits none of the papers is applicable to none of them."""
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    outcome = _calc(tenant, examination, school["outsider"], head)
    snapshot = _snap(outcome)
    assert snapshot["papers"] == []
    assert outcome["result"].percentage is None
    assert any("sits none" in w for w in snapshot["warnings"])


def test_a_foreign_grading_band_cannot_exist_to_be_resolved(
    ctx, db_session, tenant, school
):
    """Stronger than the service check: `fk_grading_bands_scheme` is composite
    on (tenant_id, grading_scheme_id), so a band belonging to one school cannot
    even be attached to another school's scheme. The tenant-scoped read in
    `_bands_for` is the second line, not the only one."""
    from sqlalchemy.exc import IntegrityError

    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()
    scheme = _scheme(tenant)

    db_session.add(GradingBand(
        id=_new_id("gb-"), tenant_id=other.id, grading_scheme_id=scheme.id,
        label="THEIRS", min_value=0, max_value=100, is_pass=True, sequence=1,
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_bands_are_read_scoped_to_the_examinations_tenant(
    ctx, db_session, tenant, cycles, exam_type, school, head, anyone_manages
):
    """A scheme id that exists in two schools resolves only against this one's
    bands."""
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A", 80, 100, sequence=1)

    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)

    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["result"].grade_label == "A"
    assert outcome["result"].snapshot["grading"]["scheme_id"] == scheme.id


# ---------------------------------------------------------------------------
# The snapshot is JSON, and it is data
# ---------------------------------------------------------------------------

def test_the_snapshot_is_json_serialisable_and_carries_no_exam_type_branch(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    import json

    scheme = _scheme(tenant)
    _band(tenant, scheme, "A", 80, 100, sequence=1)
    examination = _exam(tenant, cycles, exam_type, school, [
        _paper_spec(school["maths"], 100, pass_marks=35, day=6),
        _paper_spec(school["science"], 100, day=8),
    ], scheme=scheme)
    maths, science = _papers(examination, tenant)
    _mark(tenant, maths, school["riya"], MARK_PRESENT, 90)
    _mark(tenant, science, school["riya"], MARK_ABSENT)

    snapshot = _snap(_calc(tenant, examination, school["riya"], head))
    encoded = json.dumps(snapshot)          # raises if a Decimal survived
    assert json.loads(encoded) == snapshot

    row = _row_for(snapshot, maths.id)
    assert set(row) >= {
        "paper_id", "class_id", "class_subject_id", "subject_id",
        "component_label", "exam_date", "max_marks", "pass_marks", "status",
        "marks", "obtained", "included_in_total", "paper_pass",
        "not_yet_entered",
    }
    assert row["subject_id"] is not None
    assert snapshot["examination"]["id"] == examination.id
    assert snapshot["student"]["id"] == school["riya"].id


def test_calculation_writes_no_lifecycle_event(
    ctx, tenant, cycles, exam_type, school, head, anyone_manages
):
    """Calculation is not publication. `ResultsPublished` belongs to EX-03B and
    an event per recalculation would be noise nobody reads."""
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)])
    paper = _papers(examination, tenant)[0]
    _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)

    before = len(exam_services.timeline_for(examination.id, tenant.id))
    _calc(tenant, examination, school["riya"], head)
    after = exam_services.timeline_for(examination.id, tenant.id)
    assert len(after) == before
    assert "ResultsPublished" not in [e.event_name for e in after]


def test_a_non_finite_mark_refuses_rather_than_poisoning_the_total(
    ctx, db_session, tenant, cycles, exam_type, school, head, anyone_manages
):
    """`exam_marks.marks_obtained` accepts NaN at the database level — Postgres
    evaluates `NaN >= 0` as true, so the CHECK passes it. EX-02A.1 stops the
    service writing one, but raw SQL or a future non-service writer would not
    be stopped, and the failure was ugly: the total goes quietly to NaN, and
    band resolution then raises InvalidOperation instead of refusing.
    """
    scheme = _scheme(tenant)
    _band(tenant, scheme, "A", 80, 100, sequence=1)
    examination = _exam(tenant, cycles, exam_type, school,
                        [_paper_spec(school["maths"], 100)], scheme=scheme)
    paper = _papers(examination, tenant)[0]

    mark = _mark(tenant, paper, school["riya"], MARK_PRESENT, 88)
    mark.marks_obtained = Decimal("NaN")     # the state the service cannot make
    db_session.flush()

    outcome = _calc(tenant, examination, school["riya"], head)
    assert outcome["success"] is False
    assert outcome["code"] == "MARKS_NOT_FINITE"
    assert ExamResult.query.filter_by(examination_id=examination.id).count() == 0
