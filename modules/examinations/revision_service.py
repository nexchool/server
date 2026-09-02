"""Revising a result that has already been published.

A published result is what the school told a parent, and ADR-018 is categorical
that it never changes. That left a dead end: a genuine error found after
publication could not be corrected, recomputed or re-issued (debt 55). This is
the way out, and it is deliberately not an undo.

**A revision adds; it never edits.** Version 1 keeps its figures, its snapshot,
its `published_at` and the name of whoever published it, forever and
queryably. The corrected arithmetic goes into version 2, which starts
unpublished — because recomputing a number and telling a parent it changed are
two different decisions, and a school gets to make them separately.

**Per student.** Verified rather than assumed: `results_service._compute` reads
one student's marks and nothing else — no rank, no cohort average, no shared
denominator — so one child's corrected mark cannot alter another child's
figures. Versioning a whole cohort because one paper was re-totalled would
retire thirty-nine correct published results to say nothing new about any of
them.

**Nothing here computes twice.** The arithmetic is `results_service.
compute_result`, the same function ordinary calculation uses, so a revision
inherits every guard with it: weighted papers still refuse, non-finite marks
still refuse, grading still resolves once and freezes into the new snapshot.

The trigger is an **approved correction decided after the result was
published**. A revision with nothing behind it is refused — an official
statement should not be reissued because somebody pressed a button.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.branch_scope import assert_student_allowed
from core.database import db
from core.school_time import utc_now
from sqlalchemy import func

from .models import (
    CORRECTION_APPROVED,
    EXAM_PUBLISHED,
    ExamMark,
    ExamMarkCorrection,
    ExamPaper,
    ExamResult,
    Examination,
)
from .results_service import applicable_papers, compute_result
from .services import _Refused, _ok, _refuse, record_event

# The catalogue already names this authority: `examination.publish` is
# "Publish and revise examination results". Revising is not a marking act — a
# teacher who may correct a mark does not thereby get to reissue the school's
# published word — and it needs no new key.
PERM_PUBLISH = "examination.publish"

EVENT_RESULTS_REVISED = "ResultsRevised"
EVENT_RESULTS_PUBLISHED = "ResultsPublished"


def _lock_examination(examination_id: str, tenant_id: str) -> Optional[Examination]:
    """The same lock publication takes, for the same reason: two people
    revising at once would otherwise both read version 1 as current and both
    write a version 2."""
    return (
        Examination.query.filter(
            Examination.id == examination_id,
            Examination.tenant_id == tenant_id,
            Examination.deleted_at.is_(None),
        )
        .with_for_update()
        .first()
    )


def _current(examination_id: str, student_id: str, tenant_id: str):
    return ExamResult.query.filter(
        ExamResult.tenant_id == tenant_id,
        ExamResult.examination_id == examination_id,
        ExamResult.student_id == student_id,
        ExamResult.is_current.is_(True),
        ExamResult.deleted_at.is_(None),
    ).first()


def corrections_since_publication(
    examination_id: str, student_id: str, tenant_id: str, published_at
) -> List[ExamMarkCorrection]:
    """Approved corrections to this student's papers, decided after publication.

    This is what makes a revision *warranted* rather than merely requested.
    Only approved ones count: a rejected correction changed nothing, and a
    pending one has not been decided by anybody yet.
    """
    if published_at is None:
        return []
    paper_ids = [
        row[0]
        for row in db.session.query(ExamPaper.id)
        .filter(
            ExamPaper.tenant_id == tenant_id,
            ExamPaper.examination_id == examination_id,
            ExamPaper.deleted_at.is_(None),
        )
        .all()
    ]
    if not paper_ids:
        return []
    return (
        ExamMarkCorrection.query.join(
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
            ExamMarkCorrection.decided_at > published_at,
            ExamMark.student_id == student_id,
            ExamMark.exam_paper_id.in_(paper_ids),
            ExamMark.deleted_at.is_(None),
        )
        .order_by(ExamMarkCorrection.decided_at)
        .all()
    )


def revision_pending(
    examination_id: str, student_id: str, tenant_id: str
) -> bool:
    """Do this student's marks now disagree with their published result?

    The window `_correctable` opens deliberately: a correction approved after
    publication changes the mark and leaves the published figures alone. This
    is how a school sees that the two have parted company and a revision is
    owed.
    """
    result = _current(examination_id, student_id, tenant_id)
    if result is None or result.published_at is None:
        return False
    return bool(
        corrections_since_publication(
            examination_id, student_id, tenant_id, result.published_at
        )
    )


def _next_version(examination_id: str, student_id: str, tenant_id: str) -> int:
    """One past the highest ever used, so a version is never reused even if a
    row was soft-deleted."""
    highest = (
        db.session.query(func.max(ExamResult.version))
        .filter(
            ExamResult.tenant_id == tenant_id,
            ExamResult.examination_id == examination_id,
            ExamResult.student_id == student_id,
        )
        .scalar()
    )
    return (highest or 0) + 1


# ---------------------------------------------------------------------------
# Revise
# ---------------------------------------------------------------------------


def revise_result(
    examination_id: str,
    student_id: str,
    tenant_id: str,
    *,
    reason: str,
    actor_user_id: str,
    commit: bool = True,
) -> Dict[str, Any]:
    """Recompute a published result into a new, unpublished version.

    The published version is not touched — not its figures, not its snapshot,
    not its `published_at`. It stops being *current*, which is a statement
    about which version the school is working on, not about what it said.
    """
    from modules.rbac.services import has_permission

    if not has_permission(actor_user_id, PERM_PUBLISH):
        return _refuse("FORBIDDEN", f"You do not hold {PERM_PUBLISH}.")
    # A revision names one child, so it is refused rather than filtered.
    assert_student_allowed(student_id)
    if not (reason or "").strip():
        return _refuse(
            "REASON_REQUIRED",
            "A revision must say why — reissuing a result without a reason is "
            "an edit with extra steps.",
        )

    examination = _lock_examination(examination_id, tenant_id)
    if examination is None:
        return _refuse("NOT_FOUND", "Examination not found")
    if examination.status != EXAM_PUBLISHED:
        return _refuse(
            "WRONG_STATUS",
            (
                f"Only a published examination has anything to revise; this one "
                f"is '{examination.status}'."
            ),
        )

    current = _current(examination_id, student_id, tenant_id)
    if current is None:
        return _refuse("RESULT_MISSING", "This student has no result to revise")
    if current.published_at is None:
        return _refuse(
            "RESULT_NOT_PUBLISHED",
            (
                "This student's current result has not been published, so it "
                "can simply be recalculated rather than revised."
            ),
        )

    behind = corrections_since_publication(
        examination_id, student_id, tenant_id, current.published_at
    )
    if not behind:
        return _refuse(
            "NOTHING_TO_REVISE",
            (
                "No approved correction has changed this student's marks since "
                "their result was published, so there is nothing to reissue."
            ),
        )

    try:
        with db.session.begin_nested():
            # Raises `_Refused` for a weighted paper or a non-finite mark, so a
            # revision can never write figures ordinary calculation would have
            # refused.
            computed = compute_result(examination, student_id, tenant_id)

            previous_version = current.version
            current.is_current = False

            revised = ExamResult(
                tenant_id=tenant_id,
                examination_id=examination_id,
                student_id=student_id,
                version=_next_version(examination_id, student_id, tenant_id),
                is_current=True,
                total_max=computed["total_max"],
                total_obtained=computed["total_obtained"],
                percentage=computed["percentage"],
                grade_label=computed["grade_label"],
                is_pass=computed["is_pass"],
                snapshot=computed["snapshot"],
                revision_reason=reason.strip(),
            )
            db.session.add(revised)

            record_event(
                examination,
                EVENT_RESULTS_REVISED,
                note=(
                    f"Student {student_id}: version {previous_version} → "
                    f"{revised.version} after {len(behind)} approved "
                    f"correction(s). {reason.strip()}"
                ),
                actor_user_id=actor_user_id,
            )
            db.session.flush()
    except _Refused as stop:
        return stop.refusal

    if commit:
        db.session.commit()
    return _ok(result=revised, superseded_version=previous_version)


# ---------------------------------------------------------------------------
# Publish the revision
# ---------------------------------------------------------------------------


def publish_revision(
    examination_id: str,
    student_id: str,
    tenant_id: str,
    *,
    actor_user_id: str,
    commit: bool = True,
) -> Dict[str, Any]:
    """Tell the school's audience that the revised figures are now the answer.

    Separate from revising on purpose. Recomputing a number and issuing it are
    two decisions; a school may want to look at a revision before it goes out,
    and nothing should send it merely because the arithmetic finished.

    The examination's own lifecycle does not move — it is already `published`,
    and a second transition would be a second state machine for the same fact.
    """
    from modules.rbac.services import has_permission

    from .publication_service import _unfit

    if not has_permission(actor_user_id, PERM_PUBLISH):
        return _refuse("FORBIDDEN", f"You do not hold {PERM_PUBLISH}.")
    # Issuing a revised result names one child, the same as making it.
    assert_student_allowed(student_id)

    examination = _lock_examination(examination_id, tenant_id)
    if examination is None:
        return _refuse("NOT_FOUND", "Examination not found")
    if examination.status != EXAM_PUBLISHED:
        return _refuse(
            "WRONG_STATUS",
            f"This examination is '{examination.status}', not published",
        )

    current = _current(examination_id, student_id, tenant_id)
    if current is None:
        return _refuse("RESULT_MISSING", "This student has no result")
    if current.published_at is not None:
        return _refuse(
            "ALREADY_PUBLISHED",
            "This student's current result is already published",
        )

    # The same fitness rules publication applies, not a second copy of them —
    # a revision must clear the bar the first publication had to clear.
    refusal = _unfit(current, student_id)
    if refusal:
        return refusal

    try:
        with db.session.begin_nested():
            current.published_at = utc_now()
            current.published_by_user_id = actor_user_id
            record_event(
                examination,
                EVENT_RESULTS_PUBLISHED,
                note=(
                    f"Student {student_id}: revised result version "
                    f"{current.version} published"
                ),
                actor_user_id=actor_user_id,
            )
            db.session.flush()
    except _Refused as stop:
        return stop.refusal

    if commit:
        db.session.commit()
    return _ok(result=current)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def result_history(
    examination_id: str, student_id: str, tenant_id: str
) -> List[ExamResult]:
    """Every version this student's result has had, oldest first."""
    return (
        ExamResult.query.filter(
            ExamResult.tenant_id == tenant_id,
            ExamResult.examination_id == examination_id,
            ExamResult.student_id == student_id,
        )
        .order_by(ExamResult.version)
        .all()
    )


def official_result(
    examination_id: str, student_id: str, tenant_id: str
) -> Optional[ExamResult]:
    """The version the school has actually stated — the latest **published** one.

    Deliberately not "the current one". Between a revision and its publication
    the current version is a working figure nobody has been told about, while
    the school's word is still the older published version. Anything showing a
    result to a parent must ask this, not `current_result`.
    """
    return (
        ExamResult.query.filter(
            ExamResult.tenant_id == tenant_id,
            ExamResult.examination_id == examination_id,
            ExamResult.student_id == student_id,
            ExamResult.deleted_at.is_(None),
            ExamResult.published_at.isnot(None),
        )
        .order_by(ExamResult.version.desc())
        .first()
    )
