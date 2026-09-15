# Mobile Academic Calendar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a read-only, audience-scoped Academic Calendar on the Expo client, and make every calendar read on the server return only what the caller is entitled to see.

**Architecture:** A single `CalendarAudience` value, resolved from the signed-in identity, is threaded into the one existing calendar read path (`_collect_day_sets`, `list_exam_windows`, `list_school_events`). Everything downstream — `compute_summary`, `get_days_feed`, every GraphQL field — inherits the filter. Mobile reads the already-GraphQL calendar API and renders a month grid plus a day list; it has no write surface.

**Tech Stack:** Flask + SQLAlchemy 2 + Strawberry GraphQL (server); Expo ~54 + React Native + TanStack Query v5 + i18next (client).

**Spec:** `server/docs/architecture/specs/2026-09-15-mobile-academic-calendar.md`

**Branch:** all work on `develop` in each repo (v2 migration period — see `.claude/rules/git-conventions.md`). Both repos are already on `develop` and already dirty with unrelated work: **stage only the files each task names.**

---

## File structure

### `server/`

| File | Responsibility |
|---|---|
| `modules/academics/teaching_assignment.py` (modify) | gains `class_ids_taught_by()` — every class a teacher stands in front of, class-teacher duty ∪ subject teaching |
| `modules/academics/calendar/audience.py` (create) | `CalendarAudience` + `resolve_calendar_audience()`. Knows nothing about calendars — only about who is asking |
| `modules/academics/calendar/services.py` (modify) | applies an audience in `_collect_day_sets`, `list_exam_windows`, `list_school_events` |
| `modules/academics/calendar/resolvers.py` (modify) | gains `currentAcademicCalendar` |
| `modules/academics/calendar/graphql/types.py` (modify) | gains the `CurrentCalendar` type |
| `modules/rbac/catalog.py` (modify) | Student + Parent gain `academic_calendar.read` |
| `tests/test_calendar_audience.py` (create) | the §1 visibility matrix, one test per row |

### `client/`

| File | Responsibility |
|---|---|
| `common/services/graphql.ts` (create) | the shared `gql()` POST helper, lifted out of `academicStructureService.ts` |
| `modules/academic-calendar/types.ts` (create) | `CalendarDay`, `CalendarSummary`, `CurrentCalendar` |
| `modules/academic-calendar/services/academicCalendarService.ts` (create) | the one GraphQL query |
| `modules/academic-calendar/hooks/useCurrentCalendar.ts` (create) | TanStack Query wrapper |
| `modules/academic-calendar/components/CalendarMonthGrid.tsx` (create) | month grid with per-day markers |
| `modules/academic-calendar/components/CalendarDayCard.tsx` (create) | one entry in the day list |
| `modules/academic-calendar/components/CalendarLegend.tsx` (create) | the dot key |
| `modules/academic-calendar/screens/AcademicCalendarScreen.tsx` (create) | composes the above |
| `app/(protected)/academic-calendar.tsx` (create) | route + feature guard |
| `i18n/resources/{en,gu,hi}/academicCalendar.json` (create) | copy |

---

## Task 1: `class_ids_taught_by()` — every class a teacher stands in front of

**Why this task exists:** `classes_taught_by()` reads `ClassTeacherAssignment` **only** — its docstring says "as its class teacher". A subject teacher who is not the class teacher gets an empty list from it. The agreed rule is every class they teach, so this needs the union with `ClassSubjectTeacher`. Do not change `classes_taught_by()` — attendance depends on its narrower meaning.

**Files:**
- Modify: `server/modules/academics/teaching_assignment.py`
- Test: `server/tests/test_calendar_audience.py` (created here, extended by later tasks)

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_calendar_audience.py`:

```python
"""Who sees what on the academic calendar.

The matrix in docs/architecture/specs/2026-09-15-mobile-academic-calendar.md
§1, one test per row. These are authorization tests: a failure here is a
teacher reading another class's exam schedule, not a cosmetic defect.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def two_classes(db_session, tenant):
    """Two classes in one tenant: the teacher teaches one of them."""
    from modules.classes.models import Class

    rows = [
        Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="Std 8",
            section="A", academic_year_id=None,
        ),
        Class(
            id=_new_id("c-"), tenant_id=tenant.id, name="Std 12",
            section="B", academic_year_id=None,
        ),
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


def test_subject_teaching_counts_as_teaching_the_class(db_session, tenant, two_classes):
    """A subject teacher who is not the class teacher still teaches the class.

    `classes_taught_by` answers "class teacher of", which is a narrower
    question and the one attendance asks. Reusing it here would have hidden a
    maths teacher's own exam window from them.
    """
    from modules.academics.backbone.models import ClassSubject, ClassSubjectTeacher
    from modules.academics.teaching_assignment import class_ids_taught_by

    taught, other = two_classes
    teacher_id = _new_id("t-")

    offering = ClassSubject(
        id=_new_id("cs-"), tenant_id=tenant.id, class_id=taught.id,
        subject_id=_new_id("s-"), weekly_periods=5,
    )
    db_session.add(offering)
    db_session.flush()
    db_session.add(
        ClassSubjectTeacher(
            id=_new_id("cst-"), tenant_id=tenant.id,
            class_subject_id=offering.id, teacher_id=teacher_id,
            role="primary", is_active=True,
        )
    )
    db_session.flush()

    reached = class_ids_taught_by(teacher_id)

    assert taught.id in reached
    assert other.id not in reached


def test_class_teacher_duty_counts_too(db_session, tenant, two_classes):
    from modules.academics.backbone.models import ClassTeacherAssignment
    from modules.academics.teaching_assignment import class_ids_taught_by

    owned, other = two_classes
    teacher_id = _new_id("t-")

    db_session.add(
        ClassTeacherAssignment(
            id=_new_id("cta-"), tenant_id=tenant.id, class_id=owned.id,
            teacher_id=teacher_id, role="primary", is_active=True,
        )
    )
    db_session.flush()

    reached = class_ids_taught_by(teacher_id)

    assert reached == {owned.id}
    assert other.id not in reached
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd server && pytest tests/test_calendar_audience.py -v
```

Expected: `ImportError: cannot import name 'class_ids_taught_by'`.

`ClassSubject` lives in `modules/classes/models.py` and is re-exported from `modules/academics/backbone/models.py`. If the import in the test fails, import it from `modules.classes.models` instead and note the correction — do not add a new re-export.

- [ ] **Step 3: Implement**

Append to `server/modules/academics/teaching_assignment.py`:

```python
def class_ids_taught_by(teacher_id: str) -> Set[str]:
    """Every class this teacher stands in front of.

    The union of both ways a teacher meets a class: class-teacher duty
    (`ClassTeacherAssignment`) and subject teaching (`ClassSubjectTeacher`).

    Deliberately not `classes_taught_by()`, which answers the narrower "class
    teacher of" — the question attendance asks when deciding who may take a
    register. Asking it here would hide a maths teacher's own exam window from
    them because somebody else is the class teacher.
    """
    from modules.academics.backbone.models import (
        ClassSubjectTeacher,
        ClassTeacherAssignment,
    )
    from modules.classes.models import ClassSubject

    owned = (
        db.session.query(ClassTeacherAssignment.class_id)
        .filter(
            ClassTeacherAssignment.teacher_id == teacher_id,
            ClassTeacherAssignment.is_active.is_(True),
            ClassTeacherAssignment.deleted_at.is_(None),
        )
    )
    taught = (
        db.session.query(ClassSubject.class_id)
        .join(ClassSubjectTeacher, ClassSubjectTeacher.class_subject_id == ClassSubject.id)
        .filter(
            ClassSubjectTeacher.teacher_id == teacher_id,
            ClassSubjectTeacher.is_active.is_(True),
            ClassSubjectTeacher.deleted_at.is_(None),
            ClassSubject.deleted_at.is_(None),
        )
    )
    return {row[0] for row in owned.all()} | {row[0] for row in taught.all()}
```

Add to the imports at the top of that file if not already present:

```python
from typing import Set

from core.database import db
```

- [ ] **Step 4: Run the tests**

```bash
cd server && pytest tests/test_calendar_audience.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Prove nothing else moved**

```bash
cd server && pytest tests/test_attendance.py tests/test_academic_calendar.py -q
```

Expected: same pass count as before this task. `classes_taught_by()` is untouched, so attendance must be unaffected — if it isn't, the wrong function was edited.

- [ ] **Step 6: Commit**

```bash
cd server && git add modules/academics/teaching_assignment.py tests/test_calendar_audience.py
git commit -m "feat(academics): add class_ids_taught_by for subject-teacher scope"
```

---

## Task 2: `CalendarAudience` and `resolve_calendar_audience()`

**Files:**
- Create: `server/modules/academics/calendar/audience.py`
- Test: `server/tests/test_calendar_audience.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_calendar_audience.py`:

```python
def test_manage_holder_is_unrestricted(db_session, tenant):
    """An admin sees the whole calendar — the shape admin-web has always had."""
    from modules.academics.calendar.audience import resolve_calendar_audience
    from tests.test_calendar_setup_graphql import _staff_with

    user, _ = _staff_with(db_session, tenant, "academic_calendar.manage")

    audience = resolve_calendar_audience(user)

    assert audience.unrestricted is True
    assert audience.class_ids is None


def test_office_staff_without_teaching_are_unrestricted(db_session, tenant):
    """A view-only sub-admin keeps the view they have on admin-web today.

    Narrowing is keyed on being a teacher or a student, not on lacking
    `manage` — otherwise this task would silently take the calendar away from
    the office desk.
    """
    from modules.academics.calendar.audience import resolve_calendar_audience
    from tests.test_calendar_setup_graphql import _staff_with

    user, _ = _staff_with(db_session, tenant, "academic_calendar.read")

    audience = resolve_calendar_audience(user)

    assert audience.unrestricted is True


def test_teacher_is_scoped_to_the_classes_they_teach(db_session, tenant, two_classes, teaching_user):
    from modules.academics.calendar.audience import resolve_calendar_audience

    user, taught_class_id = teaching_user

    audience = resolve_calendar_audience(user)

    assert audience.unrestricted is False
    assert audience.class_ids == {taught_class_id}
    assert audience.applies_to == {"entire_school", "students", "teachers", "staff"}


def test_student_is_scoped_to_their_own_class_and_hides_staff_events(
    db_session, tenant, two_classes, studying_user
):
    from modules.academics.calendar.audience import resolve_calendar_audience

    user, own_class_id = studying_user

    audience = resolve_calendar_audience(user)

    assert audience.unrestricted is False
    assert audience.class_ids == {own_class_id}
    assert audience.applies_to == {"entire_school", "students"}
```

And these two fixtures, above the tests:

```python
@pytest.fixture
def teaching_user(db_session, tenant, two_classes):
    """A signed-in account that teaches the first of `two_classes`.

    Built through Person → Staff → Teacher because `teacher_for_user` reaches
    the teaching record along that chain, not through `teachers.user_id`
    (ADR-001/003/005). Setting the column instead resolves to nobody.
    """
    from modules.academics.backbone.models import ClassTeacherAssignment
    from tests.conftest import make_teacher_user

    taught, _other = two_classes
    user, teacher = make_teacher_user(db_session, tenant)
    db_session.add(
        ClassTeacherAssignment(
            id=_new_id("cta-"), tenant_id=tenant.id, class_id=taught.id,
            teacher_id=teacher.id, role="primary", is_active=True,
        )
    )
    db_session.flush()
    return user, taught.id


@pytest.fixture
def studying_user(db_session, tenant, two_classes):
    from tests.conftest import make_student_user

    own, _other = two_classes
    user, _student = make_student_user(db_session, tenant, class_id=own.id)
    return user, own.id
```

**Before writing these fixtures, check what `server/tests/conftest.py` already offers:**

```bash
cd server && grep -n "^def \|^@pytest.fixture" tests/conftest.py | grep -i "teacher\|student\|user\|profile"
```

If `make_teacher_user` / `make_student_user` do not exist, build them inline in the fixture from the pattern `_staff_with` uses in `tests/test_calendar_setup_graphql.py` (User → Role → `grant_profile_to`), adding the Person/Staff/Teacher (or Person/Student) rows the chain needs. **Do not call `create_app()` in these tests** — it rebinds the global Celery and breaks unrelated test files downstream.

- [ ] **Step 2: Run and watch it fail**

```bash
cd server && pytest tests/test_calendar_audience.py -v
```

Expected: `ModuleNotFoundError: No module named 'modules.academics.calendar.audience'`.

- [ ] **Step 3: Implement**

Create `server/modules/academics/calendar/audience.py`:

```python
"""Who is asking, and therefore how much of the calendar they get.

One value answers it for every calendar read. The alternative — each read
deciding for itself — is how a teacher came to be able to read the Std 12
board-exam schedule from a Std 8 account.

Narrowing keys on *identity*, not on which permission string the caller
holds: `academic_calendar.read` means "may open the calendar", and being a
teacher or a student is what decides how much of it comes back. A caller who
is neither — the office desk, a view-only sub-admin — keeps the whole view
they have on admin-web today.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Optional

from flask import g

# Every audience value a school event or holiday can be addressed to.
ALL_AUDIENCES = frozenset({"entire_school", "students", "teachers", "staff"})
# What a student is entitled to. A staff meeting is not their information.
STUDENT_AUDIENCES = frozenset({"entire_school", "students"})


@dataclass(frozen=True)
class CalendarAudience:
    """How much of the calendar one caller may see."""

    unrestricted: bool
    class_ids: Optional[FrozenSet[str]]
    applies_to: FrozenSet[str]

    def may_see_exam(self, applicable_class_ids) -> bool:
        """An exam window is visible when it touches a class of theirs.

        An empty list means the whole school — that is the field's existing
        meaning, set when a window is created without a class scope.
        """
        if self.unrestricted:
            return True
        if not applicable_class_ids:
            return True
        return bool(set(applicable_class_ids) & (self.class_ids or frozenset()))

    def may_see_audience(self, applies_to: Optional[str]) -> bool:
        """A holiday or event addressed to `applies_to` is visible to them."""
        if self.unrestricted:
            return True
        return (applies_to or "entire_school") in self.applies_to


UNRESTRICTED = CalendarAudience(
    unrestricted=True, class_ids=None, applies_to=ALL_AUDIENCES
)


def resolve_calendar_audience(user=None) -> CalendarAudience:
    """The audience of whoever is signed in.

    Pass `user` explicitly from tests; request code leaves it out and the
    caller on `g` is used.
    """
    from modules.academics.teaching_assignment import class_ids_taught_by
    from modules.auth.parents import children_of_account
    from modules.rbac.services import has_permission
    from modules.students.services import student_for_user
    from modules.teachers.services import teacher_for_user

    if user is None:
        user = getattr(g, "current_user", None)
    if user is None:
        # No caller means no entitlement. The permission classes on the
        # resolvers reject this long before here; answering "everything"
        # would make that the only thing standing in the way.
        return CalendarAudience(
            unrestricted=False, class_ids=frozenset(), applies_to=frozenset()
        )

    if has_permission(user.id, "academic_calendar.manage") or has_permission(
        user.id, "system.manage"
    ):
        return UNRESTRICTED

    teacher = teacher_for_user(user.id)
    if teacher is not None:
        return CalendarAudience(
            unrestricted=False,
            class_ids=frozenset(class_ids_taught_by(teacher.id)),
            applies_to=ALL_AUDIENCES,
        )

    student = student_for_user(user.id)
    if student is None:
        # Separate parent logins (ADR-011): resolve through the children.
        children = children_of_account(user)
        if children:
            return CalendarAudience(
                unrestricted=False,
                class_ids=frozenset(
                    child.class_id for child in children if child.class_id
                ),
                applies_to=STUDENT_AUDIENCES,
            )
    if student is not None:
        return CalendarAudience(
            unrestricted=False,
            class_ids=frozenset({student.class_id} if student.class_id else ()),
            applies_to=STUDENT_AUDIENCES,
        )

    # Office staff, view-only sub-admins: neither teaching nor studying, so
    # there is no "their students" to narrow to.
    return UNRESTRICTED
```

- [ ] **Step 4: Run the tests**

```bash
cd server && pytest tests/test_calendar_audience.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd server && git add modules/academics/calendar/audience.py tests/test_calendar_audience.py
git commit -m "feat(calendar): resolve a caller's calendar audience from identity"
```

---

## Task 3: Scope exam windows and school events

**Files:**
- Modify: `server/modules/academics/calendar/services.py:265-275` (`list_exam_windows`), `:439-449` (`list_school_events`)
- Test: `server/tests/test_calendar_audience.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_calendar_audience.py`:

```python
@pytest.fixture
def exams(db_session, tenant, year, two_classes):
    """Three windows: one per class, and one for the whole school."""
    from modules.academics.calendar.models import ExamWindow

    taught, other = two_classes
    rows = [
        ExamWindow(
            id=_new_id("ew-"), tenant_id=tenant.id, academic_year_id=year.id,
            name="Std 8 Unit Test", exam_type="unit_test", status="active",
            start_date=date(2026, 8, 3), end_date=date(2026, 8, 7),
            applicable_class_ids=[taught.id],
        ),
        ExamWindow(
            id=_new_id("ew-"), tenant_id=tenant.id, academic_year_id=year.id,
            name="Std 12 Pre-Board", exam_type="pre_board", status="active",
            start_date=date(2026, 9, 1), end_date=date(2026, 9, 10),
            applicable_class_ids=[other.id],
        ),
        ExamWindow(
            id=_new_id("ew-"), tenant_id=tenant.id, academic_year_id=year.id,
            name="Annual Exams", exam_type="final", status="active",
            start_date=date(2027, 2, 1), end_date=date(2027, 2, 20),
            applicable_class_ids=[],
        ),
    ]
    db_session.add_all(rows)
    db_session.flush()
    return rows


def _names(rows):
    return {row.name for row in rows}


def test_teacher_sees_own_class_exam_and_whole_school_exam_only(
    db_session, tenant, year, exams, teaching_user
):
    from modules.academics.calendar.audience import resolve_calendar_audience
    from modules.academics.calendar.services import list_exam_windows

    user, _ = teaching_user
    audience = resolve_calendar_audience(user)

    seen = _names(list_exam_windows(year.id, audience=audience))

    assert seen == {"Std 8 Unit Test", "Annual Exams"}
    assert "Std 12 Pre-Board" not in seen


def test_student_sees_only_their_own_class_exam(
    db_session, tenant, year, exams, studying_user
):
    from modules.academics.calendar.audience import resolve_calendar_audience
    from modules.academics.calendar.services import list_exam_windows

    user, _ = studying_user
    audience = resolve_calendar_audience(user)

    seen = _names(list_exam_windows(year.id, audience=audience))

    assert seen == {"Std 8 Unit Test", "Annual Exams"}


def test_admin_sees_every_exam_window(db_session, tenant, year, exams):
    from modules.academics.calendar.audience import UNRESTRICTED
    from modules.academics.calendar.services import list_exam_windows

    seen = _names(list_exam_windows(year.id, audience=UNRESTRICTED))

    assert len(seen) == 3


def test_student_does_not_see_a_staff_only_event(db_session, tenant, year, studying_user):
    from modules.academics.calendar.audience import resolve_calendar_audience
    from modules.academics.calendar.models import SchoolEvent
    from modules.academics.calendar.services import list_school_events

    db_session.add_all([
        SchoolEvent(
            id=_new_id("se-"), tenant_id=tenant.id, academic_year_id=year.id,
            name="Staff Training", event_type="training", status="active",
            event_date=date(2026, 7, 10), applies_to="staff",
        ),
        SchoolEvent(
            id=_new_id("se-"), tenant_id=tenant.id, academic_year_id=year.id,
            name="Sports Day", event_type="activity", status="active",
            event_date=date(2026, 12, 12), applies_to="entire_school",
        ),
    ])
    db_session.flush()

    user, _ = studying_user
    audience = resolve_calendar_audience(user)

    seen = _names(list_school_events(year.id, audience=audience))

    assert seen == {"Sports Day"}


def test_teacher_does_see_a_student_facing_event(db_session, tenant, year, teaching_user):
    """A sports day is a teacher's working day. Only exams are class-filtered
    for teachers."""
    from modules.academics.calendar.audience import resolve_calendar_audience
    from modules.academics.calendar.models import SchoolEvent
    from modules.academics.calendar.services import list_school_events

    db_session.add(
        SchoolEvent(
            id=_new_id("se-"), tenant_id=tenant.id, academic_year_id=year.id,
            name="Sports Day", event_type="activity", status="active",
            event_date=date(2026, 12, 12), applies_to="students",
        )
    )
    db_session.flush()

    user, _ = teaching_user
    audience = resolve_calendar_audience(user)

    assert _names(list_school_events(year.id, audience=audience)) == {"Sports Day"}
```

Add a `year` fixture to this file, copied from `tests/test_calendar_setup_graphql.py:58`:

```python
@pytest.fixture
def year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name="2026-2027",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    db_session.add(ay)
    db_session.flush()
    return ay
```

- [ ] **Step 2: Run and watch it fail**

```bash
cd server && pytest tests/test_calendar_audience.py -v -k "exam or event"
```

Expected: `TypeError: list_exam_windows() got an unexpected keyword argument 'audience'`.

- [ ] **Step 3: Implement**

In `server/modules/academics/calendar/services.py`, add the import near the top:

```python
from .audience import CalendarAudience, resolve_calendar_audience
```

Replace `list_exam_windows` (currently at line 265):

```python
def list_exam_windows(
    academic_year_id: str,
    active_only: bool = False,
    audience: Optional[CalendarAudience] = None,
) -> List[ExamWindow]:
    """Exam windows for a year, narrowed to what the caller may see.

    Filtering happens in Python rather than in the query because
    `applicable_class_ids` is JSONB holding a list, and "any of these ids" is
    a containment test the index cannot serve anyway. A year holds tens of
    windows, not thousands.
    """
    query = ExamWindow.query.filter(
        ExamWindow.tenant_id == g.tenant_id,
        ExamWindow.academic_year_id == academic_year_id,
    )
    if active_only:
        query = query.filter(ExamWindow.status == LIVE_STATUS)
    rows = query.order_by(ExamWindow.start_date).all()

    seen_by = audience if audience is not None else resolve_calendar_audience()
    if seen_by.unrestricted:
        return rows
    return [row for row in rows if seen_by.may_see_exam(row.applicable_class_ids)]
```

Replace `list_school_events` (currently at line 439):

```python
def list_school_events(
    academic_year_id: str,
    active_only: bool = False,
    audience: Optional[CalendarAudience] = None,
) -> List[SchoolEvent]:
    """School events for a year, narrowed to what the caller may see."""
    query = SchoolEvent.query.filter(
        SchoolEvent.tenant_id == g.tenant_id,
        SchoolEvent.academic_year_id == academic_year_id,
    )
    if active_only:
        query = query.filter(SchoolEvent.status == LIVE_STATUS)
    rows = query.order_by(SchoolEvent.event_date).all()

    seen_by = audience if audience is not None else resolve_calendar_audience()
    if seen_by.unrestricted:
        return rows
    return [row for row in rows if seen_by.may_see_audience(row.applies_to)]
```

**Check the callers before moving on.** These two functions are also called by the write path (overlap and duplicate-name validation) and by export/import:

```bash
cd server && grep -rn "list_exam_windows\|list_school_events" modules --include="*.py" | grep -v __pycache__
```

Every **validation** call site must pass `audience=UNRESTRICTED` — an overlap check that cannot see the window it collides with will let a duplicate through. Only the **read** paths (`_collect_day_sets`, the resolvers, export) take the caller's audience. Import `UNRESTRICTED` from `.audience` at each such site.

- [ ] **Step 4: Run the tests**

```bash
cd server && pytest tests/test_calendar_audience.py tests/test_academic_calendar.py -v
```

Expected: all of `test_calendar_audience.py` passes, and `test_academic_calendar.py` keeps its previous pass count — the overlap tests there are the ones that catch a missed `UNRESTRICTED`.

- [ ] **Step 5: Commit**

```bash
cd server && git add modules/academics/calendar/services.py tests/test_calendar_audience.py
git commit -m "feat(calendar): scope exam windows and events to the caller's audience"
```

---

## Task 4: Scope the day feed and summary

**Files:**
- Modify: `server/modules/academics/calendar/services.py:628-686` (`_collect_day_sets`), `:688` (`compute_summary`), `:736` (`get_days_feed`)
- Test: `server/tests/test_calendar_audience.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
def test_a_staff_only_holiday_is_a_working_day_for_a_student(
    db_session, tenant, year, studying_user, published_calendar
):
    """The summary answers the caller's question, not the school's.

    A closure that applies only to staff does not close school for students,
    so it must not be subtracted from their working days.
    """
    from modules.academics.calendar.audience import UNRESTRICTED, resolve_calendar_audience
    from modules.academics.calendar.holidays import Holiday
    from modules.academics.calendar.services import compute_summary

    db_session.add(
        Holiday(
            id=_new_id("h-"), tenant_id=tenant.id, academic_year_id=year.id,
            name="Staff Development Day", holiday_type="school",
            start_date=date(2026, 7, 6), end_date=date(2026, 7, 6),
            applies_to="staff",
        )
    )
    db_session.flush()

    user, _ = studying_user
    student_view = compute_summary(published_calendar, audience=resolve_calendar_audience(user))
    admin_view = compute_summary(published_calendar, audience=UNRESTRICTED)

    assert student_view["working_days"] == admin_view["working_days"] + 1


def test_the_day_feed_hides_another_class_exam_from_a_student(
    db_session, tenant, year, exams, studying_user, published_calendar
):
    from modules.academics.calendar.audience import resolve_calendar_audience
    from modules.academics.calendar.services import get_days_feed

    user, _ = studying_user
    feed = {
        day["date"]: day
        for day in get_days_feed(published_calendar, audience=resolve_calendar_audience(user))
    }

    assert feed["2026-08-03"]["has_exam"] is True     # their own Std 8 unit test
    assert feed["2026-09-01"]["has_exam"] is False    # the Std 12 pre-board
```

Add a `published_calendar` fixture. Read `tests/test_academic_calendar.py` for the exact constructor its own calendar fixture uses — `AcademicCalendar` needs `academic_cycle_id` bound to the year by a composite FK, so copy that fixture rather than inventing one:

```bash
cd server && grep -n "AcademicCalendar(" tests/test_academic_calendar.py
```

- [ ] **Step 2: Run and watch it fail**

```bash
cd server && pytest tests/test_calendar_audience.py -v -k "working_day or day_feed"
```

Expected: `TypeError: compute_summary() got an unexpected keyword argument 'audience'`.

- [ ] **Step 3: Implement**

Change the three signatures in `server/modules/academics/calendar/services.py`:

```python
def _collect_day_sets(
    year: AcademicYear,
    cal: AcademicCalendar,
    audience: Optional[CalendarAudience] = None,
) -> Tuple[Set[date], Dict[date, List[Dict]], Dict[date, List[Dict]], Set[date], Set[date]]:
```

Immediately after the docstring in `_collect_day_sets`, resolve once:

```python
    seen_by = audience if audience is not None else resolve_calendar_audience()
```

In the holiday loop, skip closures addressed to somebody else. The `weekly_off` branch stays **above** this check — a weekly closure is the school's timetable, not an announcement, and every audience keeps it:

```python
    for h in holidays:
        end = h.end_date or h.start_date
        target = vacation_map if h.holiday_type == "vacation" else holiday_map
        # Materialized 2nd/4th-Saturday rows are weekly offs, not public holidays.
        if h.holiday_type == "weekly_off":
            for d in _iter_dates(h.start_date, end):
                if span_start <= d <= span_end:
                    weekly_off.add(d)
            continue
        # A closure addressed to staff does not close school for a student.
        if not seen_by.may_see_audience(h.applies_to):
            continue
        info = {"id": h.id, "name": h.name, "holiday_type": h.holiday_type}
        for d in _iter_dates(h.start_date, end):
            if span_start <= d <= span_end:
                target.setdefault(d, []).append(info)
```

Pass the audience down to the two list calls in the same function:

```python
    exam_dates: Set[date] = set()
    for w in list_exam_windows(year.id, active_only=True, audience=seen_by):
        for d in _iter_dates(w.start_date, w.end_date):
            if span_start <= d <= span_end:
                exam_dates.add(d)

    event_dates: Set[date] = {
        e.event_date
        for e in list_school_events(year.id, active_only=True, audience=seen_by)
        if span_start <= e.event_date <= span_end
    }
```

Thread it through the two public readers:

```python
def compute_summary(
    cal: AcademicCalendar, audience: Optional[CalendarAudience] = None
) -> Dict[str, Any]:
    """Review-step / dashboard stats, from the caller's view of the year.

    Working days = all days minus weekly offs, public holidays and vacation
    days the caller can see (overlaps counted once).
    """
    year = _get_year(cal.academic_year_id)
    weekly_off, holiday_map, vacation_map, exam_dates, _ = _collect_day_sets(
        year, cal, audience
    )
```

```python
def get_days_feed(
    cal: AcademicCalendar, audience: Optional[CalendarAudience] = None
) -> List[Dict[str, Any]]:
```

and inside it:

```python
    weekly_off, holiday_map, vacation_map, exam_dates, event_dates = _collect_day_sets(
        year, cal, audience
    )
```

**One call site must NOT take the caller's audience:** `publish_calendar` snapshots `published_summary`, which is the school's calendar, not one reader's. Find it and pin it:

```bash
cd server && grep -n "compute_summary\|_collect_day_sets\|get_days_feed" modules --include="*.py" -r | grep -v __pycache__
```

Pass `audience=UNRESTRICTED` in `publish_calendar`, `_validate_*_for_publish`, and the export services.

- [ ] **Step 4: Run the tests**

```bash
cd server && pytest tests/test_calendar_audience.py tests/test_academic_calendar.py tests/test_calendar_setup_graphql.py -v
```

Expected: all pass, with `test_academic_calendar.py` at its prior count.

- [ ] **Step 5: Commit**

```bash
cd server && git add modules/academics/calendar/services.py tests/test_calendar_audience.py
git commit -m "feat(calendar): scope the day feed and summary to the caller's audience"
```

---

## Task 5: Give Students and Parents `academic_calendar.read`

**Files:**
- Modify: `server/modules/rbac/catalog.py:348-390`
- Test: `server/tests/test_calendar_audience.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
def test_student_and_parent_profiles_can_read_the_calendar():
    """Without this they hold only `holiday.read` and the calendar 403s.

    Asserted against the catalog rather than a seeded database so the check
    fails at the source of truth, where the fix belongs.
    """
    from modules.rbac.catalog import ROLE_PROFILES

    assert "academic_calendar.read" in ROLE_PROFILES["Student"]["permissions"]
    assert "academic_calendar.read" in ROLE_PROFILES["Parent"]["permissions"]
```

Confirm the dict's real name first — the plan assumes `ROLE_PROFILES`:

```bash
cd server && grep -n "^[A-Z_]* = {" modules/rbac/catalog.py
```

- [ ] **Step 2: Run and watch it fail**

```bash
cd server && pytest tests/test_calendar_audience.py -v -k "profiles_can_read"
```

Expected: `AssertionError`.

- [ ] **Step 3: Implement**

In `server/modules/rbac/catalog.py`, add `'academic_calendar.read',` to the `permissions` list of both the `'Student'` and `'Parent'` profiles, next to the existing `'holiday.read'`.

- [ ] **Step 4: Run the test**

```bash
cd server && pytest tests/test_calendar_audience.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd server && git add modules/rbac/catalog.py tests/test_calendar_audience.py
git commit -m "feat(rbac): let students and parents read the academic calendar"
```

---

## Task 6: `currentAcademicCalendar` GraphQL field

**Files:**
- Modify: `server/modules/academics/calendar/graphql/types.py`, `server/modules/academics/calendar/resolvers.py:196-270`
- Test: `server/tests/test_calendar_audience.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
CURRENT = """
query {
  currentAcademicCalendar {
    id status academicYearName
    summary { totalDays workingDays holidayCount }
    days { date dayType hasExam hasEvent semesterStart semesterEnd
           holidays { id name holidayType } }
    events { id name eventType eventDate appliesTo }
    examWindows { id name examType startDate endDate }
  }
}
"""


def test_current_calendar_answers_a_student_with_their_own_view(
    client, db_session, tenant, year, exams, published_calendar, studying_user
):
    from modules.auth.services import generate_access_token
    from tests.test_calendar_setup_graphql import _ask

    user, _ = studying_user
    body = _ask(client, tenant, generate_access_token(user), CURRENT)

    calendar = body["data"]["currentAcademicCalendar"]
    assert calendar is not None
    names = {window["name"] for window in calendar["examWindows"]}
    assert names == {"Std 8 Unit Test", "Annual Exams"}


def test_current_calendar_is_null_when_the_school_has_not_published_one(
    client, db_session, tenant, year, studying_user
):
    from modules.auth.services import generate_access_token
    from tests.test_calendar_setup_graphql import _ask

    user, _ = studying_user
    body = _ask(client, tenant, generate_access_token(user), CURRENT)

    assert body["data"]["currentAcademicCalendar"] is None
```

Add the `client` fixture from `tests/test_calendar_setup_graphql.py:52`:

```python
@pytest.fixture
def client(flask_app):
    return flask_app.test_client()
```

Note the student's token must carry the `academic_calendar.read` permission Task 5 added — the `studying_user` fixture grants a role, so add that permission to the role it builds.

- [ ] **Step 2: Run and watch it fail**

```bash
cd server && pytest tests/test_calendar_audience.py -v -k current_calendar
```

Expected: GraphQL error `Cannot query field 'currentAcademicCalendar'`.

- [ ] **Step 3: Implement the type**

Append to `server/modules/academics/calendar/graphql/types.py`:

```python
@strawberry.type(
    description=(
        "The calendar a school is running right now, with everything a "
        "reader needs to draw it. One answer, because a phone asking four "
        "questions to fill one screen is four chances to be on a train."
    )
)
class CurrentCalendar:
    id: strawberry.ID
    status: str
    academic_year_id: strawberry.ID
    academic_year_name: Optional[str]
    summary: CalendarSummary
    days: List[CalendarDay]
    events: List[SchoolEvent]
    exam_windows: List[ExamWindow]
```

- [ ] **Step 4: Implement the resolver**

Add to `CalendarQuery` in `server/modules/academics/calendar/resolvers.py`:

```python
    @strawberry.field(
        permission_classes=CALENDAR_READS,
        description=(
            "The published calendar for the school's active year, scoped to "
            "what the caller may see, or null if there is not one. What a "
            "phone opens the calendar screen with."
        ),
    )
    def current_academic_calendar(
        self, info: strawberry.Info
    ) -> Optional[CurrentCalendar]:
        from modules.academics.academic_year.models import AcademicYear

        from . import services
        from .audience import resolve_calendar_audience

        year = AcademicYear.query.filter_by(
            tenant_id=info.context.tenant_id, is_active=True
        ).first()
        if year is None:
            return None

        calendar = services.get_calendar_for_year(year.id)
        # A draft is the school still deciding. Showing it to a parent would
        # announce dates that are going to move.
        if calendar is None or calendar.status != "published":
            return None

        seen_by = resolve_calendar_audience()
        return CurrentCalendar(
            id=strawberry.ID(calendar.id),
            status=calendar.status,
            academic_year_id=strawberry.ID(year.id),
            academic_year_name=year.name,
            summary=summary_to_graphql(_computed(services, calendar, seen_by)),
            days=[
                day_to_graphql(day)
                for day in services.get_days_feed(calendar, audience=seen_by)
            ],
            events=[
                event_to_graphql(row.to_dict())
                for row in services.list_school_events(year.id, active_only=True, audience=seen_by)
            ],
            exam_windows=[
                exam_window_to_graphql(row.to_dict())
                for row in services.list_exam_windows(year.id, active_only=True, audience=seen_by)
            ],
        )
```

Widen `_computed` in the same file to take the audience:

```python
def _computed(services, calendar, audience=None) -> Dict[str, Any]:
    """The summary, or the reason it cannot be computed."""
    from .services import CalendarValidationError

    try:
        return services.compute_summary(calendar, audience=audience)
    except CalendarValidationError as invalid:
        raise ValidationError(str(getattr(invalid, "errors", invalid)))
```

Add `CurrentCalendar` to the `from .graphql.types import (...)` block at the top of `resolvers.py`.

- [ ] **Step 5: Run the tests**

```bash
cd server && pytest tests/test_calendar_audience.py tests/test_calendar_setup_graphql.py -v
```

Expected: all pass.

- [ ] **Step 6: Check the schema actually changed**

```bash
cd server && python -c "
from graphql_api.schema import schema
print('currentAcademicCalendar' in schema.as_str())
"
```

Expected: `True`. If `graphql_api.schema` is not the module path, find it with `grep -rn 'strawberry.Schema(' graphql_api/`.

- [ ] **Step 7: Commit**

```bash
cd server && git add modules/academics/calendar/graphql/types.py modules/academics/calendar/resolvers.py tests/test_calendar_audience.py
git commit -m "feat(calendar): add currentAcademicCalendar for the mobile client"
```

---

## Task 7: Full server suite

- [ ] **Step 1: Run everything**

```bash
cd server && pytest -q 2>&1 | tail -20
```

Expected: the same pass count as the pre-task baseline plus the new tests. The baseline measured on `develop` on 2026-09-14 was **3640 passed** — if the count is lower, something regressed; do not proceed.

If anything fails, **first** stash and re-run to check it was not already failing:

```bash
cd server && git stash && pytest -q tests/<failing_file> 2>&1 | tail -5 && git stash pop
```

---

## Task 8: Lift `gql()` into a shared client helper

**Files:**
- Create: `client/common/services/graphql.ts`
- Modify: `client/modules/academics/services/academicStructureService.ts:49-65`

- [ ] **Step 1: Create the shared helper**

`client/common/services/graphql.ts`:

```ts
import { apiPost } from '@/common/services/api';
import { ApiException } from '@/common/services/api';

type GraphQLError = { message: string };
type GraphQLReply<T> = { data?: T | null; errors?: GraphQLError[] };

/**
 * POST one GraphQL operation and hand back `data`, or throw.
 *
 * GraphQL answers 200 with an `errors` array where REST would answer 4xx, so
 * without this every caller would have to remember that a successful request
 * can still be a failure.
 */
export async function gql<T>(
  query: string,
  variables?: Record<string, unknown>
): Promise<T> {
  const reply = await apiPost<GraphQLReply<T>>('/api/graphql', {
    query,
    variables: variables ?? {},
  });
  const failure = reply.errors?.[0];
  if (failure) {
    throw new ApiException(failure.message || 'Request failed');
  }
  if (reply.data === undefined || reply.data === null) {
    throw new ApiException('The server returned no data.');
  }
  return reply.data;
}
```

Check where `ApiException` is actually exported from before writing the import:

```bash
cd client && grep -n "ApiException" modules/academics/services/academicStructureService.ts | head -3
```

- [ ] **Step 2: Repoint the existing caller**

In `client/modules/academics/services/academicStructureService.ts`, delete the local `GraphQLError`, `GraphQLReply` and `gql` definitions and import instead:

```ts
import { gql } from '@/common/services/graphql';
```

- [ ] **Step 3: Verify**

```bash
cd client && npx tsc --noEmit
```

Expected: no new errors. Record the pre-existing error count first by running this on a clean tree if the output is not empty.

- [ ] **Step 4: Commit**

```bash
cd client && git add common/services/graphql.ts modules/academics/services/academicStructureService.ts
git commit -m "refactor(client): share the graphql helper across modules"
```

---

## Task 9: Calendar types and service

**Files:**
- Create: `client/modules/academic-calendar/types.ts`, `client/modules/academic-calendar/services/academicCalendarService.ts`

- [ ] **Step 1: Types**

`client/modules/academic-calendar/types.ts`:

```ts
/** What the school is doing on one day. Mirrors the server's days feed. */
export type CalendarDayType = 'working' | 'weekly_holiday' | 'public_holiday' | 'vacation';

export interface CalendarDayHoliday {
  id: string;
  name: string;
  holidayType: string;
}

export interface CalendarDay {
  date: string;              // ISO yyyy-mm-dd
  dayType: CalendarDayType;
  hasExam: boolean;
  hasEvent: boolean;
  semesterStart: string | null;
  semesterEnd: string | null;
  holidays: CalendarDayHoliday[];
}

export interface CalendarSummary {
  totalDays: number;
  workingDays: number;
  holidayCount: number;
}

export interface CalendarEvent {
  id: string;
  name: string;
  eventType: string;
  eventDate: string;
  appliesTo: string;
  description: string | null;
}

export interface CalendarExamWindow {
  id: string;
  name: string;
  examType: string;
  startDate: string;
  endDate: string;
  description: string | null;
}

export interface CurrentCalendar {
  id: string;
  status: string;
  academicYearId: string;
  academicYearName: string | null;
  summary: CalendarSummary;
  days: CalendarDay[];
  events: CalendarEvent[];
  examWindows: CalendarExamWindow[];
}
```

**Confirm each field name against the server's Strawberry types before committing** — Strawberry camel-cases Python snake_case, so `day_type` becomes `dayType`, but check `holiday_type` on the nested holiday, which may already be camel in `graphql/types.py`:

```bash
cd server && grep -n "class CalendarDay\|class CalendarSummary\|class SchoolEvent\|class ExamWindow" -A 15 modules/academics/calendar/graphql/types.py
```

- [ ] **Step 2: Service**

`client/modules/academic-calendar/services/academicCalendarService.ts`:

```ts
import { gql } from '@/common/services/graphql';
import type { CurrentCalendar } from '../types';

const CURRENT_CALENDAR = `
  query CurrentCalendar {
    currentAcademicCalendar {
      id
      status
      academicYearId
      academicYearName
      summary { totalDays workingDays holidayCount }
      days {
        date dayType hasExam hasEvent semesterStart semesterEnd
        holidays { id name holidayType }
      }
      events { id name eventType eventDate appliesTo description }
      examWindows { id name examType startDate endDate description }
    }
  }
`;

export const academicCalendarService = {
  /**
   * The published calendar for the school's active year, already narrowed to
   * what this caller may see. Null when the school has not published one.
   */
  getCurrent: async (): Promise<CurrentCalendar | null> => {
    const reply = await gql<{ currentAcademicCalendar: CurrentCalendar | null }>(
      CURRENT_CALENDAR
    );
    return reply.currentAcademicCalendar ?? null;
  },
};
```

- [ ] **Step 3: Verify and commit**

```bash
cd client && npx tsc --noEmit
git add modules/academic-calendar/types.ts modules/academic-calendar/services/academicCalendarService.ts
git commit -m "feat(client): add the academic calendar graphql service"
```

---

## Task 10: `useCurrentCalendar` hook

**Files:**
- Create: `client/modules/academic-calendar/hooks/useCurrentCalendar.ts`

- [ ] **Step 1: Implement**

```ts
import { useQuery } from '@tanstack/react-query';
import { academicCalendarService } from '../services/academicCalendarService';

export const academicCalendarKeys = {
  all: ['academic-calendar'] as const,
  current: () => [...academicCalendarKeys.all, 'current'] as const,
};

/**
 * The school's published calendar, as this caller may see it.
 *
 * Not parameterised by academic year: the server answers for the active one,
 * and a read-only phone screen has no year picker to disagree with it.
 */
export function useCurrentCalendar() {
  return useQuery({
    queryKey: academicCalendarKeys.current(),
    queryFn: () => academicCalendarService.getCurrent(),
    staleTime: 5 * 60 * 1000,
  });
}
```

**Check the client's tenant-scoping convention before committing.** `.claude/rules/query-conventions.md` requires `tenantId` as the last key segment for tenant-scoped data. Find how the Expo client does it:

```bash
cd client && grep -rn "queryKey" modules/academics/hooks/useAcademicYears.ts
```

If sibling hooks append a tenant id, do the same here and gate `enabled` on it. If the Expo client relies on `queryClient.clear()` at login instead, match that and say so in a comment.

- [ ] **Step 2: Verify and commit**

```bash
cd client && npx tsc --noEmit
git add modules/academic-calendar/hooks/useCurrentCalendar.ts
git commit -m "feat(client): add useCurrentCalendar"
```

---

## Task 11: `CalendarMonthGrid`

**Files:**
- Create: `client/modules/academic-calendar/components/CalendarMonthGrid.tsx`
- Reference (do not modify): `client/common/components/datepicker/MonthGrid.tsx`

This is a sibling of the datepicker grid, not a change to it: that one selects a date and carries no markers, this one displays a month and marks every day. Copy its `buildWeeks`, `toIso` and `CELL = 44` (the minimum touch target) rather than reinventing them.

- [ ] **Step 1: Implement**

```tsx
import React, { useMemo } from 'react';
import { Pressable, View } from 'react-native';
import { useTheme } from '@/common/theme';
import { Text } from '@/common/components/Text';
import { AppIcon } from '@/common/components/AppIcon';
import type { CalendarDay } from '../types';

const CELL = 44; // TouchTarget.min

type Cell = { iso: string; day: number } | null;

export type CalendarMonthGridProps = {
  /** Any date inside the month being shown. */
  month: Date;
  onMonthChange: (next: Date) => void;
  /** The whole year's feed, keyed by ISO date for O(1) lookup per cell. */
  daysByIso: Map<string, CalendarDay>;
  selectedIso: string | null;
  onSelectDay: (iso: string) => void;
  monthLabel: string;
  weekdayLabels: string[];
};

function toIso(year: number, month: number, day: number): string {
  const m = `${month + 1}`.padStart(2, '0');
  const d = `${day}`.padStart(2, '0');
  return `${year}-${m}-${d}`;
}

function buildWeeks(month: Date): Cell[][] {
  const year = month.getFullYear();
  const m = month.getMonth();
  const leading = new Date(year, m, 1).getDay();
  const daysInMonth = new Date(year, m + 1, 0).getDate();
  const cells: Cell[] = Array.from({ length: leading }, () => null);
  for (let day = 1; day <= daysInMonth; day++) {
    cells.push({ iso: toIso(year, m, day), day });
  }
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks: Cell[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

export function CalendarMonthGrid({
  month,
  onMonthChange,
  daysByIso,
  selectedIso,
  onSelectDay,
  monthLabel,
  weekdayLabels,
}: CalendarMonthGridProps) {
  const { palette, spacing, radius } = useTheme();
  const weeks = useMemo(() => buildWeeks(month), [month]);

  // A day carries up to three marks — its type, an exam, an event — so the
  // dots are a row, not one colour fighting to mean three things.
  const marksFor = (entry: CalendarDay | undefined): string[] => {
    if (!entry) return [];
    const marks: string[] = [];
    if (entry.dayType === 'vacation') marks.push(palette.info);
    else if (entry.dayType === 'public_holiday') marks.push(palette.danger);
    else if (entry.dayType === 'weekly_holiday') marks.push(palette.textMuted);
    if (entry.hasExam) marks.push(palette.warning);
    if (entry.hasEvent) marks.push(palette.success);
    return marks;
  };

  const shiftMonth = (by: number) =>
    onMonthChange(new Date(month.getFullYear(), month.getMonth() + by, 1));

  return (
    <View>
      <View
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingHorizontal: spacing.sm,
          paddingVertical: spacing.sm,
        }}
      >
        <Pressable
          onPress={() => shiftMonth(-1)}
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel="Previous month"
          style={{ width: CELL, height: CELL, alignItems: 'center', justifyContent: 'center' }}
        >
          <AppIcon name="chevron-back" size={20} color={palette.text} />
        </Pressable>
        <Text variant="titleSmall">{monthLabel}</Text>
        <Pressable
          onPress={() => shiftMonth(1)}
          hitSlop={8}
          accessibilityRole="button"
          accessibilityLabel="Next month"
          style={{ width: CELL, height: CELL, alignItems: 'center', justifyContent: 'center' }}
        >
          <AppIcon name="chevron-forward" size={20} color={palette.text} />
        </Pressable>
      </View>

      <View style={{ flexDirection: 'row' }}>
        {weekdayLabels.map((label, index) => (
          <View key={`${label}-${index}`} style={{ flex: 1, alignItems: 'center' }}>
            <Text variant="labelSmall" color={palette.textMuted}>
              {label}
            </Text>
          </View>
        ))}
      </View>

      {weeks.map((week, weekIndex) => (
        <View key={weekIndex} style={{ flexDirection: 'row' }}>
          {week.map((cell, cellIndex) => {
            if (!cell) return <View key={cellIndex} style={{ flex: 1, height: CELL }} />;
            const entry = daysByIso.get(cell.iso);
            const marks = marksFor(entry);
            const isSelected = cell.iso === selectedIso;
            return (
              <Pressable
                key={cell.iso}
                onPress={() => onSelectDay(cell.iso)}
                accessibilityRole="button"
                accessibilityState={{ selected: isSelected }}
                style={{
                  flex: 1,
                  height: CELL,
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRadius: radius.sm,
                  backgroundColor: isSelected ? palette.primarySoft : 'transparent',
                }}
              >
                <Text
                  variant="bodySmall"
                  color={isSelected ? palette.primary : palette.text}
                >
                  {cell.day}
                </Text>
                <View style={{ flexDirection: 'row', gap: 2, height: 6, marginTop: 2 }}>
                  {marks.map((color, index) => (
                    <View
                      key={index}
                      style={{ width: 4, height: 4, borderRadius: 2, backgroundColor: color }}
                    />
                  ))}
                </View>
              </Pressable>
            );
          })}
        </View>
      ))}
    </View>
  );
}
```

**Check the real token names before running this** — `palette.primarySoft`, `palette.danger`, `palette.warning`, `palette.success`, `palette.info`, `palette.textMuted` and the `Text` `variant` values are assumed:

```bash
cd client && grep -n "primarySoft\|danger\|warning\|success\|info\|textMuted" common/theme/*.ts | head -20
grep -n "variant" common/components/Text.tsx | head -10
```

Substitute the names that actually exist. Do not add new tokens.

- [ ] **Step 2: Verify and commit**

```bash
cd client && npx tsc --noEmit
git add modules/academic-calendar/components/CalendarMonthGrid.tsx
git commit -m "feat(client): add the academic calendar month grid"
```

---

## Task 12: `CalendarLegend` and `CalendarDayCard`

**Files:**
- Create: `client/modules/academic-calendar/components/CalendarLegend.tsx`, `client/modules/academic-calendar/components/CalendarDayCard.tsx`

- [ ] **Step 1: Legend**

```tsx
import React from 'react';
import { View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { useTheme } from '@/common/theme';
import { Text } from '@/common/components/Text';

/** The key to the grid's dots. Colour alone is not a label. */
export function CalendarLegend() {
  const { t } = useTranslation('academicCalendar');
  const { palette, spacing } = useTheme();

  const items = [
    { color: palette.danger, label: t('legend.holiday') },
    { color: palette.info, label: t('legend.vacation') },
    { color: palette.textMuted, label: t('legend.weeklyOff') },
    { color: palette.warning, label: t('legend.exam') },
    { color: palette.success, label: t('legend.event') },
  ];

  return (
    <View
      style={{
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: spacing.sm,
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm,
      }}
    >
      {items.map((item) => (
        <View key={item.label} style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
          <View
            style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: item.color }}
          />
          <Text variant="labelSmall" color={palette.textMuted}>
            {item.label}
          </Text>
        </View>
      ))}
    </View>
  );
}
```

- [ ] **Step 2: Day card**

```tsx
import React from 'react';
import { View } from 'react-native';
import { useTheme } from '@/common/theme';
import { Text } from '@/common/components/Text';
import { AppIcon } from '@/common/components/AppIcon';

export type CalendarEntryKind = 'holiday' | 'vacation' | 'weeklyOff' | 'exam' | 'event' | 'term';

const ICONS: Record<CalendarEntryKind, string> = {
  holiday: 'flag-outline',
  vacation: 'sunny-outline',
  weeklyOff: 'moon-outline',
  exam: 'document-text-outline',
  event: 'sparkles-outline',
  term: 'bookmark-outline',
};

export type CalendarDayCardProps = {
  kind: CalendarEntryKind;
  title: string;
  subtitle?: string | null;
  accent: string;
};

/** One thing happening on the selected day. Read-only: no press, no actions. */
export function CalendarDayCard({ kind, title, subtitle, accent }: CalendarDayCardProps) {
  const { palette, spacing, radius, elevation } = useTheme();

  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.sm,
        padding: spacing.md,
        marginHorizontal: spacing.md,
        marginBottom: spacing.sm,
        borderRadius: radius.md,
        backgroundColor: palette.surface,
        borderLeftWidth: 3,
        borderLeftColor: accent,
        ...elevation.level1,
      }}
    >
      <AppIcon name={ICONS[kind] as never} size={20} color={accent} />
      <View style={{ flex: 1 }}>
        <Text variant="bodyMedium">{title}</Text>
        {subtitle ? (
          <Text variant="bodySmall" color={palette.textMuted}>
            {subtitle}
          </Text>
        ) : null}
      </View>
    </View>
  );
}
```

Check `elevation.level1` and `palette.surface` against `common/theme/` and against how `HolidayListItem.tsx` builds its card — copy that card's exact shape rather than this approximation if they differ.

- [ ] **Step 3: Verify and commit**

```bash
cd client && npx tsc --noEmit
git add modules/academic-calendar/components/
git commit -m "feat(client): add the calendar legend and day card"
```

---

## Task 13: The screen and its route

**Files:**
- Create: `client/modules/academic-calendar/screens/AcademicCalendarScreen.tsx`, `client/app/(protected)/academic-calendar.tsx`

- [ ] **Step 1: The screen**

```tsx
import React, { useMemo, useState } from 'react';
import { RefreshControl, ScrollView, View } from 'react-native';
import { useTranslation } from 'react-i18next';
import { calendarLocaleForLanguage } from '@/i18n';
import { useTheme } from '@/common/theme';
import { Text } from '@/common/components/Text';
import { PageHeader } from '@/common/components/PageHeader';
import { EmptyState } from '@/common/components/EmptyState';
import { Skeleton } from '@/common/components/Skeleton';
import { schoolTodayIso } from '@/common/utils/datetime';
import { useCurrentCalendar } from '../hooks/useCurrentCalendar';
import { CalendarMonthGrid } from '../components/CalendarMonthGrid';
import { CalendarLegend } from '../components/CalendarLegend';
import { CalendarDayCard, type CalendarEntryKind } from '../components/CalendarDayCard';
import type { CalendarDay } from '../types';

type Entry = { kind: CalendarEntryKind; title: string; subtitle?: string | null };

export default function AcademicCalendarScreen() {
  const { t, i18n } = useTranslation('academicCalendar');
  const { palette, spacing } = useTheme();
  const locale = calendarLocaleForLanguage(i18n.language ?? 'en');
  const { data: calendar, isLoading, refetch, isRefetching } = useCurrentCalendar();

  const today = schoolTodayIso();
  const [selectedIso, setSelectedIso] = useState<string>(today);
  const [month, setMonth] = useState<Date>(() => {
    const [y, m] = today.split('-').map(Number);
    return new Date(y, m - 1, 1);
  });

  const daysByIso = useMemo(() => {
    const map = new Map<string, CalendarDay>();
    for (const day of calendar?.days ?? []) map.set(day.date, day);
    return map;
  }, [calendar]);

  /** Everything happening on the selected day, in the order a reader cares. */
  const entries = useMemo<Entry[]>(() => {
    if (!calendar) return [];
    const day = daysByIso.get(selectedIso);
    const out: Entry[] = [];
    for (const holiday of day?.holidays ?? []) {
      out.push({
        kind: holiday.holidayType === 'vacation' ? 'vacation' : 'holiday',
        title: holiday.name,
        subtitle: t(`holidayTypes.${holiday.holidayType}`, { defaultValue: '' }) || null,
      });
    }
    if (day?.dayType === 'weekly_holiday' && (day?.holidays ?? []).length === 0) {
      out.push({ kind: 'weeklyOff', title: t('weeklyOff') });
    }
    for (const window of calendar.examWindows) {
      if (selectedIso >= window.startDate && selectedIso <= window.endDate) {
        out.push({ kind: 'exam', title: window.name, subtitle: window.description });
      }
    }
    for (const event of calendar.events) {
      if (event.eventDate === selectedIso) {
        out.push({ kind: 'event', title: event.name, subtitle: event.description });
      }
    }
    if (day?.semesterStart) {
      out.push({ kind: 'term', title: t('termStarts', { name: day.semesterStart }) });
    }
    if (day?.semesterEnd) {
      out.push({ kind: 'term', title: t('termEnds', { name: day.semesterEnd }) });
    }
    return out;
  }, [calendar, daysByIso, selectedIso, t]);

  const accentFor: Record<CalendarEntryKind, string> = {
    holiday: palette.danger,
    vacation: palette.info,
    weeklyOff: palette.textMuted,
    exam: palette.warning,
    event: palette.success,
    term: palette.primary,
  };

  if (isLoading) {
    return (
      <View style={{ flex: 1, backgroundColor: palette.background }}>
        <PageHeader title={t('title')} />
        <Skeleton height={320} style={{ margin: spacing.md }} />
      </View>
    );
  }

  if (!calendar) {
    return (
      <View style={{ flex: 1, backgroundColor: palette.background }}>
        <PageHeader title={t('title')} />
        <EmptyState
          icon="calendar-outline"
          title={t('empty.title')}
          description={t('empty.description')}
        />
      </View>
    );
  }

  const monthLabel = new Intl.DateTimeFormat(locale, {
    month: 'long',
    year: 'numeric',
  }).format(month);
  const weekdayFormat = new Intl.DateTimeFormat(locale, { weekday: 'narrow' });
  const weekdayLabels = Array.from({ length: 7 }, (_, index) =>
    weekdayFormat.format(new Date(2026, 5, 7 + index))
  );
  const selectedLabel = new Intl.DateTimeFormat(locale, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  }).format(new Date(`${selectedIso}T00:00:00`));

  return (
    <View style={{ flex: 1, backgroundColor: palette.background }}>
      <PageHeader title={t('title')} subtitle={calendar.academicYearName ?? undefined} />
      <ScrollView
        refreshControl={<RefreshControl refreshing={isRefetching} onRefresh={refetch} />}
      >
        <View
          style={{
            flexDirection: 'row',
            justifyContent: 'space-around',
            paddingVertical: spacing.md,
          }}
        >
          <View style={{ alignItems: 'center' }}>
            <Text variant="titleMedium">{calendar.summary.workingDays}</Text>
            <Text variant="labelSmall" color={palette.textMuted}>
              {t('stats.workingDays')}
            </Text>
          </View>
          <View style={{ alignItems: 'center' }}>
            <Text variant="titleMedium">{calendar.summary.holidayCount}</Text>
            <Text variant="labelSmall" color={palette.textMuted}>
              {t('stats.holidays')}
            </Text>
          </View>
          <View style={{ alignItems: 'center' }}>
            <Text variant="titleMedium">{calendar.summary.totalDays}</Text>
            <Text variant="labelSmall" color={palette.textMuted}>
              {t('stats.totalDays')}
            </Text>
          </View>
        </View>

        <CalendarMonthGrid
          month={month}
          onMonthChange={setMonth}
          daysByIso={daysByIso}
          selectedIso={selectedIso}
          onSelectDay={setSelectedIso}
          monthLabel={monthLabel}
          weekdayLabels={weekdayLabels}
        />

        <CalendarLegend />

        <Text variant="titleSmall" style={{ margin: spacing.md }}>
          {selectedLabel}
        </Text>

        {entries.length === 0 ? (
          <Text
            variant="bodySmall"
            color={palette.textMuted}
            style={{ marginHorizontal: spacing.md, marginBottom: spacing.xl }}
          >
            {t('noEntries')}
          </Text>
        ) : (
          entries.map((entry, index) => (
            <CalendarDayCard
              key={`${entry.kind}-${index}`}
              kind={entry.kind}
              title={entry.title}
              subtitle={entry.subtitle}
              accent={accentFor[entry.kind]}
            />
          ))
        )}
        <View style={{ height: spacing.xl }} />
      </ScrollView>
    </View>
  );
}
```

Check `PageHeader`'s real props (`subtitle` is assumed) and `EmptyState`'s (`icon`/`title`/`description`) against `HolidaysScreen.tsx:280-300`, which already uses both.

- [ ] **Step 2: The route**

`client/app/(protected)/academic-calendar.tsx` — copy the feature guard from `app/(protected)/holidays.tsx` verbatim, swapping the screen:

```tsx
import { useEffect } from 'react';
import { useRouter } from 'expo-router';
import { useAuth } from '@/modules/auth/hooks/useAuth';
import AcademicCalendarScreen from '@/modules/academic-calendar/screens/AcademicCalendarScreen';

export default function Page() {
  const router = useRouter();
  const { isFeatureEnabled } = useAuth();

  // The API gates the calendar behind the module a school may not have
  // bought. Without this guard the screen renders an empty state built from
  // 403s instead of saying the module is off.
  useEffect(() => {
    if (!isFeatureEnabled('academic_calendar')) {
      router.replace('/(protected)/home');
    }
  }, [isFeatureEnabled, router]);

  if (!isFeatureEnabled('academic_calendar')) {
    return null;
  }

  return <AcademicCalendarScreen />;
}
```

- [ ] **Step 3: Verify and commit**

```bash
cd client && npx tsc --noEmit && npm run lint -- --no-cache
```

`expo lint` only covers `/src`, `/app`, `/components` unless the scope fix from 2026-09-08 is in place — confirm `modules/` is linted, and pass `--no-cache` so a stale cache does not report a clean run over files it never read.

```bash
cd client && git add modules/academic-calendar/screens/ "app/(protected)/academic-calendar.tsx"
git commit -m "feat(client): add the read-only academic calendar screen"
```

---

## Task 14: Copy

**Files:**
- Create: `client/i18n/resources/{en,gu,hi}/academicCalendar.json`
- Modify: `client/i18n/config.ts`

- [ ] **Step 1: English copy**

`client/i18n/resources/en/academicCalendar.json`:

```json
{
  "title": "Academic Calendar",
  "weeklyOff": "Weekly off",
  "noEntries": "Nothing scheduled on this day.",
  "termStarts": "{{name}} begins",
  "termEnds": "{{name}} ends",
  "stats": {
    "workingDays": "Working days",
    "holidays": "Holidays",
    "totalDays": "Total days"
  },
  "legend": {
    "holiday": "Holiday",
    "vacation": "Vacation",
    "weeklyOff": "Weekly off",
    "exam": "Exams",
    "event": "Event"
  },
  "holidayTypes": {
    "public": "Public holiday",
    "national": "National holiday",
    "school": "School holiday",
    "vacation": "Vacation",
    "weekly_off": "Weekly off"
  },
  "empty": {
    "title": "No calendar published yet",
    "description": "Your school has not published its academic calendar for this year."
  }
}
```

- [ ] **Step 2: Gujarati and Hindi**

Terms reused from the existing `gu/holidays.json` and `hi/holidays.json` so the
app keeps one vocabulary: રજા / छुट्टी for a holiday, સાપ્તાહિક રજા /
साप्ताहिक अवकाश for a weekly off, સાર્વજનિક / सार्वजनिक for public, શાળા /
स्कूल for school.

`client/i18n/resources/gu/academicCalendar.json`:

```json
{
  "title": "શૈક્ષણિક કેલેન્ડર",
  "weeklyOff": "સાપ્તાહિક રજા",
  "noEntries": "આ દિવસે કંઈ નિર્ધારિત નથી.",
  "termStarts": "{{name}} શરૂ થાય છે",
  "termEnds": "{{name}} પૂર્ણ થાય છે",
  "stats": {
    "workingDays": "કાર્યદિવસો",
    "holidays": "રજાઓ",
    "totalDays": "કુલ દિવસો"
  },
  "legend": {
    "holiday": "રજા",
    "vacation": "વેકેશન",
    "weeklyOff": "સાપ્તાહિક રજા",
    "exam": "પરીક્ષા",
    "event": "કાર્યક્રમ"
  },
  "holidayTypes": {
    "public": "સાર્વજનિક રજા",
    "national": "રાષ્ટ્રીય રજા",
    "school": "શાળા રજા",
    "vacation": "વેકેશન",
    "weekly_off": "સાપ્તાહિક રજા"
  },
  "empty": {
    "title": "હજુ કોઈ કેલેન્ડર પ્રકાશિત નથી",
    "description": "તમારી શાળાએ આ વર્ષનું શૈક્ષણિક કેલેન્ડર હજુ પ્રકાશિત કર્યું નથી."
  }
}
```

`client/i18n/resources/hi/academicCalendar.json`:

```json
{
  "title": "शैक्षणिक कैलेंडर",
  "weeklyOff": "साप्ताहिक अवकाश",
  "noEntries": "इस दिन कुछ निर्धारित नहीं है।",
  "termStarts": "{{name}} शुरू होता है",
  "termEnds": "{{name}} समाप्त होता है",
  "stats": {
    "workingDays": "कार्यदिवस",
    "holidays": "छुट्टियाँ",
    "totalDays": "कुल दिन"
  },
  "legend": {
    "holiday": "छुट्टी",
    "vacation": "अवकाश",
    "weeklyOff": "साप्ताहिक अवकाश",
    "exam": "परीक्षा",
    "event": "कार्यक्रम"
  },
  "holidayTypes": {
    "public": "सार्वजनिक छुट्टी",
    "national": "राष्ट्रीय छुट्टी",
    "school": "स्कूल की छुट्टी",
    "vacation": "अवकाश",
    "weekly_off": "साप्ताहिक अवकाश"
  },
  "empty": {
    "title": "अभी कोई कैलेंडर प्रकाशित नहीं",
    "description": "आपके स्कूल ने इस वर्ष का शैक्षणिक कैलेंडर अभी प्रकाशित नहीं किया है।"
  }
}
```

Ask the user to confirm the Gujarati before it ships — the pilot schools are
Gujarati-medium and this copy is read by parents.

- [ ] **Step 3: Register the namespace**

In `client/i18n/config.ts`, follow the three places `holidays` appears:

```ts
import enAcademicCalendar from "./resources/en/academicCalendar.json";
import guAcademicCalendar from "./resources/gu/academicCalendar.json";
import hiAcademicCalendar from "./resources/hi/academicCalendar.json";
```

add `"academicCalendar",` to the namespace list near line 97, and `academicCalendar: enAcademicCalendar,` (and the `gu`/`hi` equivalents) to each resource map.

- [ ] **Step 4: Verify and commit**

```bash
cd client && npx tsc --noEmit
git add i18n/
git commit -m "feat(client): add academic calendar copy in en, gu and hi"
```

---

## Task 15: Fold Holidays into the calendar

**Files:**
- Delete: `client/app/(protected)/holidays/new.tsx`, `client/app/(protected)/holidays/[id]/edit.tsx`, `client/modules/holidays/screens/HolidayFormScreen.tsx`, `client/modules/holidays/screens/HolidaysScreen.tsx`, `client/modules/holidays/validation/schemas.ts`
- Modify: `client/app/(protected)/holidays.tsx`, `client/modules/holidays/services/holidayService.ts`, `client/modules/holidays/hooks/useHolidays.ts`, `client/common/components/chrome/AppDrawer.tsx:95`

- [ ] **Step 1: Prove what is safe to delete**

Before deleting anything, confirm each file has no consumer left. A bad grep path once deleted three live routes here — client module roots are `modules/` and `common/`, **not** `src/`:

```bash
cd client && ls -d modules common app
for name in HolidayFormScreen HolidaysScreen createHoliday updateHoliday deleteHoliday; do
  echo "--- $name"
  grep -rn "$name" app modules common 2>/dev/null | grep -v node_modules
done
```

Expected: `HolidayFormScreen` only in the two route files being deleted; `HolidaysScreen` only in `app/(protected)/holidays.tsx`; `deleteHoliday` in `useHolidays.ts` (whose delete path also goes).

**These must stay — each has a live consumer:** `holidayService.getHolidays`, `holidayService.getRecurring`, `holidayService.getHoliday`, `useHolidays` (minus its delete path), `modules/holidays/types.ts`, and the `holidays:` i18n namespace, which `modules/teacher-leaves/components/HolidayRow.tsx` reads for `holidays:form.types.*`.

- [ ] **Step 2: Delete the write surfaces**

```bash
cd client && git rm "app/(protected)/holidays/new.tsx" "app/(protected)/holidays/[id]/edit.tsx" \
  modules/holidays/screens/HolidayFormScreen.tsx \
  modules/holidays/screens/HolidaysScreen.tsx \
  modules/holidays/validation/schemas.ts
```

Then remove `createHoliday`, `updateHoliday` and `deleteHoliday` from `modules/holidays/services/holidayService.ts`, and the `deleteHoliday` callback from `modules/holidays/hooks/useHolidays.ts` along with the `CreateHolidayDTO` import if it becomes unused.

- [ ] **Step 3: Redirect the old route**

Replace `client/app/(protected)/holidays.tsx` entirely:

```tsx
import { Redirect } from 'expo-router';

/**
 * Holidays folded into the Academic Calendar, which is the single read-only
 * surface for closures on mobile (editing is admin-web's). Kept as a redirect
 * rather than deleted: shortcuts and notification deep links still point here.
 */
export default function Page() {
  return <Redirect href="/(protected)/academic-calendar" />;
}
```

- [ ] **Step 4: Repoint the drawer**

In `client/common/components/chrome/AppDrawer.tsx:95`, replace the holidays entry:

```ts
{ key: 'academic-calendar', label: 'Academic Calendar', icon: 'calendar-outline', iconActive: 'calendar', route: '/(protected)/academic-calendar', roles: ['admin', 'teacher', 'student', 'parent'], flag: 'academic_calendar', section: 'academics' },
```

Check whether `label` is a raw string or an i18n key in the surrounding entries and match them. If labels come from `navigation.json`, add the key to all three locales instead of hardcoding.

- [ ] **Step 5: Verify**

```bash
cd client && npx tsc --noEmit && npm run lint -- --no-cache
```

Expected: clean, and no unresolved import of a deleted file.

- [ ] **Step 6: Commit**

```bash
cd client && git add -A app modules/holidays common/components/chrome/AppDrawer.tsx
git commit -m "refactor(client): fold holidays into the read-only academic calendar"
```

---

## Task 16: Run it as each persona

This is not optional and it is not covered by the tests above: the tests prove the filter, not the screen.

- [ ] **Step 1: Read the dogfooding skill**

Invoke `dogfooding-as-end-user` and walk the calendar as Admin, as a Teacher, and as a Student against the local demo tenant (`default`: 2 campuses, 3 boards, 2,015 students — admin `admin@nexchool.in`).

- [ ] **Step 2: Confirm the matrix by eye**

For each persona, verify against spec §1: an exam window for another class is absent; a staff-only event is absent for the student; terms, vacations and public holidays are present for everyone; the working-day count is plausible.

**The Expo app cannot be built on this machine** (no Xcode simulator runtimes, no Android SDK). Ask the user to run it and send screenshots, and say plainly that the mobile pass is unverified until they do — do not claim the screen works from the type-check alone.

- [ ] **Step 3: Fix what the walk finds, then re-run the suites from Tasks 7 and 15.**

---

## Task 17: Documentation

**Files:**
- Create: `server/docs/architecture/adr/ADR-025-academic-calendar-visibility.md`
- Modify: `server/docs/architecture/debt-register.md`, `server/docs/modules/academic-management.md`, `.claude/memory/modules/academics_schedule.md`

- [ ] **Step 1: Write the ADR**

ADR-025 records the §1 matrix and the decision that narrowing keys on identity rather than on a permission string — including the two readings decided in the spec (teachers see student-facing events; students do not see staff-only events), and why the office desk stays unrestricted. Follow the shape of `ADR-024-leave-approval-authority-by-stage.md`.

- [ ] **Step 2: Register the debt**

Add to the Open section of `server/docs/architecture/debt-register.md`:

> **`/api/holidays` REST reads are not audience-scoped.** The calendar's GraphQL reads narrow holidays by `applies_to`; the REST list does not, because attendance and leave working-day math read it and narrowing it would change attendance behaviour. A teacher-only closure is therefore visible to a student through `/api/holidays` while being correctly hidden on the calendar. Exit: scope it when attendance's working-day source is settled.

- [ ] **Step 3: Update the module doc and the memory file**

Add the mobile surface, the audience rule and `currentAcademicCalendar` to `server/docs/modules/academic-management.md` and to `.claude/memory/modules/academics_schedule.md` — minimal diffs, not rewrites.

- [ ] **Step 4: Refresh the graph**

```bash
cd /Users/sahilsapariya/Documents/projects/school-ERP && graphify update .
```

`Rebuild failed` with exit 1 is expected on this repo — only `graph.html` fails, past the 5,000-node cap. Verify the run landed by checking `graphify-out/graph.json`'s mtime, not the exit code.

- [ ] **Step 5: Commit**

```bash
cd server && git add docs/architecture/adr/ADR-025-academic-calendar-visibility.md docs/architecture/debt-register.md docs/modules/academic-management.md
git commit -m "docs(calendar): record the calendar visibility rule as ADR-025"
```

---

## Deploy checklist

- [ ] **Reseed RBAC** so Student and Parent gain `academic_calendar.read`. Note the known trap: `scripts/seed_rbac.py` loads `.env`, whose `DATABASE_URL` points at the docker `postgres` host and overrides the shell env — run it where that resolves, or insert the grants directly.
- [ ] **No migration.** Nothing in this plan changes a table.
- [ ] **Watch `tenants.feature_flags`.** `academic_calendar` is an existing key and is unaffected, but that column is never pruned — do not reuse a retired key for anything new here.
