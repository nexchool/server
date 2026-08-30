"""Changing a mark on a paper that has already been closed.

Locking a paper (migration 117) deliberately left no way back, because the
obvious way back — an unlock button — puts the register into a state where a
number can move with nothing recording that it did. This is the way back.

The shape is `attendance_corrections`, one domain over, followed rather than
re-invented: **request, then decide**. Asking is `assessment.update` plus
authority over the paper (ADR-014); deciding is `assessment.manage`, the same
split that already separates marking a register from closing it. Both outcomes
are terminal and both are kept.

Three rules do the real work here:

**The request states what it is changing *from*.** Without that, approving two
requests against the same mark applies the second one's arithmetic to a number
nobody is looking at any more. With it, the second is refused as stale and the
school is asked to look again.

**Approval re-validates from scratch.** The mark is re-read, the from-state
re-checked, and the new value run through exactly the same validation ordinary
entry uses — the one function, not a copy of its rules.

**Nothing is written unless everything is.** The mark mutation and the
approval are one savepoint; a refusal leaves the mark untouched, the request
undecided, and no event claiming otherwise.

Correcting a **published** examination is allowed (EX-03C): it changes the
mark and leaves the published result alone until somebody revises it, which is
`revision_service`'s job.

Deliberately not here: unlocking, editing a decided request, and any
notification.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.branch_scope import filter_by_exam_mark_ids
from core.database import db
from core.school_time import utc_now

from .marks_service import (
    PERM_MANAGE,
    _paper_of,
    _validate_outcome,
    marker_authority,
)
from .models import (
    CORRECTION_APPROVED,
    CORRECTION_REJECTED,
    CORRECTION_REQUESTED,
    EXAM_MARKS_ENTRY,
    EXAM_PUBLISHED,
    ExamMark,
    ExamMarkCorrection,
)
from .services import _Refused, _ok, _refuse, record_event

EVENT_MARKS_CORRECTED = "MarksCorrected"


def _as_number(value: Any) -> Optional[float]:
    return None if value is None else float(value)


def _same_state(correction: ExamMarkCorrection, mark: ExamMark) -> bool:
    """Is the mark still what the request was written against?"""
    return (
        correction.from_status == mark.status
        and _as_number(correction.from_marks) == _as_number(mark.marks_obtained)
    )


def _load(correction_id: str, tenant_id: str):
    correction = ExamMarkCorrection.query.filter_by(
        id=correction_id, tenant_id=tenant_id
    ).first()
    if correction is None:
        return None, None, None, _refuse("NOT_FOUND", "Correction not found")
    if correction.status != CORRECTION_REQUESTED:
        return None, None, None, _refuse(
            "ALREADY_DECIDED", f"This correction is already {correction.status}"
        )

    mark = ExamMark.query.filter(
        ExamMark.id == correction.exam_mark_id,
        ExamMark.tenant_id == tenant_id,
        ExamMark.deleted_at.is_(None),
    ).first()
    if mark is None:
        return None, None, None, _refuse("MARK_NOT_FOUND", "The mark is missing")

    paper, examination, refusal = _paper_of(mark.exam_paper_id, tenant_id)
    if refusal:
        return None, None, None, refusal
    return correction, mark, (paper, examination), None


def _correctable(paper, examination) -> Optional[Dict[str, Any]]:
    """A correction is for a *closed* register on a live examination.

    An open paper needs no correction — ordinary entry still writes to it, and
    routing that through an approval queue would make marking a class of forty
    a forty-request backlog.

    **A published examination is now correctable too** (EX-03C). It was refused
    while nothing could act on the consequence: moving a mark under a frozen
    snapshot left the school's published word disagreeing with its own marks,
    and there was no way to reconcile them. Result revision is that way. The
    correction changes the mark; it does **not** touch the published result,
    which stays exactly as published until somebody holding
    `examination.publish` revises it into a new version.

    That leaves a real window in which the marks and the published result
    disagree, and it is deliberate — reconciling them is a separate decision
    somebody has to take, not a side effect of approving a correction.
    `revision_service.revision_pending` is how that window is visible.

    Cancelled and pre-marking states stay refused: there is nothing to correct
    in an examination that was never marked, and nothing to reconcile in one
    that will not be held.
    """
    if not paper.marks_are_locked:
        return _refuse(
            "PAPER_NOT_LOCKED",
            "This paper is still open for marking — change the mark directly "
            "rather than raising a correction.",
        )
    if examination.status not in (EXAM_MARKS_ENTRY, EXAM_PUBLISHED):
        return _refuse(
            "WRONG_STATUS",
            (
                f"Marks can only be corrected while the examination is being "
                f"marked or after its results are published; this one is "
                f"'{examination.status}'."
            ),
        )
    return None


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


def request_correction(
    tenant_id: str,
    exam_mark_id: str,
    *,
    to_status: str,
    to_marks: Any = None,
    reason: str,
    requested_by_user_id: str,
    commit: bool = True,
) -> Dict[str, Any]:
    """Ask for a closed mark to be changed.

    Writes the request only. Nothing about the mark moves until somebody who
    runs assessment approves it — which is the whole difference between a
    correction and an edit.
    """
    if not (reason or "").strip():
        return _refuse(
            "REASON_REQUIRED",
            "A reason is required — a correction without one is an edit",
        )

    mark = ExamMark.query.filter(
        ExamMark.id == exam_mark_id,
        ExamMark.tenant_id == tenant_id,
        ExamMark.deleted_at.is_(None),
    ).first()
    if mark is None:
        return _refuse("MARK_NOT_FOUND", "Mark not found")

    paper, examination, refusal = _paper_of(mark.exam_paper_id, tenant_id)
    if refusal:
        return refusal
    refusal = _correctable(paper, examination)
    if refusal:
        return refusal

    # Asking to change a mark is an act on the paper, so it answers to the same
    # authority marking it does — a permission *and* ADR-014 standing.
    refusal = marker_authority(paper, requested_by_user_id, correcting=True)
    if refusal:
        return refusal

    to_status = (to_status or "").strip()
    refusal, value = _validate_outcome(
        to_status, to_marks, paper, who="The correction"
    )
    if refusal:
        return refusal

    if to_status == mark.status and value == _as_number(mark.marks_obtained):
        return _refuse(
            "NO_CHANGE", "That is what the mark already says"
        )

    correction = ExamMarkCorrection(
        tenant_id=tenant_id,
        exam_mark_id=mark.id,
        from_status=mark.status,
        from_marks=mark.marks_obtained,
        to_status=to_status,
        to_marks=value,
        reason=reason.strip(),
        status=CORRECTION_REQUESTED,
        requested_by_user_id=requested_by_user_id,
    )
    db.session.add(correction)

    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return _ok(correction=correction)


# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------


def approve_correction(
    tenant_id: str,
    correction_id: str,
    *,
    decided_by_user_id: str,
    note: Optional[str] = None,
    commit: bool = True,
) -> Dict[str, Any]:
    """Agree to the change, and make it — both, or neither."""
    from modules.rbac.services import has_permission

    correction, mark, context, refusal = _load(correction_id, tenant_id)
    if refusal:
        return refusal
    paper, examination = context

    if not has_permission(decided_by_user_id, PERM_MANAGE):
        return _refuse("FORBIDDEN", f"You do not hold {PERM_MANAGE}.")

    refusal = _correctable(paper, examination)
    if refusal:
        return refusal

    # Re-read and re-check: the mark may have moved since this was asked for,
    # and a stale request carries a number computed against the old one.
    if not _same_state(correction, mark):
        return _refuse(
            "STALE_CORRECTION",
            (
                "This mark has changed since the correction was requested. "
                "Look at it again and raise a new correction."
            ),
        )

    # The same validation ordinary entry runs, not a second copy of its rules —
    # so a correction can never write a value marking could not.
    refusal, value = _validate_outcome(
        correction.to_status,
        _as_number(correction.to_marks),
        paper,
        who="The correction",
    )
    if refusal:
        return refusal

    try:
        with db.session.begin_nested():
            mark.status = correction.to_status
            mark.marks_obtained = value
            mark.entered_by_user_id = decided_by_user_id
            mark.entered_at = utc_now()

            correction.status = CORRECTION_APPROVED
            correction.decided_by_user_id = decided_by_user_id
            correction.decided_at = utc_now()
            correction.decision_note = note

            record_event(
                examination,
                EVENT_MARKS_CORRECTED,
                note=(
                    f"Mark {mark.id} on paper {paper.id} for student "
                    f"{mark.student_id}: {correction.from_status} "
                    f"{_as_number(correction.from_marks)} → "
                    f"{correction.to_status} {value} "
                    f"(correction {correction.id})"
                ),
                actor_user_id=decided_by_user_id,
            )
            db.session.flush()
    except _Refused as stop:  # pragma: no cover - defensive
        return stop.refusal

    if commit:
        db.session.commit()
    return _ok(correction=correction, mark=mark)


def reject_correction(
    tenant_id: str,
    correction_id: str,
    *,
    decided_by_user_id: str,
    note: Optional[str] = None,
    commit: bool = True,
) -> Dict[str, Any]:
    """Decline the change. The mark stands, and the request is kept.

    Kept because a refused correction is itself part of the record: a school
    asked why a mark was *not* changed has an answer, with a name on it.
    """
    from modules.rbac.services import has_permission

    correction, mark, _context, refusal = _load(correction_id, tenant_id)
    if refusal:
        return refusal

    if not has_permission(decided_by_user_id, PERM_MANAGE):
        return _refuse("FORBIDDEN", f"You do not hold {PERM_MANAGE}.")

    correction.status = CORRECTION_REJECTED
    correction.decided_by_user_id = decided_by_user_id
    correction.decided_at = utc_now()
    correction.decision_note = note

    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return _ok(correction=correction, mark=mark)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def correction_queue(
    tenant_id: str, *, status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Corrections with enough context to decide on, for a whole queue at once.

    A list of ids is not something a person can act on: the reviewer needs the
    child, the paper, what the mark says now and what is being asked for.
    Fetched for the batch rather than per row — a term's backlog asked one at a
    time is the N+1 that makes a queue unusable exactly when it is long, which
    is the lesson `attendance.correction_service.context_for` already learned.

    `status` filters; omitted, it returns the whole history so an audit can
    read approved and rejected requests too.
    """
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    from .marks_service import _paper_of
    from .services import paper_labels

    query = ExamMarkCorrection.query.filter_by(tenant_id=tenant_id)
    # Scoped at the source, not per row: `_paper_of` below refuses a paper out
    # of branch, so a queue holding another campus's request would raise rather
    # than simply not show it.
    query = filter_by_exam_mark_ids(query, ExamMarkCorrection.exam_mark_id)
    if status:
        query = query.filter(ExamMarkCorrection.status == status)
    corrections = query.order_by(ExamMarkCorrection.requested_at.desc()).all()
    if not corrections:
        return []

    marks = {
        mark.id: mark
        for mark in ExamMark.query.filter(
            ExamMark.tenant_id == tenant_id,
            ExamMark.id.in_({c.exam_mark_id for c in corrections}),
        ).all()
    }
    students = {
        student.id: student
        for student in Student.query.filter(
            Student.tenant_id == tenant_id,
            Student.id.in_({m.student_id for m in marks.values()}),
        ).all()
    } if marks else {}
    people = {
        person.id: person
        for person in Person.query.filter(
            Person.id.in_({s.person_id for s in students.values() if s.person_id})
        ).all()
    } if students else {}
    user_ids = {
        user_id
        for correction in corrections
        for user_id in (correction.requested_by_user_id, correction.decided_by_user_id)
        if user_id
    }
    users = {
        user.id: user
        for user in User.query.filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    # Paper labels are resolved once per paper, not once per correction: a
    # queue of forty on one paper would otherwise ask forty times.
    labels: Dict[str, tuple] = {}
    papers: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []
    for correction in corrections:
        mark = marks.get(correction.exam_mark_id)
        paper_id = mark.exam_paper_id if mark else None
        if paper_id and paper_id not in labels:
            paper, examination, _refusal = _paper_of(paper_id, tenant_id)
            papers[paper_id] = (paper, examination)
            labels[paper_id] = paper_labels(paper_id, tenant_id)
        paper, examination = papers.get(paper_id, (None, None))
        class_name, subject_name = labels.get(paper_id, (None, None))
        student = students.get(mark.student_id) if mark else None
        person = people.get(student.person_id) if student else None
        requester = users.get(correction.requested_by_user_id)
        decider = users.get(correction.decided_by_user_id)

        rows.append({
            "correction": correction,
            "student_id": student.id if student else None,
            "admission_number": student.admission_number if student else None,
            "full_name": person.full_name if person else None,
            "exam_paper_id": paper_id,
            "class_name": class_name,
            "subject_name": subject_name,
            "examination_id": examination.id if examination else None,
            "examination_name": examination.name if examination else None,
            "max_marks": float(paper.max_marks) if paper is not None else None,
            "requested_by_name": getattr(requester, "name", None),
            "decided_by_name": getattr(decider, "name", None),
        })
    return rows


def corrections_for_mark(
    exam_mark_id: str, tenant_id: str
) -> List[ExamMarkCorrection]:
    """Every request ever raised against this mark, oldest first."""
    return (
        ExamMarkCorrection.query.filter_by(
            exam_mark_id=exam_mark_id, tenant_id=tenant_id
        )
        .order_by(ExamMarkCorrection.requested_at)
        .all()
    )


def pending_corrections(tenant_id: str) -> List[ExamMarkCorrection]:
    """The queue somebody has to work through."""
    query = filter_by_exam_mark_ids(
        ExamMarkCorrection.query.filter_by(
            tenant_id=tenant_id, status=CORRECTION_REQUESTED
        ),
        ExamMarkCorrection.exam_mark_id,
    )
    return query.order_by(ExamMarkCorrection.requested_at).all()
