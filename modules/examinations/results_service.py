"""Turning recorded marks into a result.

`exam_marks` stays the source of truth. This computes a **frozen presentation**
of those facts and stores it on `exam_results` (ADR-018) — totals, a
percentage, a grade and a pass, plus a snapshot holding everything the
calculation saw. Nothing here changes a mark.

The rules below are locked decisions, not defaults. ADR-018 deliberately left
computation open ("a service concern that will change as schools ask for it"),
so each one is written down in ADR-020 rather than inferred from the code.

**The five mark states stay five.** Present contributes its marks and its
maximum. Absent and malpractice contribute nothing to the numerator and their
full maximum to the denominator — the student sat nothing and is measured
against what they could have scored. Exempted contributes to *neither*: the
paper leaves the calculation entirely, so an exemption cannot lower a
percentage. A paper with **no mark row at all** is not any of these — it is
`not_yet_entered`, it contributes nothing to either side, and it makes the
result incomplete. Turning it into a zero would fail a student for a teacher's
unfinished work.

**Weighting is refused, not guessed.** `paper.weight` has no established
mathematics, no validation, and a column that will accept NaN. A paper carrying
one refuses the whole calculation rather than being silently ignored.

**The grade is resolved once and frozen.** A school that redraws its bands in
December must not change what was computed in August, so the resolved band is
copied into the snapshot and never re-read.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from core.database import db
from modules.classes.models import ClassSubject

from .marks_service import PERM_MANAGE, is_eligible, paper_cohort
from .models import (
    MARK_ABSENT,
    MARK_EXEMPTED,
    MARK_MALPRACTICE,
    MARK_PRESENT,
    ExamMark,
    ExamPaper,
    ExamResult,
    Examination,
    GradingBand,
)
from .services import _Refused, _get, _ok, _refuse, papers_for

# A sixth state, and the only one that is the absence of a row rather than a
# value in one. It never becomes a mark, and no ExamMark is created for it.
STATUS_NOT_ENTERED = "not_yet_entered"

# Percentages are stored as Numeric(6,3). Rounded once, here, and the rounded
# value is what the bands are matched against — so what a marksheet prints and
# what earned the grade are the same number.
_PERCENT_PLACES = Decimal("0.001")

# How a status contributes: (counts toward obtained, counts toward maximum).
_CONTRIBUTION = {
    MARK_PRESENT: (True, True),
    MARK_ABSENT: (False, True),
    MARK_MALPRACTICE: (False, True),
    MARK_EXEMPTED: (False, False),
    STATUS_NOT_ENTERED: (False, False),
}


def _decimal(value: Any) -> Optional[Decimal]:
    return None if value is None else Decimal(str(value))


def _number(value: Any) -> Optional[float]:
    """For the snapshot, which must be JSON."""
    return None if value is None else float(value)


# ---------------------------------------------------------------------------
# Applicability
# ---------------------------------------------------------------------------


def applicable_papers(
    examination: Examination, student_id: str, tenant_id: str
) -> List[ExamPaper]:
    """Which of this examination's papers this student sits.

    Asked per paper through `is_eligible`, which is the EX-02A.1 rule: an open
    paper answers from current enrollment, a closed one from its own register.
    Reusing it is what keeps a result computed after promotion from quietly
    changing — reading today's class membership instead is exactly the bug that
    slice fixed.

    One consequence follows from that and is recorded rather than worked
    around: a **locked** paper with no mark for a student does not count as
    that student's paper at all, so it cannot appear as `not_yet_entered`.
    Nothing recorded who was expected to sit it (debt 51). `not_yet_entered` is
    therefore reachable only for papers still open — which is precisely when it
    is actionable.
    """
    return [
        paper
        for paper in papers_for(examination.id, tenant_id)
        if is_eligible(paper, student_id)
    ]


def examination_cohort(examination: Examination, tenant_id: str) -> List[str]:
    """Every student any of this examination's papers is about (ADR-016).

    Sorted, so a cohort calculation is deterministic and its refusals are
    reproducible.
    """
    students: set = set()
    for paper in papers_for(examination.id, tenant_id):
        found, _source = paper_cohort(paper)
        students.update(found)
    return sorted(students)


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


def _resolve_band(
    bands: List[GradingBand], percentage: Optional[Decimal]
) -> Tuple[Optional[GradingBand], Optional[str]]:
    """The band this percentage falls in, and any warning about the scheme.

    Bounds are inclusive at both ends (the model says so). A scheme with no
    bands is legal — a school reporting marks only — and yields no grade and no
    complaint.

    Where the school's bands **overlap**, the lowest `sequence` wins. The
    database permits overlaps and repairing them is not this slice's business;
    what matters is that the same marks always produce the same grade, and that
    the snapshot says the configuration was ambiguous.

    Where they leave a **gap**, there is no grade. Picking the nearest band
    would be inventing a policy the school did not write down.
    """
    if percentage is None or not bands:
        return None, None

    matched = [
        band
        for band in bands
        if _decimal(band.min_value) <= percentage <= _decimal(band.max_value)
    ]
    if not matched:
        return None, (
            f"No grading band covers {percentage}%. The scheme leaves a gap, so "
            "this result has no grade."
        )

    matched.sort(key=lambda b: (b.sequence, b.id))
    if len(matched) > 1:
        labels = ", ".join(f"{b.label} ({b.min_value}-{b.max_value})" for b in matched)
        return matched[0], (
            f"{len(matched)} grading bands cover {percentage}%: {labels}. The "
            f"lowest sequence won ('{matched[0].label}')."
        )
    return matched[0], None


def _bands_for(scheme_id: Optional[str], tenant_id: str) -> List[GradingBand]:
    if not scheme_id:
        return []
    return (
        GradingBand.query.filter_by(
            grading_scheme_id=scheme_id, tenant_id=tenant_id
        )
        .order_by(GradingBand.sequence, GradingBand.id)
        .all()
    )


# ---------------------------------------------------------------------------
# The calculation
# ---------------------------------------------------------------------------


def _paper_rows(
    papers: List[ExamPaper], marks: Dict[str, ExamMark], subjects: Dict[str, str]
) -> List[Dict[str, Any]]:
    """One snapshot row per applicable paper, in a stable order."""
    rows = []
    for paper in papers:
        mark = marks.get(paper.id)
        status = mark.status if mark is not None else STATUS_NOT_ENTERED
        counts_obtained, counts_max = _CONTRIBUTION[status]

        max_marks = _decimal(paper.max_marks)
        pass_marks = _decimal(paper.pass_marks)
        scored = _decimal(mark.marks_obtained) if mark is not None else None
        # Absent and malpractice are measured as nothing scored. Exempted and
        # not-entered are measured as nothing at all — hence `included_in_total`.
        obtained = scored if (counts_obtained and scored is not None) else (
            Decimal("0") if counts_max else None
        )

        paper_pass: Optional[bool] = None
        if pass_marks is not None and counts_max:
            paper_pass = (obtained or Decimal("0")) >= pass_marks

        rows.append(
            {
                "paper_id": paper.id,
                "class_id": paper.class_id,
                "class_subject_id": paper.class_subject_id,
                "subject_id": subjects.get(paper.class_subject_id),
                "component_label": paper.component_label or None,
                "exam_date": paper.exam_date.isoformat() if paper.exam_date else None,
                "max_marks": _number(max_marks),
                "pass_marks": _number(pass_marks),
                "status": status,
                "marks": _number(scored),
                "obtained": _number(obtained),
                "included_in_total": bool(counts_max),
                "paper_pass": paper_pass,
                "not_yet_entered": status == STATUS_NOT_ENTERED,
            }
        )
    return rows


def _compute(
    examination: Examination,
    student_id: str,
    papers: List[ExamPaper],
    marks: Dict[str, ExamMark],
    subjects: Dict[str, str],
    bands: List[GradingBand],
) -> Dict[str, Any]:
    """Everything a result is, computed and shaped. Raises `_Refused`."""
    weighted = [p.id for p in papers if p.weight is not None]
    if weighted:
        raise _Refused(_refuse(
            "WEIGHTED_CALCULATION_UNSUPPORTED",
            (
                f"{len(weighted)} paper(s) carry a weight. What a weight means "
                "mathematically has not been decided, and the column accepts "
                "values arithmetic cannot use, so this refuses rather than "
                "quietly ignoring it."
            ),
        ))

    # EX-02A.1 stops a NaN reaching `exam_marks` through the service, but the
    # column itself accepts one — Postgres evaluates `NaN >= 0` as true, so the
    # CHECK lets it through — and a mark written by raw SQL or a future
    # non-service writer would arrive here. It must not be computed on: the sum
    # goes quietly to NaN, and band resolution then raises InvalidOperation
    # rather than refusing. Refuse where it can be named.
    unusable = [
        paper.id
        for paper in papers
        if (mark := marks.get(paper.id)) is not None
        and mark.marks_obtained is not None
        and not _decimal(mark.marks_obtained).is_finite()
    ]
    if unusable:
        raise _Refused(_refuse(
            "MARKS_NOT_FINITE",
            (
                f"{len(unusable)} paper(s) hold a mark that is not an ordinary "
                "number, so this result cannot be computed. The mark must be "
                "corrected first."
            ),
        ))

    rows = _paper_rows(papers, marks, subjects)

    total_max = Decimal("0")
    total_obtained = Decimal("0")
    for row in rows:
        if not row["included_in_total"]:
            continue
        total_max += _decimal(row["max_marks"])
        total_obtained += _decimal(row["obtained"] or 0)

    warnings: List[str] = []
    complete = not any(row["not_yet_entered"] for row in rows)
    if not complete:
        outstanding = [r["paper_id"] for r in rows if r["not_yet_entered"]]
        warnings.append(
            f"{len(outstanding)} applicable paper(s) have no mark recorded yet, "
            "so this result is incomplete."
        )
    if not papers:
        warnings.append("This student sits none of this examination's papers.")

    # No denominator, no percentage. Every paper exempted is the real case, and
    # 0% would say the student failed everything they were excused from.
    percentage: Optional[Decimal] = None
    if total_max > 0:
        percentage = (total_obtained / total_max * Decimal("100")).quantize(
            _PERCENT_PLACES, rounding=ROUND_HALF_UP
        )
    elif rows:
        warnings.append(
            "No paper contributes to the total, so there is no percentage."
        )

    band, band_warning = _resolve_band(bands, percentage)
    if band_warning:
        warnings.append(band_warning)

    band_pass: Optional[bool] = band.is_pass if band is not None else None
    judged = [r["paper_pass"] for r in rows if r["paper_pass"] is not None]
    paper_pass: Optional[bool] = all(judged) if judged else None

    # Three-valued on purpose: with no bands and no pass marks, nothing in the
    # school's configuration decides pass or fail, and inventing an answer is
    # worse than saying so.
    if band_pass is None and paper_pass is None:
        is_pass = None
    elif band_pass is None:
        is_pass = paper_pass
    elif paper_pass is None:
        is_pass = band_pass
    else:
        is_pass = band_pass and paper_pass

    snapshot = {
        "examination": {"id": examination.id, "name": examination.name},
        "student": {"id": student_id},
        "complete": complete,
        "papers": rows,
        "aggregate": {
            "total_max": _number(total_max),
            "total_obtained": _number(total_obtained),
            "percentage": _number(percentage),
        },
        "grading": {
            "scheme_id": examination.grading_scheme_id,
            "band_id": band.id if band else None,
            "grade_label": band.label if band else None,
            "min_value": _number(band.min_value) if band else None,
            "max_value": _number(band.max_value) if band else None,
            "is_pass": band.is_pass if band else None,
            "grade_point": _number(band.grade_point) if band else None,
            "band_warning": band_warning,
        },
        "pass": {
            "band_pass": band_pass,
            "paper_pass": paper_pass,
            "is_pass": is_pass,
        },
        "warnings": warnings,
    }

    return {
        "total_max": total_max,
        "total_obtained": total_obtained,
        "percentage": percentage,
        "grade_label": band.label if band else None,
        "is_pass": is_pass,
        "snapshot": snapshot,
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _store(
    examination: Examination, student_id: str, tenant_id: str, computed: Dict[str, Any]
) -> ExamResult:
    """Write the figures onto the student's current result.

    **A published result is never touched** (ADR-018) — the caller checks that
    before we get here, because refusing has to happen before anything else in
    the batch is written.

    An **unpublished** result is replaced in place rather than versioned. A
    version is a statement the school made; a result nobody has been told about
    is not one, and versioning every recalculation would reach version 40
    before publication with nothing to show for it. `version` stays 1 until
    EX-03B publishes, and a revision after that inserts 2.
    """
    result = ExamResult.query.filter(
        ExamResult.tenant_id == tenant_id,
        ExamResult.examination_id == examination.id,
        ExamResult.student_id == student_id,
        ExamResult.is_current.is_(True),
        ExamResult.deleted_at.is_(None),
    ).first()

    if result is None:
        result = ExamResult(
            tenant_id=tenant_id,
            examination_id=examination.id,
            student_id=student_id,
            version=1,
            is_current=True,
        )
        db.session.add(result)

    result.total_max = computed["total_max"]
    result.total_obtained = computed["total_obtained"]
    result.percentage = computed["percentage"]
    result.grade_label = computed["grade_label"]
    result.is_pass = computed["is_pass"]
    result.snapshot = computed["snapshot"]
    return result


def _published_refusal(
    examination: Examination, student_id: str, tenant_id: str
) -> Optional[Dict[str, Any]]:
    published = ExamResult.query.filter(
        ExamResult.tenant_id == tenant_id,
        ExamResult.examination_id == examination.id,
        ExamResult.student_id == student_id,
        ExamResult.is_current.is_(True),
        ExamResult.deleted_at.is_(None),
        ExamResult.published_at.isnot(None),
    ).first()
    if published is None:
        return None
    return _refuse(
        "RESULT_PUBLISHED",
        (
            "This student's result has been published, and a published result "
            "is what the school told a parent. Recalculating over it would "
            "rewrite that; a change needs a revision."
        ),
    )


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def _preload(examination: Examination, tenant_id: str):
    """Everything the whole cohort needs, fetched once."""
    papers = papers_for(examination.id, tenant_id)
    paper_ids = [p.id for p in papers]

    subjects: Dict[str, str] = {}
    offering_ids = {p.class_subject_id for p in papers}
    if offering_ids:
        subjects = {
            row[0]: row[1]
            for row in db.session.query(ClassSubject.id, ClassSubject.subject_id)
            .filter(
                ClassSubject.tenant_id == tenant_id,
                ClassSubject.id.in_(offering_ids),
            )
            .all()
        }

    marks: Dict[str, Dict[str, ExamMark]] = {}
    if paper_ids:
        for mark in ExamMark.query.filter(
            ExamMark.tenant_id == tenant_id,
            ExamMark.exam_paper_id.in_(paper_ids),
            ExamMark.deleted_at.is_(None),
        ).all():
            marks.setdefault(mark.student_id, {})[mark.exam_paper_id] = mark

    bands = _bands_for(examination.grading_scheme_id, tenant_id)
    return subjects, marks, bands


def _calculate_one(
    examination: Examination,
    student_id: str,
    tenant_id: str,
    subjects: Dict[str, str],
    marks: Dict[str, Dict[str, ExamMark]],
    bands: List[GradingBand],
) -> ExamResult:
    """Compute and store one student's result. Raises `_Refused`."""
    refusal = _published_refusal(examination, student_id, tenant_id)
    if refusal:
        raise _Refused(refusal)

    papers = applicable_papers(examination, student_id, tenant_id)
    computed = _compute(
        examination, student_id, papers, marks.get(student_id, {}), subjects, bands
    )
    return _store(examination, student_id, tenant_id, computed)


def compute_result(
    examination: Examination, student_id: str, tenant_id: str
) -> Dict[str, Any]:
    """One student's figures, computed and shaped — and stored by nobody.

    The calculation on its own, so revision (EX-03C) can write the same
    arithmetic into a *new* version instead of over the current row. Every
    guard comes with it, because they live in `_compute`: a weighted paper
    still refuses, a non-finite mark still refuses, and grading still resolves
    exactly once. Raises `_Refused`.
    """
    subjects, marks, bands = _preload(examination, tenant_id)
    papers = applicable_papers(examination, student_id, tenant_id)
    return _compute(
        examination, student_id, papers, marks.get(student_id, {}), subjects, bands
    )


def calculate_result(
    examination_id: str,
    student_id: str,
    *,
    tenant_id: str,
    actor_user_id: str,
    commit: bool = True,
) -> Dict[str, Any]:
    """Compute one student's result for one examination."""
    from modules.rbac.services import has_permission

    if not has_permission(actor_user_id, PERM_MANAGE):
        return _refuse("FORBIDDEN", f"You do not hold {PERM_MANAGE}.")

    examination = _get(examination_id, tenant_id)
    if examination is None:
        return _refuse("NOT_FOUND", "Examination not found")

    subjects, marks, bands = _preload(examination, tenant_id)

    try:
        with db.session.begin_nested():
            result = _calculate_one(
                examination, student_id, tenant_id, subjects, marks, bands
            )
            db.session.flush()
    except _Refused as stop:
        return stop.refusal

    if commit:
        db.session.commit()
    return _ok(result=result)


def calculate_results(
    examination_id: str,
    *,
    tenant_id: str,
    actor_user_id: str,
    commit: bool = True,
) -> Dict[str, Any]:
    """Compute the whole examination's results — all of them, or none.

    One student refusing takes the batch with it. A half-calculated cohort is
    worse than an uncalculated one: nothing distinguishes the students who were
    recomputed from the students who were not, and the school cannot tell by
    looking.
    """
    from modules.rbac.services import has_permission

    if not has_permission(actor_user_id, PERM_MANAGE):
        return _refuse("FORBIDDEN", f"You do not hold {PERM_MANAGE}.")

    examination = _get(examination_id, tenant_id)
    if examination is None:
        return _refuse("NOT_FOUND", "Examination not found")

    subjects, marks, bands = _preload(examination, tenant_id)
    cohort = examination_cohort(examination, tenant_id)

    results: List[ExamResult] = []
    try:
        with db.session.begin_nested():
            for student_id in cohort:
                results.append(
                    _calculate_one(
                        examination, student_id, tenant_id, subjects, marks, bands
                    )
                )
            db.session.flush()
    except _Refused as stop:
        return stop.refusal

    if commit:
        db.session.commit()
    return _ok(results=results, calculated=len(results))


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def current_result(
    examination_id: str, student_id: str, tenant_id: str
) -> Optional[ExamResult]:
    """The result in force, read as stored — never recomputed.

    Recomputing on read is what ADR-018 exists to prevent: a band edited in
    December would silently change what a parent was told in August.
    """
    return ExamResult.query.filter(
        ExamResult.tenant_id == tenant_id,
        ExamResult.examination_id == examination_id,
        ExamResult.student_id == student_id,
        ExamResult.is_current.is_(True),
        ExamResult.deleted_at.is_(None),
    ).first()


def results_for(examination_id: str, tenant_id: str) -> List[ExamResult]:
    return (
        ExamResult.query.filter(
            ExamResult.tenant_id == tenant_id,
            ExamResult.examination_id == examination_id,
            ExamResult.is_current.is_(True),
            ExamResult.deleted_at.is_(None),
        )
        .order_by(ExamResult.student_id)
        .all()
    )


# ---------------------------------------------------------------------------
# The board a results screen reads (EX-08)
# ---------------------------------------------------------------------------


def result_board(examination_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Every student's result state for one examination, in one read.

    A results screen needs three things `results_for` cannot give it: who the
    student is, which version is *official* as opposed to current, and whether
    a correction has left the two disagreeing. Asking per student would be
    three N+1s stacked — `revision_pending` alone queries corrections — which
    is the shape `correction_queue` and `papers_with_labels` already avoided.

    **Official and current are kept apart deliberately** (ADR-020). `official`
    is the latest published version, which is what a parent was told; `current`
    is the working one, which may be an unpublished revision. Collapsing them
    is the mistake this whole read exists to prevent.
    """
    from modules.people.models import Person
    from modules.students.models import Student

    from .models import CORRECTION_APPROVED, ExamMark, ExamMarkCorrection
    from .services import _get

    examination = _get(examination_id, tenant_id)
    if examination is None:
        return None

    cohort = examination_cohort(examination, tenant_id)
    versions: Dict[str, List[ExamResult]] = {}
    for row in (
        ExamResult.query.filter(
            ExamResult.tenant_id == tenant_id,
            ExamResult.examination_id == examination_id,
            ExamResult.deleted_at.is_(None),
        )
        .order_by(ExamResult.student_id, ExamResult.version)
        .all()
    ):
        versions.setdefault(row.student_id, []).append(row)

    student_ids = set(cohort) | set(versions)
    students = {
        student.id: student
        for student in Student.query.filter(
            Student.tenant_id == tenant_id, Student.id.in_(student_ids)
        ).all()
    } if student_ids else {}
    people = {
        person.id: person
        for person in Person.query.filter(
            Person.id.in_({s.person_id for s in students.values() if s.person_id})
        ).all()
    } if students else {}

    # Every approved correction on this examination's papers, once — so
    # "has this student's marks moved since publication?" is a dictionary
    # lookup rather than a query per student.
    paper_ids = [p.id for p in papers_for(examination_id, tenant_id)]
    decided: Dict[str, List] = {}
    if paper_ids:
        for correction, student_id in (
            db.session.query(ExamMarkCorrection, ExamMark.student_id)
            .join(
                ExamMark,
                db.and_(
                    ExamMark.id == ExamMarkCorrection.exam_mark_id,
                    ExamMark.tenant_id == ExamMarkCorrection.tenant_id,
                ),
            )
            .filter(
                ExamMarkCorrection.tenant_id == tenant_id,
                ExamMarkCorrection.status == CORRECTION_APPROVED,
                ExamMarkCorrection.decided_at.isnot(None),
                ExamMark.exam_paper_id.in_(paper_ids),
                ExamMark.deleted_at.is_(None),
            )
            .all()
        ):
            decided.setdefault(student_id, []).append(correction)

    rows: List[Dict[str, Any]] = []
    for student_id in sorted(student_ids):
        history = versions.get(student_id, [])
        current = next((r for r in history if r.is_current), None)
        published = [r for r in history if r.published_at is not None]
        official = published[-1] if published else None

        # The same rule `revision_pending` applies, evaluated from data already
        # in hand: an approved correction decided after the official result was
        # published means the marks and the school's word have parted company.
        pending = bool(
            official is not None
            and any(
                correction.decided_at > official.published_at
                for correction in decided.get(student_id, [])
            )
        )

        student = students.get(student_id)
        person = people.get(student.person_id) if student else None
        rows.append({
            "student_id": student_id,
            "admission_number": student.admission_number if student else None,
            "full_name": person.full_name if person else None,
            "current": current,
            "official": official,
            "versions": history,
            "revision_pending": pending,
            "has_result": current is not None,
        })

    return {
        "examination": examination,
        "students": rows,
        "readiness": None,      # filled by the caller that needs it
    }
