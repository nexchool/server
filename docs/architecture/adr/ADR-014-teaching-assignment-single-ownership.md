# ADR-014 — One Owner for Teaching, Reached Through a Service

## Status

Accepted — implemented 2026-08-07 (migration `092_teaching_has_one_owner`;
service `modules/academics/teaching_assignment.py`)

---

## Date

2026-08-05

---

# Context

Two different questions a school asks every day had been allowed to blur into
each other, and each was being answered from more than one place.

**Who teaches this subject in this class?** Recorded twice:

- `class_teachers` — class + teacher + subject, from v1. 59 rows: 51 carrying a
  subject, 8 carrying none. No validity dates, so a teacher who takes over a
  subject in October cannot be recorded as having done so from October.
- `class_subject_teachers` — teacher against a `class_subject`, with a role and
  an effective date range. 55 rows.

Fifty-one rows said the same thing in both. Four existed only in
`class_subject_teachers`. Nothing anywhere declared which was authoritative, so
a reader picking the other one got a different answer — and the branch-scope
filter added the same week had to union both tables to work out whose teacher a
teacher was.

**Who is the class teacher?** Recorded in three places: `classes.teacher_id`,
`class_teacher_assignments`, and — as a boolean flag — on the *subject* table,
`class_teachers.is_class_teacher`. A responsibility for a whole class was
being stored as a property of teaching one subject.

The blur is the cause, not the duplication. Once `is_class_teacher` sat on a
subject row, the two questions could not be told apart, and every later reader
had to guess which one it was asking.

---

# Decision

## Subject teaching has one owner

`class_subject_teachers` is the single owner of *who teaches a subject in a
class*. It hangs off `class_subjects`, which is where a subject genuinely
belongs to a class, and it carries the role and the effective dates that make a
mid-year change expressible.

`class_teachers` is retired. It holds nothing that is not already recorded:
every one of its 51 subject rows exists in `class_subject_teachers`, and every
one of its 12 class-teacher rows exists in `class_teacher_assignments`.

## Class teacher responsibility has one owner

`class_teacher_assignments` is the single owner of *who is responsible for a
class*.

`is_class_teacher` is removed. A responsibility for a class is not a property
of teaching one of its subjects, and keeping the flag would leave the two
questions blurred in exactly the way that caused this.

## Caches are caches

`classes.teacher_id` and `students.class_id` remain, and remain useful — they
are denormalised pointers to the current answer, maintained by the service that
owns the underlying fact.

They are **never** business owners. Nothing decides anything from them. A
reader that needs to know who teaches a class, or which class a child is in,
asks the owner. The cache exists to make a listing fast, not to answer a
question.

## Operational modules ask the service, not the tables

Attendance, timetable, notifications, examinations and everything after them
resolve teaching through the Teaching Assignment service. No operational module
queries `class_subject_teachers` or `class_teacher_assignments` directly.

This is what stops the next duplication. Tables get read from wherever somebody
happens to be standing; a service is one place to change when the model moves
again — and the model has already moved twice.

## Time is part of the question

- **Current operations** — today's attendance, today's timetable, who to notify
  now — resolve against *active* assignments.
- **Historical operations** — last term's marks, an audit of who taught when, a
  report card for a year already closed — resolve against the assignment that
  was in effect *at that time*.

A historical question answered with today's assignment is a wrong answer that
looks right, which is the worst kind. The service takes the date the question
is about.

---

# Consequences

## Positive

- One answer to "who teaches this", from one place, whatever asks.
- A mid-year teacher change becomes recordable rather than a silent overwrite.
- Marks and report cards can attribute teaching to whoever actually taught,
  because the assignment in effect at that time is still there to read.
- The branch-scope filter stops unioning two tables to answer one question.

## Trade-offs

- Operational modules gain a dependency on a service where they had a table.
  That is the point, but it is a real constraint on new code.
- Resolving through a service costs a call where a join used to do. Any list
  that resolves teaching per row must be given the page's assignments once —
  the same rule already applied to People and to transport.
- `class_teachers` disappearing changes five modules that read it, one of which
  is the live `/api/timetable`.

---

# Migration Debt

None created. `class_teachers` is redundant on every row, so this is a reader
migration and a table drop, with no data to carry.

Two caches remain by design (`classes.teacher_id`, `students.class_id`). They
are not debt, but they need a guard proving they cannot drift from their owner
— `tests/test_caches_follow_their_owner.py` is that guard (added 2026-08-07).

---

# Related Documents

- `ADR-008` — Teaching Assignment as the Academic Responsibility
- `ADR-012` — Academic Domain Reconciliation
- `docs/architecture/reviews/2026-08-05-foundation.md` — findings AC1, AC3
- `docs/modules/academic-management.md`
