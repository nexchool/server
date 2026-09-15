# Mobile Academic Calendar (read-only, audience-scoped)

**Status:** approved, not yet implemented
**Date:** 2026-09-15
**Repos:** `server`, `client` (Expo). `admin-web` is affected only by the scoping fix in §3.

## Problem

The Academic Calendar exists on admin-web only. Teachers, students and parents —
the people whose days it describes — cannot see it. The Expo client has a
Holidays screen instead, which shows one layer of the calendar and, contrary to
where editing belongs, can **create and edit** holidays.

Two visibility defects sit underneath that:

1. `academic_calendar.read` returns **every** exam window for **every** class. A
   Teacher holds that permission, so a Std 8 maths teacher can read the Std 12
   board-exam schedule. This is live on admin-web today.
2. Students and Parents hold no calendar permission at all, so there is nothing
   to scope — they simply cannot read it.

## Decision

Bring the calendar to mobile as a **read-only** surface, and make every calendar
read answer with what the caller is entitled to see rather than everything.

Editing stays on admin-web. Mobile has no create, edit, delete, export, import,
print or preferences surface.

## 1. Visibility matrix

The contract. Every read path must satisfy it.

| Layer | Admin | Teacher | Student / Parent |
|---|---|---|---|
| Weekly offs (incl. 2nd/4th Saturday) | all | all | all |
| Public / national holidays | all | all | all |
| Vacations | all | all | all |
| Terms and semesters | all | all | all |
| Exam windows | all | windows whose `applicable_class_ids` intersect the classes they teach | windows covering their own class |
| School events | all | all | `applies_to ∈ {entire_school, students}` |
| Working-day summary | over all of the above | over what they can see | over what they can see |

An exam window with an empty `applicable_class_ids` means the whole school, and
is visible to everyone. That is the field's existing meaning, not a new rule.

Two readings the requirement did not spell out, decided here so they are not
re-litigated:

- **A teacher sees student-facing events.** A sports day is a teacher's working
  day. Only exams are class-filtered for teachers.
- **A student does not see staff-only events** (`applies_to ∈ {teachers, staff}`)
  — a staff meeting or a teacher training day is not the student's information.

Parents are covered by the student rules: a household shares the student's
credential (ADR-011). When a school turns on separate parent logins, the parent
resolves through their child's class and the same row applies.

## 2. Where the filter lives

Server-side, at the service layer, on the single existing read path. Not in the
client: data the client filters has already left the server.

New `server/modules/academics/calendar/audience.py`:

```python
@dataclass(frozen=True)
class CalendarAudience:
    unrestricted: bool
    class_ids: frozenset[str] | None   # None when unrestricted
    applies_to: frozenset[str]

def resolve_calendar_audience(user=None) -> CalendarAudience: ...
```

Resolution order — first match wins:

| Caller | Audience |
|---|---|
| holds `academic_calendar.manage` (or `system.manage`) | unrestricted |
| is a teacher | `classes_taught_by(teacher.id)`, all `applies_to` values |
| is a student, or a parent of one | `{student.class_id}`, `{entire_school, students}` |
| none of the above (sub-admin, office staff) | unrestricted |

The last row is deliberate: it preserves exactly what a view-only sub-admin sees
on admin-web today. Narrowing happens because of **who you are**, not because of
which permission string you hold.

"Classes they teach" is the union of both ways a teacher meets a class:
class-teacher duty (`ClassTeacherAssignment`) and subject teaching
(`ClassSubjectTeacher`). A new `class_ids_taught_by()` in
`modules/academics/teaching_assignment.py` answers it.

It is deliberately **not** the existing `classes_taught_by()` in that file,
which reads `ClassTeacherAssignment` alone — "class teacher of" is the narrower
question attendance asks when deciding who may take a register. Asking it here
would hide a maths teacher's own exam window from them because somebody else is
the class teacher. `classes_taught_by()` is left alone.

### Threading it through

The audience is applied in one place — `_collect_day_sets()` in
`calendar/services.py` — plus `list_exam_windows()` and `list_school_events()`,
which gain an optional `audience` argument defaulting to
`resolve_calendar_audience()`. Everything downstream inherits the filter:
`compute_summary()`, `get_days_feed()`, and every GraphQL field built on them.

There is deliberately **no second, unscoped read path**. A future reader cannot
forget to scope, because there is nothing to forget.

Tests pass an explicit `CalendarAudience` rather than staging a request context.

## 3. Permissions

Add `academic_calendar.read` to the **Student** and **Parent** profiles in
`modules/rbac/catalog.py`. No new permission string is introduced: after §2 the
permission means "may open the calendar", and identity decides how much of it
comes back.

**Deploy step: reseed RBAC.**

This also closes defect (1) above — the Teacher over-exposure on admin-web — as a
side effect of scoping, with no change to the Teacher's permission list.

## 4. Server API

One new GraphQL field:

- `currentAcademicCalendar` — resolves the tenant's active academic year and its
  published calendar, returning the document, the days feed and the summary in
  one call.

Mobile should not need a year picker, three round trips, or permission to list
academic years in order to answer "is the 14th a holiday?".

Existing fields (`academicCalendar`, `calendarDays`, `calendarSummary`,
`calendarEvents`, `examWindows`) keep their shapes and become audience-scoped.

Mobile reads GraphQL. The client already posts to `/api/graphql` from
`modules/academics/services/academicStructureService.ts`; its private `gql()`
helper moves to `common/services/graphql.ts` so both modules share one.

## 5. Mobile screen

New `client/modules/academic-calendar/`, routed at
`app/(protected)/academic-calendar.tsx`.

- **Month grid** — a new `CalendarMonthGrid`, sibling to the datepicker's
  `MonthGrid` (that one is selection-only and carries no markers). Month arrows,
  a Today control, one coloured dot per day keyed to holiday / vacation / exam /
  event / weekly-off, and a legend.
- **Day list** — tapping a day lists its entries as cards. Today is selected on
  open.
- **Summary strip** — working days, holidays, current term, from
  `calendarSummary`.
- **Read-only** — no FAB, no swipe actions, no overflow menu.
- Empty state when the school has no published calendar; the
  `academic_calendar` feature guard is copied from today's `holidays.tsx`.

Primitives and skeletons come from the existing stable screens (`Text`,
`AppIcon`, `PressScale`, the HolidaysScreen card shape) rather than being drawn
fresh.

## 6. Folding Holidays in

The calendar becomes the single mobile surface for closures, matching what
admin-web already did.

**Removed:**

- `app/(protected)/holidays/new.tsx`
- `app/(protected)/holidays/[id]/edit.tsx`
- `modules/holidays/screens/HolidayFormScreen.tsx`
- `modules/holidays/screens/HolidaysScreen.tsx`
- `modules/holidays/validation/schemas.ts`
- `createHoliday` / `updateHoliday` / `deleteHoliday` on `holidayService`

**Kept — each has a live consumer, verified by grep:**

| Kept | Consumer |
|---|---|
| `holidayService.getHolidays`, `getRecurring` | `AdminAttendanceScreen`, `MarkAttendanceScreen`, `teacher-leaves/utils/workingDays.ts` |
| `useHolidays` | `MyTeacherLeavesScreen` |
| `modules/holidays/types.ts` | several of the above |
| `holidays:` i18n namespace | `teacher-leaves/components/HolidayRow.tsx` reads `holidays:form.types.*` |

`app/(protected)/holidays.tsx` becomes a redirect to `/academic-calendar`, so
shortcuts and deep links keep working. The drawer entry is renamed.

## 7. Tests

Server, one per matrix row:

- a teacher sees an exam window for a class they teach
- a teacher does not see one for a class they do not teach
- a whole-school exam window (`applicable_class_ids = []`) reaches everyone
- a student sees their own class's exam window and not another class's
- a student does not see an `applies_to='teachers'` event; a teacher does
- the working-day summary differs between a student and an admin when a
  staff-only holiday exists
- **regression:** a caller holding `academic_calendar.manage` sees exactly what
  they saw before (admin-web unchanged)

Client: the screen renders a published calendar, renders the empty state without
one, and exposes no write control.

## 8. Out of scope

- **`/api/holidays` REST stays unscoped.** Attendance and leave working-day math
  read it; narrowing it by `applies_to` would change attendance behaviour. The
  inconsistency is registered in the debt register instead of fixed here.
- No mobile export, print, import, view switcher or calendar preferences — those
  belong to admin-web.
- No change to exam-window branch scoping.
