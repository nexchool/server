"""Recording what students scored.

Four rules decide every operation here, and each is enforced in one place:

**Grain.** One mark per (paper, student). Theory and practical are separate
papers (ADR-016), so they are separate marks — there is no SubjectMark and no
per-component mark record.

**Eligibility** comes from the student's enrollment in the paper's class, not
from a roll number and not from a list a caller supplies. An `additional`
enrollment counts: a child in a JEE batch sits that batch's papers.

**Authority** comes from ADR-014. Whoever teaches this subject in this class
*on the day of the paper* may mark it — resolved through
`subject_teacher_of(class_id, subject_id, on=exam_date)`, the same service
attendance uses. There is no exam-specific teacher, and adding one would be a
second authority model.

**Absence is a status, never a number.** The database already refuses a mark
for anyone who was not present; this service refuses the inverse mistakes
earlier, with a message naming the student.

Correcting a mark on a paper that has already been closed lives next door, in
`corrections_service.py` — it is a request somebody decides, not a write.

Deliberately not here: result computation, grading, aggregation, notifications.
Locking exists so those can be built without finding the marks already changed
underneath them.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.branch_scope import assert_exam_paper_allowed
from core.database import db
from core.school_time import utc_now
from modules.academics.backbone.models import StudentClassEnrollment
from modules.academics.teaching_assignment import subject_teacher_of
from modules.classes.models import ClassSubject
from modules.students.models import Student

from .models import (
    EXAM_MARKS_ENTRY,
    MARK_PRESENT,
    MARK_STATUSES,
    ExamMark,
    ExamPaper,
    Examination,
)
from .services import _Refused, _refuse, _ok, record_event

# Entering marks and correcting them are different acts, so they answer to
# different keys — both already in the central catalogue. `assessment.manage`
# is the head's key: whoever runs assessment may mark any paper, which is how
# a school covers for an absent teacher without inventing a delegation.
PERM_ENTER = "assessment.enter"
PERM_UPDATE = "assessment.update"
PERM_MANAGE = "assessment.manage"

EVENT_MARKS_LOCKED = "MarksLocked"


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


# Where a paper's cohort came from. An open paper asks the school who is in
# the class; a closed one asks its own register.
COHORT_ENROLLMENT = "enrollment"
COHORT_REGISTER = "register"


def _currently_enrolled_ids(paper: ExamPaper) -> List[str]:
    """Every student enrolled in the paper's class today — **both** primary and
    additional. A child attending a vacation batch holds an `additional`
    enrollment in that batch's class and sits its papers; filtering to primary
    would leave a batch unmarkable."""
    rows = (
        db.session.query(StudentClassEnrollment.student_id)
        .filter(
            StudentClassEnrollment.tenant_id == paper.tenant_id,
            StudentClassEnrollment.class_id == paper.class_id,
            StudentClassEnrollment.is_current.is_(True),
        )
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


def _recorded_student_ids(paper: ExamPaper) -> List[str]:
    """Everyone this paper actually has a mark for."""
    rows = (
        db.session.query(ExamMark.student_id)
        .filter(
            ExamMark.tenant_id == paper.tenant_id,
            ExamMark.exam_paper_id == paper.id,
            ExamMark.deleted_at.is_(None),
        )
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


def paper_cohort(paper: ExamPaper) -> Tuple[List[str], str]:
    """Who this paper is about, and where that answer came from.

    **Open paper — the class, as it stands.** The question is "who can I mark
    now?", and current enrollment answers it exactly.

    **Locked paper — the register it recorded.** Current enrollment stops being
    able to answer, and does so silently. Promotion sets every prior-year
    enrollment `is_current = False`, so last year's papers would report an
    empty class. A section transfer *rewrites* `class_id` on the same row (the
    canon: "Section Transfer modifies the current Academic Enrollment"), so a
    child moved from 10A to 10B in August disappears from 10A's July register
    and appears in 10B's — a paper they never sat. Withdrawal does the same.

    The marks do not move. `ExamMark` is keyed on (paper, student), so once a
    paper is closed its own rows are the only account of who sat it that cannot
    be rewritten by something that happens afterwards.

    **This deliberately cannot invent the students who were never marked.** A
    paper locked with 33 of 35 marked reports those 33. The other two are not
    recoverable without a cohort snapshot taken at lock time, and guessing them
    from today's enrollment would be the very substitution this exists to stop.
    `marking_progress` reports `outstanding = None` there rather than a zero
    that would read as "everybody was marked".
    """
    if paper.marks_locked_at is not None:
        return _recorded_student_ids(paper), COHORT_REGISTER
    return _currently_enrolled_ids(paper), COHORT_ENROLLMENT


def eligible_student_ids(paper: ExamPaper) -> List[str]:
    """The paper's cohort — live while it is open, its register once closed."""
    students, _ = paper_cohort(paper)
    return students


def is_eligible(paper: ExamPaper, student_id: str) -> bool:
    """Is this student part of the paper's cohort? Same rule as `paper_cohort`,
    asked about one student so a register of forty is not loaded to answer it."""
    if paper.marks_locked_at is not None:
        return (
            db.session.query(ExamMark.id)
            .filter(
                ExamMark.tenant_id == paper.tenant_id,
                ExamMark.exam_paper_id == paper.id,
                ExamMark.student_id == student_id,
                ExamMark.deleted_at.is_(None),
            )
            .first()
            is not None
        )
    return (
        db.session.query(StudentClassEnrollment.id)
        .filter(
            StudentClassEnrollment.tenant_id == paper.tenant_id,
            StudentClassEnrollment.class_id == paper.class_id,
            StudentClassEnrollment.student_id == student_id,
            StudentClassEnrollment.is_current.is_(True),
        )
        .first()
        is not None
    )


# ---------------------------------------------------------------------------
# Authority
# ---------------------------------------------------------------------------


def marker_authority(
    paper: ExamPaper, user_id: str, *, correcting: bool = False
) -> Optional[Dict[str, Any]]:
    """May this person mark this paper? Returns a refusal, or None.

    Two things must both hold, and conflating them is the mistake this guards:

    * **a permission** — `assessment.enter` to record, `assessment.update` to
      correct. This says what kind of act somebody may perform at all.
    * **authority over this paper** — they teach this subject in this class on
      the day it was sat (ADR-014), or they hold `assessment.manage`.

    A teacher with `assessment.enter` and no assignment here may mark nothing.
    A head with `assessment.manage` may mark anything, because somebody has to
    be able to when a teacher is away.
    """
    from modules.rbac.services import has_permission

    needed = PERM_UPDATE if correcting else PERM_ENTER
    if not has_permission(user_id, needed):
        return _refuse(
            "FORBIDDEN",
            f"You do not hold {needed}.",
        )

    if has_permission(user_id, PERM_MANAGE):
        return None

    offering = ClassSubject.query.filter_by(
        id=paper.class_subject_id, tenant_id=paper.tenant_id
    ).first()
    if offering is None:
        return _refuse("OFFERING_NOT_FOUND", "The paper's subject offering is missing")

    from modules.teachers.services import teacher_for_user

    teacher = teacher_for_user(user_id, paper.tenant_id)
    if teacher is None:
        return _refuse(
            "NOT_THE_MARKER",
            "Only the teacher of this subject may mark this paper.",
        )

    held = subject_teacher_of(
        paper.class_id, offering.subject_id, on=paper.exam_date
    )
    if held is None or held.teacher_id != teacher.id:
        return _refuse(
            "NOT_THE_MARKER",
            (
                "You do not teach this subject in this class on the day of the "
                "paper."
            ),
        )
    return None


# ---------------------------------------------------------------------------
# Status semantics
# ---------------------------------------------------------------------------


def _validate_outcome(
    status: str, marks_obtained: Any, paper: ExamPaper, *, who: str
) -> Tuple[Optional[Dict[str, Any]], Optional[float]]:
    """The rule the database also holds, refused here with a name attached.

    Present means a number. Absent, exempted and malpractice mean no number —
    a zero would fail the student and drag every aggregate, and the school
    would have no way to tell the two apart afterwards.

    Returns the refusal *and* the normalised number, so the value that is
    stored is the one that was checked. Coercing a second time at the write
    would let the two drift apart.
    """
    if status not in MARK_STATUSES:
        return _refuse(
            "STATUS_INVALID",
            f"{who}: status must be one of {', '.join(MARK_STATUSES)}",
        ), None

    if status != MARK_PRESENT:
        if marks_obtained is not None:
            return _refuse(
                "MARKS_NOT_ALLOWED",
                (
                    f"{who}: a student recorded as '{status}' has no mark. "
                    "Recording zero would say they sat the paper and scored "
                    "nothing."
                ),
            ), None
        return None, None

    if marks_obtained is None:
        return _refuse(
            "MARKS_REQUIRED",
            (
                f"{who}: a present student needs a mark. If they did not sit "
                "the paper, record them as absent."
            ),
        ), None
    try:
        value = float(marks_obtained)
    except (TypeError, ValueError):
        return _refuse("MARKS_INVALID", f"{who}: marks must be a number"), None

    # NaN and the infinities have to be refused by name, before the range
    # checks — not through them. Every comparison against NaN is False, so
    # `value < 0` and `value > max_marks` both pass it, and Postgres `numeric`
    # accepts NaN with `marks_obtained >= 0` evaluating TRUE. It would reach
    # the column and turn every later sum into NaN. A spreadsheet cell reading
    # "nan" is all it takes.
    if not math.isfinite(value):
        return _refuse(
            "MARKS_INVALID", f"{who}: marks must be an ordinary number"
        ), None

    if value < 0:
        return _refuse("MARKS_INVALID", f"{who}: marks cannot be negative"), None
    if value > float(paper.max_marks):
        return _refuse(
            "MARKS_ABOVE_MAX",
            f"{who}: {value:g} is more than the paper's {float(paper.max_marks):g}",
        ), None
    return None, value


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


def _paper_open_for_marking(
    paper: ExamPaper, examination: Examination
) -> Optional[Dict[str, Any]]:
    """Marks may be written only while the examination is being marked and the
    paper has not been closed."""
    if examination.status != EXAM_MARKS_ENTRY:
        return _refuse(
            "WRONG_STATUS",
            (
                f"Marks can only be entered while the examination is in "
                f"marks entry; this one is '{examination.status}'."
            ),
        )
    if paper.marks_locked_at is not None:
        return _refuse(
            "PAPER_LOCKED",
            (
                "This paper has been closed for marking. A change now needs a "
                "correction, which keeps what was recorded before."
            ),
        )
    return None


def _paper_of(paper_id: str, tenant_id: str):
    paper = ExamPaper.query.filter(
        ExamPaper.id == paper_id,
        ExamPaper.tenant_id == tenant_id,
        ExamPaper.deleted_at.is_(None),
    ).first()
    if paper is None:
        return None, None, _refuse("PAPER_NOT_FOUND", "Exam paper not found")
    assert_exam_paper_allowed(paper.id)
    examination = Examination.query.filter(
        Examination.id == paper.examination_id,
        Examination.tenant_id == tenant_id,
        Examination.deleted_at.is_(None),
    ).first()
    if examination is None:
        return None, None, _refuse("NOT_FOUND", "The paper's examination is missing")
    return paper, examination, None


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


def record_mark(
    *,
    tenant_id: str,
    exam_paper_id: str,
    student_id: str,
    status: str,
    marks_obtained: Any = None,
    remarks: Optional[str] = None,
    actor_user_id: str,
    commit: bool = True,
) -> Dict[str, Any]:
    """Record — or correct — one student's outcome for one paper.

    Deliberately one operation rather than `enter` plus `update`. The row is
    unique per (paper, student), so a second entry is the same act performed
    again; splitting it would leave a caller guessing which to call and the
    unique index deciding.

    `remarks` reuses the existing column (EX-00). No new field was needed.
    """
    result = record_marks(
        tenant_id=tenant_id,
        exam_paper_id=exam_paper_id,
        rows=[{
            "student_id": student_id,
            "status": status,
            "marks_obtained": marks_obtained,
            "remarks": remarks,
        }],
        actor_user_id=actor_user_id,
        commit=commit,
    )
    if not result["success"]:
        return result
    return _ok(mark=result["marks"][0], created=result["created"])


def record_marks(
    *,
    tenant_id: str,
    exam_paper_id: str,
    rows: Iterable[Dict[str, Any]],
    actor_user_id: str,
    commit: bool = True,
) -> Dict[str, Any]:
    """Record a register's worth of outcomes for one paper.

    **All or nothing.** A sheet of forty with one bad row writes nothing —
    partial success would leave a teacher unable to tell which half landed, and
    re-submitting would be ambiguous. The bulk *file* boundary (workbook
    parsing, row-level error reports) is EX-02B; this is the service it will
    call once it has resolved students to ids.

    Students are identified by `student_id`. Roll numbers are deliberately not
    accepted: they are nullable, non-unique across sections and — until a
    caller resolves them against the enrollment for the right year — ambiguous.
    """
    paper, examination, refusal = _paper_of(exam_paper_id, tenant_id)
    if refusal:
        return refusal

    refusal = _paper_open_for_marking(paper, examination)
    if refusal:
        return refusal

    rows = list(rows)
    if not rows:
        return _refuse("NO_ROWS", "No marks were supplied")

    existing = {
        m.student_id: m
        for m in ExamMark.query.filter(
            ExamMark.tenant_id == tenant_id,
            ExamMark.exam_paper_id == paper.id,
            ExamMark.deleted_at.is_(None),
        ).all()
    }

    # Correcting an already-recorded mark is a different act from recording one
    # for the first time, so the sheet's authority is the stronger of the two
    # it actually performs.
    correcting = any(row.get("student_id") in existing for row in rows)
    refusal = marker_authority(paper, actor_user_id, correcting=correcting)
    if refusal:
        return refusal

    # The live class, explicitly: this path is reachable only for an open paper
    # (`_paper_open_for_marking` above), and "who may be marked now" is always
    # the enrolment answer. Naming it directly keeps that true if the cohort
    # rule is ever changed.
    eligible = set(_currently_enrolled_ids(paper))
    seen: set = set()
    written: List[ExamMark] = []
    created = 0

    # A refusal has to leave the savepoint by exception: returning from inside
    # the block exits it normally, which *commits* the savepoint and would
    # leave the rows before the bad one written.
    try:
        with db.session.begin_nested():
            for index, row in enumerate(rows):
                student_id = row.get("student_id")
                if not student_id:
                    raise _Refused(_refuse(
                        "STUDENT_REQUIRED", f"Row {index + 1}: student_id is required"
                    ))
                if student_id in seen:
                    raise _Refused(_refuse(
                        "STUDENT_REPEATED",
                        f"Row {index + 1}: this student appears more than once",
                    ))
                seen.add(student_id)

                who = _describe(student_id, tenant_id)
                if student_id not in eligible:
                    raise _Refused(_refuse(
                        "STUDENT_NOT_ELIGIBLE",
                        (
                            f"{who} is not currently enrolled in the class this "
                            "paper is set for."
                        ),
                    ))

                status = (row.get("status") or MARK_PRESENT).strip()
                refusal, value = _validate_outcome(
                    status, row.get("marks_obtained"), paper, who=who
                )
                if refusal:
                    raise _Refused(refusal)

                mark = existing.get(student_id)
                if mark is None:
                    mark = ExamMark(
                        tenant_id=tenant_id,
                        exam_paper_id=paper.id,
                        student_id=student_id,
                    )
                    db.session.add(mark)
                    created += 1

                mark.status = status
                # The number the validation checked, not the caller's original
                # — a sheet from an import carries "88" as text, and the column
                # should hold what was actually vetted.
                mark.marks_obtained = value
                if "remarks" in row:
                    mark.remarks = (row.get("remarks") or None)
                mark.entered_by_user_id = actor_user_id
                mark.entered_at = utc_now()
                written.append(mark)

            db.session.flush()
    except _Refused as stop:
        return stop.refusal

    if commit:
        db.session.commit()
    return _ok(marks=written, created=created, updated=len(written) - created)


def _describe(student_id: str, tenant_id: str) -> str:
    """Name the student in a refusal. A row number alone is not actionable."""
    student = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
    if student is None:
        return f"Student {student_id}"
    person = getattr(student, "person", None)
    name = getattr(person, "full_name", None)
    return name or student.admission_number or f"Student {student_id}"


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


def lock_paper(
    paper_id: str,
    tenant_id: str,
    *,
    actor_user_id: str,
    commit: bool = True,
) -> Dict[str, Any]:
    """Close one paper for marking.

    Locking is a decision about a finished register, so it answers to
    `assessment.manage` rather than to the teacher who marked it — the same
    split attendance uses between marking and finalising.
    """
    from modules.rbac.services import has_permission

    paper, examination, refusal = _paper_of(paper_id, tenant_id)
    if refusal:
        return refusal
    if not has_permission(actor_user_id, PERM_MANAGE):
        return _refuse("FORBIDDEN", f"You do not hold {PERM_MANAGE}.")
    if examination.status != EXAM_MARKS_ENTRY:
        return _refuse(
            "WRONG_STATUS",
            f"Only a paper being marked can be closed; this examination is "
            f"'{examination.status}'.",
        )
    if paper.marks_locked_at is not None:
        return _refuse("ALREADY_LOCKED", "This paper is already closed for marking")

    paper.marks_locked_at = utc_now()
    paper.marks_locked_by_user_id = actor_user_id
    # One event per paper, on the examination's timeline. Individual marks are
    # deliberately NOT events: a register of forty would be forty rows saying
    # nothing the mark itself does not already carry in entered_by/entered_at.
    record_event(
        examination,
        EVENT_MARKS_LOCKED,
        note=f"Marking closed for paper {paper.id}",
        actor_user_id=actor_user_id,
    )

    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return _ok(paper=paper)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def marks_for_paper(paper_id: str, tenant_id: str) -> List[ExamMark]:
    return (
        ExamMark.query.filter(
            ExamMark.exam_paper_id == paper_id,
            ExamMark.tenant_id == tenant_id,
            ExamMark.deleted_at.is_(None),
        ).all()
    )


def marking_register(paper_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Everything a marks-entry screen needs for one paper, in one read.

    The register a teacher actually works down: who is in it, what each of them
    has so far, and whether the paper is still open. `eligible_student_ids`
    answers with ids, which is right for the write path and useless on screen —
    a teacher marks *Rahul, 00123*, not a UUID.

    The cohort is `paper_cohort`, not a fresh enrolment query, so this cannot
    drift from what `record_marks` will accept: EX-02A.1's rule (open paper →
    current enrolment, closed paper → its own register) holds here by
    construction rather than by being copied.

    **Students with no mark are present in the list and carry no status.** A
    row with `status = None` is the sixth state — not yet entered — and it is
    deliberately not represented as absent, as a zero, or as a missing row the
    screen has to notice on its own.

    Ordered the way a school reads a register: roll number where the section
    numbers its children, then admission number, so the order is stable when it
    does not.
    """
    from modules.people.models import Person

    paper = ExamPaper.query.filter_by(id=paper_id, tenant_id=tenant_id).first()
    if paper is None:
        return None
    assert_exam_paper_allowed(paper.id)

    examination = Examination.query.filter(
        Examination.id == paper.examination_id,
        Examination.tenant_id == tenant_id,
        Examination.deleted_at.is_(None),
    ).first()
    if examination is None:
        return None

    cohort, source = paper_cohort(paper)
    marks = {
        mark.student_id: mark
        for mark in marks_for_paper(paper_id, tenant_id)
    }

    rows = []
    if cohort:
        found = (
            db.session.query(
                Student.id,
                Student.admission_number,
                Person.full_name,
                StudentClassEnrollment.roll_number,
            )
            .join(Person, Person.id == Student.person_id)
            .outerjoin(
                StudentClassEnrollment,
                db.and_(
                    StudentClassEnrollment.student_id == Student.id,
                    StudentClassEnrollment.tenant_id == Student.tenant_id,
                    StudentClassEnrollment.class_id == paper.class_id,
                    StudentClassEnrollment.is_current.is_(True),
                ),
            )
            .filter(
                Student.tenant_id == tenant_id,
                Student.id.in_(cohort),
            )
            .all()
        )
        for student_id, admission_number, full_name, roll_number in found:
            mark = marks.get(student_id)
            rows.append({
                "student_id": student_id,
                # The mark's own id, which a correction targets. Null where no
                # mark exists — there is nothing to correct.
                "mark_id": mark.id if mark is not None else None,
                "admission_number": admission_number,
                "full_name": full_name,
                "roll_number": roll_number,
                # None means no row exists — never "absent", never zero.
                "status": mark.status if mark is not None else None,
                "marks_obtained": (
                    float(mark.marks_obtained)
                    if mark is not None and mark.marks_obtained is not None
                    else None
                ),
                "remarks": mark.remarks if mark is not None else None,
            })
        rows.sort(
            key=lambda row: (
                row["roll_number"] is None,
                row["roll_number"] or 0,
                row["admission_number"] or "",
            )
        )

    from .services import paper_labels

    class_name, subject_name = paper_labels(paper_id, tenant_id)
    return {
        "paper": paper,
        "class_name": class_name,
        "subject_name": subject_name,
        "examination": examination,
        "cohort_source": source,
        # The one place the screen learns whether it may write, and it is the
        # same guard the write path applies.
        "open_for_marking": _paper_open_for_marking(paper, examination) is None,
        "progress": marking_progress(paper_id, tenant_id),
        "students": rows,
    }


def marking_progress(paper_id: str, tenant_id: str) -> Dict[str, Any]:
    """How far a register has got.

    "Marks entry is open" never means "everyone has a mark" — a real class has
    students still unentered while others are done — so progress is reported
    rather than enforced.

    Once the paper is closed, `outstanding` is **None, not zero**. The cohort is
    then the register itself, so subtracting gives zero by construction — and
    zero would claim everybody was marked, which is exactly what a paper locked
    with two students missing did not do. The number of students who were never
    marked is not recoverable after the fact without a snapshot taken at lock
    time; saying so is better than a figure that looks answered.
    """
    paper = ExamPaper.query.filter_by(id=paper_id, tenant_id=tenant_id).first()
    if paper is None:
        return {
            "eligible": 0,
            "recorded": 0,
            "outstanding": 0,
            "locked": False,
            "cohort_source": COHORT_ENROLLMENT,
        }

    cohort, source = paper_cohort(paper)
    recorded = len(marks_for_paper(paper_id, tenant_id))
    locked = paper.marks_locked_at is not None
    return {
        "eligible": len(cohort),
        "recorded": recorded,
        "outstanding": None if locked else max(len(cohort) - recorded, 0),
        "locked": locked,
        "cohort_source": source,
    }
