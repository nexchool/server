"""Publishing an examination's results.

Publication is the moment computed figures become **the school's word**. Before
it, an `ExamResult` is a working number that recalculation may overwrite; after
it, the row is what a parent was told, and EX-03A already refuses to recompute
over it.

So this slice adds no arithmetic at all. It checks that every result is fit to
be stated, stamps them, moves the examination, and records one event — as a
single transaction, because a half-published cohort is a school that cannot say
which half.

**One door.** EX-01 left `publish_results` in `services.py` as a transition-only
stub, explicitly deferring the real thing to "the results slice". This is that
slice, and the stub is gone: an unguarded second entry point would let anything
move an examination to `published` without checking a single result.

**Nothing here recomputes.** Not marks, not grading, not the snapshot. If a
result is missing the caller is told to calculate first; publication never
quietly calculates on somebody's behalf, because that would make publication a
moment when figures can still change.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.database import db
from core.school_time import utc_now

from .models import EXAM_PUBLISHED, ExamResult, Examination
from .results_service import current_result, examination_cohort
from .services import _Refused, _ok, _refuse, _transition, may_become

# Publishing is its own act in the catalogue — "Publish and revise examination
# results" — and deliberately not `assessment.manage`, which is the key for
# running marking. Whoever closes a register is not necessarily whoever tells
# the parents.
PERM_PUBLISH = "examination.publish"


def _unfit(result: ExamResult, student_id: str) -> Optional[Dict[str, Any]]:
    """Why this result cannot be stated as the school's word — or None.

    Three conditions, and each is a thing a school should be stopped from
    saying rather than a technicality.
    """
    snapshot = result.snapshot or {}

    if snapshot.get("complete") is not True:
        return _refuse(
            "RESULT_INCOMPLETE",
            (
                f"Student {student_id} has papers with no mark recorded yet. "
                "'Not yet entered' cannot become a published result."
            ),
        )

    grading = snapshot.get("grading") or {}
    # A grade the school's own scheme failed to produce. `is_pass` being None
    # is fine when a school configured no pass rule at all — a marks-only
    # school publishes marksheets without one, and ADR-020 treats that as an
    # answer. It is *not* fine when a scheme was named, has bands, and none of
    # them covered this percentage: that is a gap in the configuration, and
    # publishing it would state a result the school cannot explain.
    if grading.get("band_id") is None and grading.get("band_warning"):
        return _refuse(
            "GRADE_UNRESOLVED",
            (
                f"Student {student_id} has no grade because the grading scheme "
                f"does not cover their result: {grading['band_warning']} Fix "
                "the bands and calculate again before publishing."
            ),
        )
    return None


def publish_results(
    examination_id: str,
    tenant_id: str,
    *,
    actor_user_id: str,
    commit: bool = True,
) -> Dict[str, Any]:
    """Publish every result for this examination — all of them, or none.

    The whole cohort is checked before anything is stamped. One student with an
    unfinished register stops the publication, which is the point: a school
    that has told half a class is in a worse position than one that has told
    nobody, because nothing distinguishes the two halves afterwards.
    """
    from modules.rbac.services import has_permission

    if not has_permission(actor_user_id, PERM_PUBLISH):
        return _refuse("FORBIDDEN", f"You do not hold {PERM_PUBLISH}.")

    # Locked for the duration. Two administrators pressing publish at the same
    # moment would otherwise both read `marks_entry`, both stamp the same rows
    # and both record the event; the second now waits, re-reads `published`,
    # and is refused by the transition table like any other late caller.
    examination = (
        Examination.query.filter(
            Examination.id == examination_id,
            Examination.tenant_id == tenant_id,
            Examination.deleted_at.is_(None),
        )
        .with_for_update()
        .first()
    )
    if examination is None:
        return _refuse("NOT_FOUND", "Examination not found")

    # The lifecycle is checked first because it is the coarser fact. A draft
    # examination has no results *because* it is a draft, and telling its
    # publisher "student X has no calculated result" would send them off to
    # calculate an examination nobody has sat yet.
    if not may_become(examination, EXAM_PUBLISHED):
        return _refuse(
            "INVALID_TRANSITION",
            (
                f"An examination that is '{examination.status}' cannot become "
                f"'{EXAM_PUBLISHED}'"
            ),
        )

    cohort = examination_cohort(examination, tenant_id)

    try:
        with db.session.begin_nested():
            published: List[ExamResult] = []
            for student_id in cohort:
                result = current_result(examination.id, student_id, tenant_id)
                if result is None:
                    raise _Refused(_refuse(
                        "RESULT_MISSING",
                        (
                            f"Student {student_id} has no calculated result. "
                            "Calculate the examination's results before "
                            "publishing it."
                        ),
                    ))
                if result.published_at is not None:
                    raise _Refused(_refuse(
                        "ALREADY_PUBLISHED",
                        f"Student {student_id}'s result is already published",
                    ))
                refusal = _unfit(result, student_id)
                if refusal:
                    raise _Refused(refusal)
                published.append(result)

            # Re-checked here as it is applied, so the one lifecycle table
            # stays the only thing that decides what may follow what.
            refusal = _transition(
                examination,
                EXAM_PUBLISHED,
                note=(
                    f"{len(published)} result(s) published"
                    if published
                    else "published with no results — no student sits this "
                         "examination"
                ),
                actor_user_id=actor_user_id,
            )
            if refusal:
                raise _Refused(refusal)

            stamped_at = utc_now()
            for result in published:
                # The snapshot is not touched. Publication says *when* the
                # figures became the school's word, never what they are.
                result.published_at = stamped_at
                result.published_by_user_id = actor_user_id

            db.session.flush()
    except _Refused as stop:
        return stop.refusal

    if commit:
        db.session.commit()
    return _ok(examination=examination, published=len(published))


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def published_results(examination_id: str, tenant_id: str) -> List[ExamResult]:
    """The results this examination has stated — the latest published version
    for each student.

    **Not filtered on `is_current`**, and that matters once revision exists
    (EX-03C): revising stands the published version down as current while it is
    still the school's word, so an `is_current` filter would make a published
    result vanish from this list the moment somebody began revising it. What is
    published is decided by `published_at`, never by which version is being
    worked on.
    """
    rows = (
        ExamResult.query.filter(
            ExamResult.tenant_id == tenant_id,
            ExamResult.examination_id == examination_id,
            ExamResult.deleted_at.is_(None),
            ExamResult.published_at.isnot(None),
        )
        .order_by(ExamResult.student_id, ExamResult.version)
        .all()
    )
    latest: Dict[str, ExamResult] = {}
    for row in rows:
        latest[row.student_id] = row       # ordered by version, so the last wins
    return [latest[student_id] for student_id in sorted(latest)]


def publication_readiness(examination_id: str, tenant_id: str) -> Dict[str, Any]:
    """What would stop this examination publishing, without publishing it.

    A cohort of forty refused one student at a time is a screen nobody can use,
    so the same checks run over everybody and report together.
    """
    examination = Examination.query.filter(
        Examination.id == examination_id,
        Examination.tenant_id == tenant_id,
        Examination.deleted_at.is_(None),
    ).first()
    if examination is None:
        return {"ready": False, "cohort": 0, "blocked": [], "found": False}

    blocked: List[Dict[str, Any]] = []
    cohort = examination_cohort(examination, tenant_id)
    for student_id in cohort:
        result = current_result(examination.id, student_id, tenant_id)
        if result is None:
            blocked.append({"student_id": student_id, "code": "RESULT_MISSING"})
            continue
        refusal = _unfit(result, student_id)
        if refusal:
            blocked.append({"student_id": student_id, "code": refusal["code"]})

    return {
        "found": True,
        "ready": not blocked and examination.status != EXAM_PUBLISHED,
        "cohort": len(cohort),
        "blocked": blocked,
        "status": examination.status,
    }
