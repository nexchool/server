"""Creating, scheduling and cancelling examinations.

Follows the conventions the student and staff lifecycles already set: refusals
are `{"success": False, "code", "error"}` so neither transport matches on
English, and `record_event` adds to the caller's transaction rather than
committing on its own.

Two rules here are worth reading before changing anything:

**A caller never supplies `class_id`.** A paper's class is read off the
offering it examines, so the denormalised column cannot disagree with its
owner. Migration 116 makes the database refuse a disagreement too; this makes
it unreachable.

**Nothing guesses a cycle.** An examination names one explicitly, or the
service refuses. There is no "current cycle", no default and no date guess —
several cycles run at once, so any of those would silently place an
examination in the wrong operating period.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Iterable, List, Optional

from core.database import db
from core.school_time import school_today
from modules.academics.backbone.models import AcademicTerm
from modules.academics.calendar.models import ExamWindow
from modules.academics.cycles.models import AcademicCycle
from modules.classes.models import Class, ClassSubject

from .models import (
    EXAM_CANCELLED,
    EXAM_DRAFT,
    EXAM_MARKS_ENTRY,
    EXAM_PUBLISHED,
    EXAM_SCHEDULED,
    ExamMark,
    ExamPaper,
    ExamType,
    Examination,
    ExaminationLifecycleEvent,
    GradingScheme,
)

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
#
# Stored states are decisions. Whether an examination is upcoming, running or
# over is derived from its papers' dates and is never written down.
#
# Cancellation is reachable from every state a school might realise it is not
# going ahead — except `published`, because results are already the school's
# word and withdrawing them is a revision, not a cancellation.
_TRANSITIONS: Dict[str, tuple] = {
    EXAM_DRAFT: (EXAM_SCHEDULED, EXAM_CANCELLED),
    EXAM_SCHEDULED: (EXAM_MARKS_ENTRY, EXAM_CANCELLED),
    EXAM_MARKS_ENTRY: (EXAM_PUBLISHED, EXAM_CANCELLED),
    EXAM_PUBLISHED: (),
    EXAM_CANCELLED: (),
}

# Named from docs/architecture/business-events.md, not invented here.
EVENT_SCHEDULED = "ExaminationScheduled"
EVENT_CANCELLED = "ExaminationCancelled"
EVENT_MARKS_ENTRY_OPENED = "MarksEntryOpened"
EVENT_RESULTS_PUBLISHED = "ResultsPublished"

_EVENT_FOR_STATUS = {
    EXAM_SCHEDULED: EVENT_SCHEDULED,
    EXAM_MARKS_ENTRY: EVENT_MARKS_ENTRY_OPENED,
    EXAM_PUBLISHED: EVENT_RESULTS_PUBLISHED,
    EXAM_CANCELLED: EVENT_CANCELLED,
}

# Once an examination is being marked, its shape is what the marks were entered
# against. Editing a paper's maximum underneath entered marks changes what a
# score means without touching the score.
_SHAPE_EDITABLE_IN = (EXAM_DRAFT, EXAM_SCHEDULED)


def _refuse(code: str, message: str) -> Dict[str, Any]:
    """Say no in a way both transports can read (the lifecycle convention)."""
    return {"success": False, "code": code, "error": message}


def _ok(**payload: Any) -> Dict[str, Any]:
    return {"success": True, **payload}


# ---------------------------------------------------------------------------
# Resolution and validation
# ---------------------------------------------------------------------------


def _cycle(cycle_id: str, tenant_id: str) -> Optional[AcademicCycle]:
    if not cycle_id:
        return None
    return (
        AcademicCycle.query.filter(
            AcademicCycle.id == cycle_id,
            AcademicCycle.tenant_id == tenant_id,
            AcademicCycle.deleted_at.is_(None),
        ).first()
    )


def _validate_term(
    term_id: Optional[str], cycle: AcademicCycle, tenant_id: str
) -> Optional[Dict[str, Any]]:
    """A term is optional; when named it must belong to this cycle.

    Optional on purpose (ADR-017): a board examination is scheduled by the
    board, and a surprise unit test belongs to no term the school planned.
    """
    if not term_id:
        return None
    term = AcademicTerm.query.filter(
        AcademicTerm.id == term_id,
        AcademicTerm.tenant_id == tenant_id,
        AcademicTerm.deleted_at.is_(None),
    ).first()
    if term is None:
        return _refuse("TERM_NOT_FOUND", "Academic term not found")
    if term.academic_cycle_id != cycle.id:
        return _refuse(
            "TERM_WRONG_CYCLE",
            f"'{term.name}' belongs to a different academic cycle",
        )
    return None


def _validate_window(
    window_id: Optional[str], cycle: AcademicCycle, tenant_id: str
) -> Optional[Dict[str, Any]]:
    """A calendar reservation the examination sits in, where one was made.

    `exam_windows` is scoped to the academic **year**, not the cycle — it
    predates cycles and is the calendar's booking of time, which this does not
    change. So the strongest check the schema supports is that the window and
    the examination's cycle report under the same year.
    """
    if not window_id:
        return None
    window = ExamWindow.query.filter(
        ExamWindow.id == window_id, ExamWindow.tenant_id == tenant_id
    ).first()
    if window is None:
        return _refuse("WINDOW_NOT_FOUND", "Exam window not found")
    if window.academic_year_id != cycle.academic_year_id:
        return _refuse(
            "WINDOW_WRONG_YEAR",
            f"'{window.name}' belongs to a different academic year",
        )
    return None


def _validate_offering(
    class_subject_id: str, cycle: AcademicCycle, tenant_id: str
) -> tuple:
    """Resolve the offering a paper examines, and the class it implies.

    Returns `(class_subject, refusal)` — exactly one is None. The class is
    **derived**, never accepted from a caller, so `exam_papers.class_id` cannot
    contradict the offering it names.
    """
    offering = ClassSubject.query.filter(
        ClassSubject.id == class_subject_id,
        ClassSubject.tenant_id == tenant_id,
        ClassSubject.deleted_at.is_(None),
    ).first()
    if offering is None:
        return None, _refuse(
            "OFFERING_NOT_FOUND", f"Class subject {class_subject_id} not found"
        )
    if offering.status != "active":
        return None, _refuse(
            "OFFERING_INACTIVE",
            "That subject is no longer offered by this class",
        )

    cls = Class.query.filter(
        Class.id == offering.class_id, Class.tenant_id == tenant_id
    ).first()
    if cls is None:
        return None, _refuse("CLASS_NOT_FOUND", "The offering's class is missing")
    if cls.academic_cycle_id != cycle.id:
        return None, _refuse(
            "CLASS_WRONG_CYCLE",
            (
                f"{cls.display_name or cls.section} runs in a different academic "
                "cycle than this examination"
            ),
        )
    if getattr(cls, "merged_into_class_id", None):
        return None, _refuse(
            "CLASS_MERGED",
            "That section has been merged; schedule the section it merged into",
        )
    return offering, None


def _validate_paper_date(
    exam_date: Optional[datetime.date], cycle: AcademicCycle
) -> Optional[Dict[str, Any]]:
    """A sitting happens while the school is open.

    The cycle is the operating boundary (ADR-017); the academic year's dates
    are reporting context and are deliberately not used here. A paper with no
    date yet is a draft schedule, which is allowed.
    """
    if exam_date is None:
        return None
    if not (cycle.start_date <= exam_date <= cycle.end_date):
        return _refuse(
            "DATE_OUTSIDE_CYCLE",
            (
                f"{exam_date.isoformat()} falls outside '{cycle.name}' "
                f"({cycle.start_date} – {cycle.end_date})"
            ),
        )
    return None


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def record_event(
    examination: Examination,
    event_name: str,
    *,
    occurred_on: Optional[datetime.date] = None,
    note: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> ExaminationLifecycleEvent:
    """Write one milestone to an examination's history.

    Added to the session, not committed: an event describes something the
    caller is doing, so it belongs in that caller's transaction. Rows are never
    edited — a correction is another event.
    """
    row = ExaminationLifecycleEvent(
        tenant_id=examination.tenant_id,
        examination_id=examination.id,
        event_name=event_name,
        occurred_on=occurred_on or school_today(),
        note=note,
        actor_user_id=actor_user_id,
    )
    db.session.add(row)
    return row


def timeline_for(examination_id: str, tenant_id: str) -> List[ExaminationLifecycleEvent]:
    return (
        ExaminationLifecycleEvent.query.filter_by(
            examination_id=examination_id, tenant_id=tenant_id
        )
        .order_by(ExaminationLifecycleEvent.occurred_on, ExaminationLifecycleEvent.created_at)
        .all()
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def create_examination(
    *,
    tenant_id: str,
    academic_cycle_id: str,
    exam_type_id: str,
    name: str,
    description: Optional[str] = None,
    academic_term_id: Optional[str] = None,
    grading_scheme_id: Optional[str] = None,
    exam_window_id: Optional[str] = None,
    papers: Optional[Iterable[Dict[str, Any]]] = None,
    created_by_user_id: Optional[str] = None,
    commit: bool = True,
) -> Dict[str, Any]:
    """Open an assessment event, optionally with its sittings.

    Atomic: an examination with twelve papers either lands whole or not at all.
    A savepoint rather than a bare rollback so an outer transaction — a seed, a
    bulk import — survives the refusal.
    """
    if not (name or "").strip():
        return _refuse("NAME_REQUIRED", "Examination name is required")

    cycle = _cycle(academic_cycle_id, tenant_id)
    if cycle is None:
        return _refuse(
            "CYCLE_NOT_FOUND",
            "Academic cycle not found. An examination must say which operating "
            "period it belongs to — there is no default.",
        )

    exam_type = ExamType.query.filter(
        ExamType.id == exam_type_id,
        ExamType.tenant_id == tenant_id,
        ExamType.deleted_at.is_(None),
    ).first()
    if exam_type is None:
        return _refuse("EXAM_TYPE_NOT_FOUND", "Examination type not found")

    refusal = _validate_term(academic_term_id, cycle, tenant_id)
    if refusal:
        return refusal
    refusal = _validate_window(exam_window_id, cycle, tenant_id)
    if refusal:
        return refusal

    if grading_scheme_id:
        scheme = GradingScheme.query.filter(
            GradingScheme.id == grading_scheme_id,
            GradingScheme.tenant_id == tenant_id,
            GradingScheme.deleted_at.is_(None),
        ).first()
        if scheme is None:
            return _refuse("GRADING_SCHEME_NOT_FOUND", "Grading scheme not found")

    clash = Examination.query.filter(
        Examination.tenant_id == tenant_id,
        Examination.academic_cycle_id == cycle.id,
        Examination.name == name.strip(),
        Examination.deleted_at.is_(None),
    ).first()
    if clash is not None:
        return _refuse(
            "NAME_TAKEN",
            f"'{name.strip()}' already exists in '{cycle.name}'",
        )

    examination = Examination(
        tenant_id=tenant_id,
        academic_cycle_id=cycle.id,
        academic_term_id=academic_term_id or None,
        exam_type_id=exam_type.id,
        grading_scheme_id=grading_scheme_id or None,
        exam_window_id=exam_window_id or None,
        name=name.strip(),
        description=description,
        status=EXAM_DRAFT,
        created_by_user_id=created_by_user_id,
    )

    try:
        with db.session.begin_nested():
            db.session.add(examination)
            db.session.flush()

            if papers:
                refusal = _add_papers_impl(
                    examination=examination, cycle=cycle, specs=papers,
                    tenant_id=tenant_id,
                )
                if refusal:
                    raise _Refused(refusal)
    except _Refused as stop:
        return stop.refusal

    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return _ok(examination=examination)


class _Refused(Exception):
    """Carries a refusal out of a savepoint so the savepoint rolls back."""

    def __init__(self, refusal: Dict[str, Any]):
        super().__init__(refusal.get("error", "refused"))
        self.refusal = refusal


# ---------------------------------------------------------------------------
# Papers
# ---------------------------------------------------------------------------


def _add_papers_impl(
    *,
    examination: Examination,
    cycle: AcademicCycle,
    specs: Iterable[Dict[str, Any]],
    tenant_id: str,
) -> Optional[Dict[str, Any]]:
    """Create the sittings. Returns a refusal, or None when every one landed.

    Runs inside the caller's savepoint, so a refusal on the seventeenth paper
    takes the first sixteen with it.
    """
    # Duplicates within one request are caught here rather than by the unique
    # index, so the message names the offering instead of an index.
    seen: set = set()
    existing = {
        (p.class_subject_id, p.component_label or "")
        for p in ExamPaper.query.filter_by(
            tenant_id=tenant_id, examination_id=examination.id
        ).filter(ExamPaper.deleted_at.is_(None)).all()
    }

    for index, spec in enumerate(specs):
        class_subject_id = spec.get("class_subject_id")
        if not class_subject_id:
            return _refuse(
                "OFFERING_REQUIRED", f"Paper {index + 1}: class_subject_id is required"
            )

        offering, refusal = _validate_offering(class_subject_id, cycle, tenant_id)
        if refusal:
            return refusal

        component = (spec.get("component_label") or "").strip()
        key = (offering.id, component)
        if key in seen or key in existing:
            label = component or "this subject"
            return _refuse(
                "PAPER_DUPLICATE",
                f"A paper for {label} is already scheduled in this examination",
            )
        seen.add(key)

        max_marks = spec.get("max_marks")
        if max_marks is None:
            return _refuse(
                "MAX_MARKS_REQUIRED", f"Paper {index + 1}: max_marks is required"
            )
        try:
            max_marks = float(max_marks)
        except (TypeError, ValueError):
            return _refuse("MAX_MARKS_INVALID", "max_marks must be a number")
        if max_marks <= 0:
            return _refuse("MAX_MARKS_INVALID", "max_marks must be greater than zero")

        pass_marks = spec.get("pass_marks")
        if pass_marks is not None:
            try:
                pass_marks = float(pass_marks)
            except (TypeError, ValueError):
                return _refuse("PASS_MARKS_INVALID", "pass_marks must be a number")
            if pass_marks < 0 or pass_marks > max_marks:
                return _refuse(
                    "PASS_MARKS_INVALID",
                    "pass_marks must be between zero and max_marks",
                )

        exam_date = spec.get("exam_date")
        refusal = _validate_paper_date(exam_date, cycle)
        if refusal:
            return refusal

        starts_at, ends_at = spec.get("starts_at"), spec.get("ends_at")
        if starts_at and ends_at and starts_at >= ends_at:
            return _refuse("TIMES_INVALID", "The paper must end after it starts")

        db.session.add(
            ExamPaper(
                tenant_id=tenant_id,
                examination_id=examination.id,
                class_subject_id=offering.id,
                # Read off the offering, never taken from the caller: this is
                # what makes the denormalisation unable to contradict its owner.
                class_id=offering.class_id,
                component_label=component,
                exam_date=exam_date,
                starts_at=starts_at,
                ends_at=ends_at,
                venue=(spec.get("venue") or None),
                max_marks=max_marks,
                pass_marks=pass_marks,
                weight=spec.get("weight"),
                instructions=(spec.get("instructions") or None),
            )
        )

    db.session.flush()
    return None


def add_papers(
    examination_id: str,
    tenant_id: str,
    specs: Iterable[Dict[str, Any]],
    *,
    commit: bool = True,
) -> Dict[str, Any]:
    """Schedule sittings against an existing examination.

    The fan-out a school actually performs: one call carrying Grade 8-A Maths,
    Grade 8-A Science, Grade 8-B Maths and Grade 8-B Science produces four
    papers, and any one of them failing produces none.
    """
    examination = _get(examination_id, tenant_id)
    if examination is None:
        return _refuse("NOT_FOUND", "Examination not found")
    if examination.status not in _SHAPE_EDITABLE_IN:
        return _refuse(
            "WRONG_STATUS",
            (
                f"Papers cannot be added once an examination is "
                f"'{examination.status}' — marks were entered against the shape "
                "it had."
            ),
        )

    cycle = _cycle(examination.academic_cycle_id, tenant_id)
    if cycle is None:
        return _refuse("CYCLE_NOT_FOUND", "The examination's academic cycle is missing")

    try:
        with db.session.begin_nested():
            refusal = _add_papers_impl(
                examination=examination, cycle=cycle, specs=specs, tenant_id=tenant_id
            )
            if refusal:
                raise _Refused(refusal)
    except _Refused as stop:
        return stop.refusal

    if commit:
        db.session.commit()
    return _ok(examination=examination)


def papers_for(examination_id: str, tenant_id: str) -> List[ExamPaper]:
    return (
        ExamPaper.query.filter_by(
            examination_id=examination_id, tenant_id=tenant_id
        )
        .filter(ExamPaper.deleted_at.is_(None))
        .order_by(ExamPaper.exam_date, ExamPaper.starts_at)
        .all()
    )


def papers_with_labels(examination_id: str, tenant_id: str) -> List[tuple]:
    """Each paper with the section and subject a person would call it by.

    `(paper, class_label, subject_name)`. A paper stores ids; a screen says
    "10-A Mathematics", and resolving that per row would be an N+1 on a list
    that is one row per section per subject. One query instead.
    """
    from modules.subjects.models import Subject

    rows = (
        db.session.query(ExamPaper, Class, Subject)
        .join(
            ClassSubject,
            db.and_(
                ClassSubject.id == ExamPaper.class_subject_id,
                ClassSubject.tenant_id == ExamPaper.tenant_id,
            ),
        )
        .join(Class, Class.id == ExamPaper.class_id)
        .join(Subject, Subject.id == ClassSubject.subject_id)
        .filter(
            ExamPaper.examination_id == examination_id,
            ExamPaper.tenant_id == tenant_id,
            ExamPaper.deleted_at.is_(None),
        )
        .order_by(ExamPaper.exam_date, ExamPaper.starts_at)
        .all()
    )
    return [
        (paper, cls.display_name or cls.section or cls.id, subject.name)
        for paper, cls, subject in rows
    ]


def paper_labels(paper_id: str, tenant_id: str) -> tuple:
    """The section and subject one paper is called by, or `(None, None)`."""
    from modules.subjects.models import Subject

    row = (
        db.session.query(Class, Subject)
        .select_from(ExamPaper)
        .join(
            ClassSubject,
            db.and_(
                ClassSubject.id == ExamPaper.class_subject_id,
                ClassSubject.tenant_id == ExamPaper.tenant_id,
            ),
        )
        .join(Class, Class.id == ExamPaper.class_id)
        .join(Subject, Subject.id == ClassSubject.subject_id)
        .filter(ExamPaper.id == paper_id, ExamPaper.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        return None, None
    cls, subject = row
    return (cls.display_name or cls.section or cls.id), subject.name


def classes_sitting(examination_id: str, tenant_id: str) -> List[str]:
    """Which sections sit this examination — derived, never declared (ADR-016)."""
    rows = (
        db.session.query(ExamPaper.class_id)
        .filter(
            ExamPaper.examination_id == examination_id,
            ExamPaper.tenant_id == tenant_id,
            ExamPaper.deleted_at.is_(None),
        )
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def _get(examination_id: str, tenant_id: str) -> Optional[Examination]:
    return Examination.query.filter(
        Examination.id == examination_id,
        Examination.tenant_id == tenant_id,
        Examination.deleted_at.is_(None),
    ).first()


# What an examination *is* and how its marks are to be read. Both change the
# meaning of marks already recorded, so both stop being editable the moment any
# exist — see `_refuse_semantic_change_once_marked`.
_FROZEN_ONCE_MARKED = ("exam_type_id", "grading_scheme_id")


def _has_any_marks(examination_id: str, tenant_id: str) -> bool:
    """Does a single mark exist against any paper of this examination?"""
    return (
        db.session.query(ExamMark.id)
        .join(
            ExamPaper,
            db.and_(
                ExamPaper.id == ExamMark.exam_paper_id,
                ExamPaper.tenant_id == ExamMark.tenant_id,
            ),
        )
        .filter(
            ExamPaper.examination_id == examination_id,
            ExamPaper.tenant_id == tenant_id,
            ExamPaper.deleted_at.is_(None),
            ExamMark.deleted_at.is_(None),
        )
        .first()
        is not None
    )


def _refuse_semantic_change_once_marked(
    examination: Examination, tenant_id: str, changes: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Marks mean something. Once any exist, that meaning stops moving.

    `exam_type_id` says what the examination *is* and `grading_scheme_id` says
    how its numbers become a result. Change either after a teacher has entered
    marks and every one of those marks is retroactively re-interpreted, with
    nothing recording that it happened — a 62 that was a pass under one scheme
    is a fail under the next.

    **The boundary is data, not status.** `status == marks_entry` is the wrong
    test in both directions: an examination sits in marks entry for days before
    the first mark arrives, during which correcting a mis-picked scheme is
    ordinary admin, and one mark on one paper out of forty is already enough to
    make the change unsafe. So the question asked is whether a mark exists.

    Re-sending the same value is not a change and is allowed, so a caller that
    PATCHes the whole object is not refused for fields it did not touch.
    """
    wanted = {
        field: changes[field]
        for field in _FROZEN_ONCE_MARKED
        if field in changes
        and (changes[field] or None) != getattr(examination, field)
    }
    if not wanted:
        return None
    if not _has_any_marks(examination.id, tenant_id):
        return None

    if "exam_type_id" in wanted:
        return _refuse(
            "EXAM_TYPE_IMMUTABLE",
            "Marks have been entered, so what kind of examination this is can "
            "no longer change — the marks were recorded against it.",
        )
    return _refuse(
        "GRADING_SCHEME_IMMUTABLE",
        "Marks have been entered, so the grading scheme can no longer change — "
        "it would silently re-grade every mark already recorded.",
    )


def update_examination(
    examination_id: str,
    tenant_id: str,
    changes: Dict[str, Any],
    *,
    commit: bool = True,
) -> Dict[str, Any]:
    """Correct an examination's details.

    The **cycle is not editable**. Moving an examination between operating
    periods would strand every paper, whose classes belong to the old one;
    that is a new examination, not an edit.
    """
    examination = _get(examination_id, tenant_id)
    if examination is None:
        return _refuse("NOT_FOUND", "Examination not found")
    if examination.status in (EXAM_PUBLISHED, EXAM_CANCELLED):
        return _refuse(
            "WRONG_STATUS",
            f"An examination that is '{examination.status}' cannot be edited",
        )

    if "academic_cycle_id" in changes:
        return _refuse(
            "CYCLE_IMMUTABLE",
            "An examination cannot move to another academic cycle — its papers "
            "belong to classes in this one.",
        )

    # Checked before anything is written, so a refusal never leaves half an
    # edit on the session.
    refusal = _refuse_semantic_change_once_marked(examination, tenant_id, changes)
    if refusal:
        return refusal

    cycle = _cycle(examination.academic_cycle_id, tenant_id)
    if cycle is None:
        return _refuse("CYCLE_NOT_FOUND", "The examination's academic cycle is missing")

    if "academic_term_id" in changes:
        refusal = _validate_term(changes["academic_term_id"], cycle, tenant_id)
        if refusal:
            return refusal
        examination.academic_term_id = changes["academic_term_id"] or None

    if "exam_window_id" in changes:
        refusal = _validate_window(changes["exam_window_id"], cycle, tenant_id)
        if refusal:
            return refusal
        examination.exam_window_id = changes["exam_window_id"] or None

    if "name" in changes:
        new_name = (changes["name"] or "").strip()
        if not new_name:
            return _refuse("NAME_REQUIRED", "Examination name is required")
        clash = Examination.query.filter(
            Examination.tenant_id == tenant_id,
            Examination.academic_cycle_id == cycle.id,
            Examination.name == new_name,
            Examination.id != examination.id,
            Examination.deleted_at.is_(None),
        ).first()
        if clash is not None:
            return _refuse("NAME_TAKEN", f"'{new_name}' already exists in '{cycle.name}'")
        examination.name = new_name

    for field in ("description", "grading_scheme_id", "exam_type_id"):
        if field not in changes:
            continue
        if field == "exam_type_id":
            found = ExamType.query.filter(
                ExamType.id == changes[field], ExamType.tenant_id == tenant_id,
                ExamType.deleted_at.is_(None),
            ).first()
            if found is None:
                return _refuse("EXAM_TYPE_NOT_FOUND", "Examination type not found")
        if field == "grading_scheme_id" and changes[field]:
            found = GradingScheme.query.filter(
                GradingScheme.id == changes[field],
                GradingScheme.tenant_id == tenant_id,
                GradingScheme.deleted_at.is_(None),
            ).first()
            if found is None:
                return _refuse("GRADING_SCHEME_NOT_FOUND", "Grading scheme not found")
        setattr(examination, field, changes[field] or None)

    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return _ok(examination=examination)


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


def may_become(examination: Examination, to_status: str) -> bool:
    """Whether this transition is allowed, without performing it.

    The same table `_transition` enforces, read rather than applied — so a
    caller with expensive validation of its own can refuse on the lifecycle
    first, and say so in the lifecycle's words, instead of reporting whatever
    its own checks happened to notice about a draft.
    """
    return to_status in _TRANSITIONS.get(examination.status, ())


def _transition(
    examination: Examination,
    to_status: str,
    *,
    note: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Move an examination, or say why not. Records the event either way it lands."""
    allowed = _TRANSITIONS.get(examination.status, ())
    if to_status not in allowed:
        return _refuse(
            "INVALID_TRANSITION",
            (
                f"An examination that is '{examination.status}' cannot become "
                f"'{to_status}'"
            ),
        )

    previous = examination.status
    examination.status = to_status
    record_event(
        examination,
        _EVENT_FOR_STATUS[to_status],
        note=note or f"{previous} → {to_status}",
        actor_user_id=actor_user_id,
    )
    return None


def schedule_examination(
    examination_id: str,
    tenant_id: str,
    *,
    actor_user_id: Optional[str] = None,
    commit: bool = True,
) -> Dict[str, Any]:
    """Announce the examination. Its papers must have dates by now.

    A scheduled examination with an undated paper is one a school cannot tell
    anybody about, so the check belongs here rather than at publication.
    """
    examination = _get(examination_id, tenant_id)
    if examination is None:
        return _refuse("NOT_FOUND", "Examination not found")

    papers = papers_for(examination_id, tenant_id)
    if not papers:
        return _refuse(
            "NO_PAPERS",
            "Add at least one paper before scheduling — an examination with no "
            "sittings is nothing to schedule.",
        )
    undated = [p for p in papers if p.exam_date is None]
    if undated:
        return _refuse(
            "PAPER_UNDATED",
            f"{len(undated)} paper(s) have no date yet",
        )

    refusal = _transition(
        examination, EXAM_SCHEDULED, actor_user_id=actor_user_id
    )
    if refusal:
        return refusal
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return _ok(examination=examination)


def open_marks_entry(
    examination_id: str,
    tenant_id: str,
    *,
    actor_user_id: Optional[str] = None,
    commit: bool = True,
) -> Dict[str, Any]:
    """The school begins recording what students scored."""
    examination = _get(examination_id, tenant_id)
    if examination is None:
        return _refuse("NOT_FOUND", "Examination not found")

    refusal = _transition(
        examination, EXAM_MARKS_ENTRY, actor_user_id=actor_user_id
    )
    if refusal:
        return refusal
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return _ok(examination=examination)


# Publication lives in `publication_service.py` (EX-03B). It used to live here
# as a transition-only stub that moved an examination to `published` without
# looking at a single result — which was correct while no result existed, and
# became a way to publish nothing the moment they did. There is one door, and
# it checks the whole cohort before it opens.


def cancel_examination(
    examination_id: str,
    tenant_id: str,
    *,
    reason: str,
    actor_user_id: Optional[str] = None,
    commit: bool = True,
) -> Dict[str, Any]:
    """The examination will not be held.

    **Not a delete.** The papers stay, any marks stay, and the row stays —
    a school asked why a September examination does not appear in its results
    needs to be able to answer, and `deleted_at` would take the answer away.
    A reason is required for the same purpose.
    """
    if not (reason or "").strip():
        return _refuse(
            "REASON_REQUIRED",
            "Say why the examination is cancelled — a cancellation without a "
            "reason is a disappearance.",
        )

    examination = _get(examination_id, tenant_id)
    if examination is None:
        return _refuse("NOT_FOUND", "Examination not found")
    if examination.status == EXAM_PUBLISHED:
        return _refuse(
            "ALREADY_PUBLISHED",
            "Results are already published. Revise them rather than cancelling "
            "the examination they came from.",
        )

    refusal = _transition(
        examination, EXAM_CANCELLED, note=reason.strip(), actor_user_id=actor_user_id
    )
    if refusal:
        return refusal
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return _ok(examination=examination)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


# The largest page any caller may have. Capped here rather than at the
# transport, because a cap a caller can route around is not a cap.
MAX_PAGE_SIZE = 100


def _examination_query(
    tenant_id: str,
    *,
    academic_cycle_id: Optional[str] = None,
    status: Optional[str] = None,
):
    """The one query behind both the list and its count.

    One builder, so a filter added to the page and not the total is not drift
    a school finds by asking why the header disagrees with the rows.
    """
    query = Examination.query.filter(
        Examination.tenant_id == tenant_id, Examination.deleted_at.is_(None)
    )
    if academic_cycle_id:
        query = query.filter(Examination.academic_cycle_id == academic_cycle_id)
    if status:
        query = query.filter(Examination.status == status)
    return query


def list_examinations(
    tenant_id: str,
    *,
    academic_cycle_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[Examination]:
    """Newest first. `limit` is clamped to `MAX_PAGE_SIZE`.

    Offset rather than a cursor, and for the reason the conventions give for
    classes: nothing an examination is ordered by is unique, immutable and
    meaningful to a school. The thing itself is bounded — a cycle holds a
    handful of examinations, not fifteen thousand children.
    """
    query = _examination_query(
        tenant_id, academic_cycle_id=academic_cycle_id, status=status
    )
    query = query.order_by(Examination.created_at.desc(), Examination.id)
    if offset:
        query = query.offset(max(offset, 0))
    if limit is not None:
        query = query.limit(min(max(limit, 0), MAX_PAGE_SIZE))
    return query.all()


def count_examinations(
    tenant_id: str,
    *,
    academic_cycle_id: Optional[str] = None,
    status: Optional[str] = None,
) -> int:
    """How many match, ignoring paging — counted only when asked for."""
    return _examination_query(
        tenant_id, academic_cycle_id=academic_cycle_id, status=status
    ).count()


def list_exam_types(tenant_id: str) -> List[ExamType]:
    """The kinds of examination this school has defined, in its own order.

    A read the scheduling wizard needs, living here rather than in a resolver:
    a query written in the transport is a service that was not written, and it
    can then only ever be reached by GraphQL.
    """
    return (
        ExamType.query.filter(
            ExamType.tenant_id == tenant_id, ExamType.deleted_at.is_(None)
        )
        .order_by(ExamType.sequence, ExamType.name)
        .all()
    )


def expand_subject_set(
    tenant_id: str,
    *,
    class_ids: Iterable[str],
    subjects: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """One set of subjects, fanned across several sections, as paper specs.

    The act a school actually performs when it schedules a half yearly: pick
    Grade 10 A and B, pick the six subjects with their marks and dates, and get
    twelve papers. Doing that in a client would mean the client resolving which
    offering teaches Maths in 10B — and an offering is what a paper's
    `class_id` is derived from, so a client that resolves it badly is a client
    inventing a paper's class.

    So the expansion lives here, next to the rules it has to respect, and
    returns specs in exactly the shape `create_examination`/`add_papers`
    already accept. It validates nothing else: every spec it produces still
    goes through `_add_papers_impl`, which owns dates, duplicates, maxima and
    the cycle check.

    A section that does not teach one of the subjects is refused by name
    rather than skipped. Silently dropping it would schedule an examination
    the school believes covers a class it does not.
    """
    from modules.classes.models import Class, ClassSubject

    class_ids = [c for c in class_ids if c]
    subjects = list(subjects)
    if not class_ids:
        return _refuse("SECTIONS_REQUIRED", "Choose at least one section")
    if not subjects:
        return _refuse("SUBJECTS_REQUIRED", "Choose at least one subject")

    sections = {
        row.id: row
        for row in Class.query.filter(
            Class.tenant_id == tenant_id, Class.id.in_(class_ids)
        ).all()
    }
    missing = [c for c in class_ids if c not in sections]
    if missing:
        return _refuse(
            "CLASS_NOT_FOUND",
            f"{len(missing)} of the chosen sections do not belong to this school",
        )

    offerings = {
        (row.class_id, row.subject_id): row
        for row in ClassSubject.query.filter(
            ClassSubject.tenant_id == tenant_id,
            ClassSubject.class_id.in_(class_ids),
            ClassSubject.deleted_at.is_(None),
        ).all()
    }

    specs: List[Dict[str, Any]] = []
    for class_id in class_ids:
        for subject in subjects:
            subject_id = subject.get("subject_id")
            if not subject_id:
                return _refuse(
                    "SUBJECT_REQUIRED", "Every chosen subject needs a subject_id"
                )
            offering = offerings.get((class_id, subject_id))
            if offering is None:
                label = sections[class_id].display_name or class_id
                return _refuse(
                    "OFFERING_NOT_FOUND",
                    f"{label} does not teach one of the chosen subjects",
                )
            spec = {k: v for k, v in subject.items() if k != "subject_id"}
            spec["class_subject_id"] = offering.id
            specs.append(spec)

    return _ok(papers=specs)


def get_examination(examination_id: str, tenant_id: str) -> Optional[Examination]:
    return _get(examination_id, tenant_id)
