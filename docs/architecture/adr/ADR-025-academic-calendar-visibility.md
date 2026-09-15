# ADR-025 — What You See on the Academic Calendar Follows From Who You Are

## Status

Accepted

---

## Date

2026-09-15

---

# Context

The academic calendar was built for admin-web, where everybody reading it was
an administrator. Every read answered with the whole thing, and that was the
right answer for the only audience there was.

Two permissions were then handed out on that assumption. `academic_calendar.read`
went to the Teacher role, so a teacher could open the calendar — and read every
class's exam schedule, including the Std 12 board dates, from a Std 8 account.
Nothing in the code was wrong by its own lights: the permission classes answered
*whether* the caller could open the calendar, which they did correctly, and no
layer was asking *how much of it they should get*.

Bringing the calendar to the phone made that gap load-bearing. Teachers,
students and parents are the people whose days the calendar describes, and they
are also the people who must not read each other's. Students and parents held no
calendar permission at all, so there was nothing to narrow — they simply could
not open it.

The question this decision answers is where the narrowing lives.

# Decision

**Every calendar read is answered from a `CalendarAudience`, resolved from the
caller's identity.**

`modules/academics/calendar/audience.py` resolves one value — how many classes
this person may see exams for, and which `applies_to` audiences are theirs — and
every read narrows by it. First match wins:

| Caller | Audience |
|---|---|
| holds `academic_calendar.manage` | the whole calendar |
| is a teacher | the classes they teach; all `applies_to` values |
| is a student, or a parent of one | their own class; `entire_school` and `students` |
| none of the above | the whole calendar |

## What each audience sees

| Layer | Admin | Teacher | Student / Parent |
|---|---|---|---|
| Weekly offs, public holidays, vacations, terms | all | all | all |
| Exam windows | all | windows touching a class they teach | windows covering their own class |
| School events | all | all | `applies_to ∈ {entire_school, students}` |
| Working-day summary | over all of it | over what they see | over what they see |

An exam window with an empty `applicable_class_ids` means the whole school and
reaches everybody. That is what the field already meant; it is not a new rule.

Two readings, decided here so they are not re-argued:

- **A teacher sees student-facing events.** A sports day is a teacher's working
  day. Only exams are class-filtered for teachers.
- **A student does not see staff-only events.** A staff meeting or a training
  day is not the student's information, even though it is not another student's
  either.

## Why narrowing keys on identity, not on a permission

`academic_calendar.read` now means "may open the calendar". How much comes back
is decided by being a teacher or a student, not by holding a second, narrower
permission string.

This is what let Students and Parents be given `academic_calendar.read` without
giving them the school's whole calendar, and it is what closed the teacher hole
without touching the Teacher role's permission list at all.

It is also what `requires_any` already said. Its docstring: *"a head teacher may
read the whole school, a class teacher only their own classes. Both reach the
same field; what differs is what it returns, which is the resolver's job."* The
guard was right; nothing had taken up its half of the bargain.

The fourth row of the table — a caller who is neither teacher nor student gets
everything — is deliberate, not a gap. It is the office desk and the view-only
sub-admin, and it preserves exactly the calendar they see on admin-web today.
Keying narrowing on *lacking* `manage` would have quietly taken the calendar
away from them.

## Where it is applied

The services take an `audience` and default to the whole calendar; the
authenticated boundary resolves the caller's and passes it. Concretely,
`_collect_day_sets`, `list_exam_windows` and `list_school_events` narrow, and
`compute_summary` and `get_days_feed` inherit it. `CalendarQuery` and the export
route resolve it.

Services do not read identity off the request. A service asked with no audience
describes the school's calendar, which is what a publish snapshot and any future
background job want; deciding *whose* calendar a request is about is an
authorization question and belongs where the other authorization questions are.
The cost is that a new read field must remember to pass one — `_for_the_caller()`
exists so that it is one call, and `tests/test_calendar_audience.py` asserts the
matrix over the wire rather than only at the service.

# Consequences

- A teacher on admin-web stops seeing other classes' exam windows. This is a
  visible change to a surface that shipped, and it is the point.
- Students and Parents gain `academic_calendar.read`. **Deploying this requires
  an RBAC reseed.** No migration.
- The working-day count is now per-audience: a staff-only closure is a working
  day for a student. Two people can correctly see different totals.
- `/api/holidays` REST reads stay unscoped — attendance and leave working-day
  math read them, and narrowing them would change attendance behaviour. The
  inconsistency is in the debt register with an exit condition.
