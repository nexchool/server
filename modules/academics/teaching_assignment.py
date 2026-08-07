"""Teaching Assignment — the single abstraction for who teaches what.

Every academic module asks this module its teaching questions. None of them
query `class_subject_teachers` or `class_teacher_assignments` directly, and none
of them read `classes.teacher_id`, which is a cache (ADR-014).

The reason is not tidiness. Teaching has been remodelled twice already, and each
time the modules that had reached for a table had to be found and changed. A
service is one place to change; a table is read from wherever somebody happened
to be standing.

Two questions, deliberately kept apart
--------------------------------------

**Who teaches this subject in this class?** Owned by `class_subject_teachers`.

**Who is responsible for this class?** Owned by `class_teacher_assignments`.

They were blurred once — a boolean on a subject row — and the confusion cost
real work to unpick. This module answers them with separate calls that cannot
be mistaken for each other.

Time is part of the question
----------------------------

Every call takes ``on``:

- ``on=None`` asks **who teaches it now**. Used by today's attendance, today's
  timetable, deciding who to notify.
- ``on=<date>`` asks **who taught it then**. Used by marks, a report card for a
  term already closed, an audit of a past decision.

A historical question answered with today's assignment is a wrong answer that
looks right — a report card crediting a teacher who took the class over in
January for work marked in August. So the date is a parameter rather than a
default, and the caller has to mean it.

Reading for a whole page
------------------------

Resolving teaching one row at a time is how a list becomes a thousand queries.
Every ``*_for`` method takes a collection and returns a mapping, so a page is
read once. Use those in list endpoints; the singular calls are for one record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional

from core.database import db
from core.school_time import school_today


# Roles a teaching responsibility can carry. "primary" is the person answerable
# for it; an assistant supports them without being answerable.
ROLE_PRIMARY = "primary"
ROLE_ASSISTANT = "assistant"


@dataclass(frozen=True)
class TeachingAssignment:
    """One teacher's responsibility, as the school understands it.

    Deliberately not a database row: callers should not care which table
    answered, and two tables do answer.
    """

    teacher_id: str
    class_id: str
    role: str
    subject_id: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None

    @property
    def is_primary(self) -> bool:
        return self.role == ROLE_PRIMARY

    def was_in_effect_on(self, day: date) -> bool:
        """Whether this responsibility covered the given day.

        An assignment with no dates has always been in effect — which is what
        undated records carried over from v1 mean, and reading them as "never
        in effect" would erase teaching that demonstrably happened.
        """
        if self.effective_from and day < self.effective_from:
            return False
        if self.effective_to and day > self.effective_to:
            return False
        return True


# ---------------------------------------------------------------------------
# Who teaches a subject
# ---------------------------------------------------------------------------

def subject_teachers_for(
    class_ids: Iterable[str], *, on: Optional[date] = None
) -> Dict[tuple, List[TeachingAssignment]]:
    """Subject teaching across these classes, keyed by (class_id, subject_id).

    One query for the whole page. A list endpoint should call this once rather
    than calling :func:`subject_teacher_of` per row.
    """
    from modules.academics.backbone.models import ClassSubjectTeacher
    from modules.classes.models import ClassSubject

    class_ids = [c for c in set(class_ids) if c]
    if not class_ids:
        return {}

    rows = (
        db.session.query(ClassSubjectTeacher, ClassSubject)
        .join(ClassSubject, ClassSubject.id == ClassSubjectTeacher.class_subject_id)
        .filter(ClassSubject.class_id.in_(class_ids))
        .all()
    )

    found: Dict[tuple, List[TeachingAssignment]] = {}
    for assignment, class_subject in rows:
        held = TeachingAssignment(
            teacher_id=assignment.teacher_id,
            class_id=class_subject.class_id,
            subject_id=class_subject.subject_id,
            role=assignment.role or ROLE_PRIMARY,
            effective_from=assignment.effective_from,
            effective_to=assignment.effective_to,
        )
        if not _counts_on(assignment, held, on):
            continue
        found.setdefault((class_subject.class_id, class_subject.subject_id), []).append(held)
    return found


def subject_teacher_of(
    class_id: str, subject_id: str, *, on: Optional[date] = None
) -> Optional[TeachingAssignment]:
    """The teacher answerable for this subject in this class.

    The primary teacher when there is one; otherwise whoever is assigned, since
    a school that recorded an assistant and no primary still has somebody
    teaching the subject.
    """
    held = subject_teachers_for([class_id], on=on).get((class_id, subject_id), [])
    if not held:
        return None
    return next((a for a in held if a.is_primary), held[0])


def subjects_taught_by(
    teacher_id: str, *, on: Optional[date] = None
) -> List[TeachingAssignment]:
    """Every subject this teacher takes, and in which class."""
    from modules.academics.backbone.models import ClassSubjectTeacher
    from modules.classes.models import ClassSubject

    rows = (
        db.session.query(ClassSubjectTeacher, ClassSubject)
        .join(ClassSubject, ClassSubject.id == ClassSubjectTeacher.class_subject_id)
        .filter(ClassSubjectTeacher.teacher_id == teacher_id)
        .all()
    )

    held = []
    for assignment, class_subject in rows:
        found = TeachingAssignment(
            teacher_id=teacher_id,
            class_id=class_subject.class_id,
            subject_id=class_subject.subject_id,
            role=assignment.role or ROLE_PRIMARY,
            effective_from=assignment.effective_from,
            effective_to=assignment.effective_to,
        )
        if _counts_on(assignment, found, on):
            held.append(found)
    return held


# ---------------------------------------------------------------------------
# Who is responsible for a class
# ---------------------------------------------------------------------------

def class_teachers_for(
    class_ids: Iterable[str], *, on: Optional[date] = None
) -> Dict[str, List[TeachingAssignment]]:
    """Class-teacher responsibility across these classes, keyed by class_id.

    One query for the whole page.
    """
    from modules.academics.backbone.models import ClassTeacherAssignment

    class_ids = [c for c in set(class_ids) if c]
    if not class_ids:
        return {}

    rows = (
        ClassTeacherAssignment.query
        .filter(
            ClassTeacherAssignment.class_id.in_(class_ids),
            ClassTeacherAssignment.deleted_at.is_(None),
        )
        .all()
    )

    found: Dict[str, List[TeachingAssignment]] = {}
    for assignment in rows:
        held = TeachingAssignment(
            teacher_id=assignment.teacher_id,
            class_id=assignment.class_id,
            role=assignment.role or ROLE_PRIMARY,
            effective_from=assignment.effective_from,
            effective_to=assignment.effective_to,
        )
        if not _counts_on(assignment, held, on):
            continue
        found.setdefault(assignment.class_id, []).append(held)
    return found


def class_teacher_of(
    class_id: str, *, on: Optional[date] = None
) -> Optional[TeachingAssignment]:
    """The teacher responsible for this class — the one a parent asks for."""
    held = class_teachers_for([class_id], on=on).get(class_id, [])
    if not held:
        return None
    return next((a for a in held if a.is_primary), held[0])


def classes_taught_by(
    teacher_id: str, *, on: Optional[date] = None
) -> List[TeachingAssignment]:
    """Every class this teacher is responsible for as its class teacher."""
    from modules.academics.backbone.models import ClassTeacherAssignment

    rows = (
        ClassTeacherAssignment.query
        .filter(
            ClassTeacherAssignment.teacher_id == teacher_id,
            ClassTeacherAssignment.deleted_at.is_(None),
        )
        .all()
    )

    held = []
    for assignment in rows:
        found = TeachingAssignment(
            teacher_id=teacher_id,
            class_id=assignment.class_id,
            role=assignment.role or ROLE_PRIMARY,
            effective_from=assignment.effective_from,
            effective_to=assignment.effective_to,
        )
        if _counts_on(assignment, found, on):
            held.append(found)
    return held


# ---------------------------------------------------------------------------
# Questions a module asks about one teacher
# ---------------------------------------------------------------------------

def teaches_anything_in(
    teacher_id: str, class_id: str, *, on: Optional[date] = None
) -> bool:
    """Whether this teacher has any responsibility for this class.

    Either kind counts: taking one subject and being the class teacher are both
    reasons a teacher belongs to a class, which is what callers asking this
    actually mean.
    """
    if any(a.class_id == class_id for a in classes_taught_by(teacher_id, on=on)):
        return True
    return any(a.class_id == class_id for a in subjects_taught_by(teacher_id, on=on))


def teacher_ids_teaching_in(
    class_ids: Iterable[str], *, on: Optional[date] = None
) -> set:
    """Every teacher with any responsibility across these classes.

    Used where a caller needs the set rather than the detail — branch scoping
    asks exactly this to decide whose teacher a teacher is.
    """
    class_ids = [c for c in set(class_ids) if c]
    if not class_ids:
        return set()

    teachers = {
        a.teacher_id
        for held in class_teachers_for(class_ids, on=on).values()
        for a in held
    }
    teachers |= {
        a.teacher_id
        for held in subject_teachers_for(class_ids, on=on).values()
        for a in held
    }
    return teachers


# ---------------------------------------------------------------------------

def _counts_on(row, held: TeachingAssignment, on: Optional[date]) -> bool:
    """Whether a stored assignment answers the question being asked.

    Asking about **now** means the assignment must still be one the school
    keeps — `is_active` — and must cover today.

    Asking about **a past date** ignores `is_active`, because that flag
    describes the assignment's standing today, not its standing then. A teacher
    who handed a class over in December was still its teacher in November, and
    a report card for November must say so.
    """
    if on is None:
        return bool(getattr(row, "is_active", True)) and held.was_in_effect_on(school_today())
    return held.was_in_effect_on(on)


# ---------------------------------------------------------------------------
# For callers that must compose SQL
# ---------------------------------------------------------------------------

def current_teaching_links(tenant_id: str):
    """(class_id, teacher_id) for everyone currently teaching, as a query.

    Some callers cannot use the Python API above: a class list that sorts by
    how many teachers a class has must compute that aggregate in SQL, or the
    sort cannot be applied before the page is taken.

    They still must not know *which tables* express teaching — that is the
    knowledge this module exists to hold — so it is offered as a composable
    query instead. The same shape `core.branch_scope` uses for the same reason.

    Current only. A caller needing history wants the dated API above, because
    "as of when" cannot be expressed in a join without saying when.
    """
    from modules.academics.backbone.models import (
        ClassSubjectTeacher,
        ClassTeacherAssignment,
    )
    from modules.classes.models import ClassSubject

    responsible = (
        db.session.query(
            ClassTeacherAssignment.class_id.label("class_id"),
            ClassTeacherAssignment.teacher_id.label("teacher_id"),
        )
        .filter(
            ClassTeacherAssignment.tenant_id == tenant_id,
            ClassTeacherAssignment.is_active.is_(True),
            ClassTeacherAssignment.deleted_at.is_(None),
        )
    )

    teaching_a_subject = (
        db.session.query(
            ClassSubject.class_id.label("class_id"),
            ClassSubjectTeacher.teacher_id.label("teacher_id"),
        )
        .join(ClassSubject, ClassSubject.id == ClassSubjectTeacher.class_subject_id)
        .filter(
            ClassSubjectTeacher.tenant_id == tenant_id,
            ClassSubjectTeacher.is_active.is_(True),
        )
    )

    return responsible.union(teaching_a_subject)
