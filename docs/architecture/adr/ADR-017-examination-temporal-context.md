# ADR-017 — An Examination Belongs to a Cycle, Optionally to a Term, and May Reference a Window

## Status

Accepted — implemented 2026-08-12 (migration
`114_an_examination_is_an_event_with_papers`)

---

## Date

2026-08-12

---

# Context

Three dated things already exist above an examination, and it was not obvious
which one it hangs from.

**AcademicYear** is what the organization reports under — "2026-27". It carries
dates, but ADR-009 and the 2026-08-12 date-semantics work established that they
are *reporting* dates: a trust runs GSEB June-to-April and CBSE April-to-March
under one 2026-27, and neither matches the year's own span.

**AcademicCycle** is when the school is actually open. It owns the operating
dates. Classes, terms and calendars all belong to one.

**AcademicTerm** is a named subdivision of a cycle — Term 1, Semester 2.

And separately, **`exam_windows`** already exists: a calendar reservation of
time that the timetable and events are meant to avoid. It has its own service,
routes, import/export and admin screen, and it predates this work.

The temptation is to treat `exam_windows` as the examination, since it already
carries a name, an exam type and a date range. That is wrong for a reason worth
stating: a window is the *calendar's* booking of time, and it has no marks, no
papers, no students and no results. Merging them would give the calendar a
result model and the examination a JSONB list of class ids.

---

# Decision

**An Examination belongs to an AcademicCycle. A term is optional. An exam
window is a reference, never an identity.**

```
AcademicYear            reporting label — NOT stored on the examination
  └── AcademicCycle     REQUIRED. the operating period
        ├── AcademicTerm      optional
        └── Examination ──────┘  academic_term_id NULLABLE
                └── ExamPaper     dates checked against the CYCLE
```

**`academic_cycle_id` is NOT NULL, and there is no `academic_year_id` column.**
The year is reachable through the cycle. Storing it beside would be a
denormalisation with no reader and one more pair to keep in step — the opposite
call from `classes`, `academic_terms` and `academic_calendars`, where the column
already existed and fifteen readers used it.

**`academic_term_id` is nullable, and that is the point.** A board examination
is scheduled by the board. A surprise unit test belongs to no term the school
planned. Requiring a term would force schools to invent one.

**`exam_window_id` is nullable and non-owning.** Where a school has reserved
calendar time, the examination points at it. `exam_windows` keeps its meaning,
its service and its screens exactly as they are.

**Paper dates are validated against the cycle**, never the year — the rule the
calendar and terms already follow.

This was re-examined for **board examinations**, whose dates the board sets and
the school cannot move, and it was kept. The codebase holds two precedents that
look contradictory and are not: a *cycle* may sit outside the year it reports
under, because a year is a reporting container; a *term* may not sit outside its
cycle, because a cycle is the operating boundary. A paper is an operating event,
so it follows the term. Relaxing the rule would let a paper name a class from a
period that was not running when it was sat, with nothing downstream able to
detect it.

A sitting that genuinely falls outside the school's operating period is modelled
as its own cycle — the move the vacation batch already makes. No board-specific
branch, no flag, no exception: the school states its calendar and the same rule
then permits the paper. Proved by
`test_a_board_paper_outside_the_cycle_is_refused_and_has_a_way_through`.

**There is no global "current examination".** Several cycles run at once, so a
single answer would be wrong for at least two of them. Context resolves it: a
paper knows its examination, an examination knows its cycle.

---

# Consequences

## What this makes easy

- GSEB's Half Yearly and CBSE's Half Yearly under one 2026-27, each on its own
  dates, each with its own terms — and both named "Half Yearly", because
  uniqueness is per cycle.
- A 40-day vacation batch holding ordinary examinations, because a batch is a
  cycle.
- An examination that sits outside every term.

## What this costs

Creating an examination requires naming a cycle. For a school with one, the
service resolves it and nobody sees the field; for a trust with several, the
server refuses to guess — the rule established for classes and calendars.

## What a reader must not conclude

That `exam_windows` is deprecated. It is not. It answers "when is the hall
booked"; an Examination answers "what is being assessed, by whom, worth what".

---

# Alternatives considered

**Examination belongs to the AcademicYear** — rejected: the year's dates are
reporting dates, so a vacation batch's examination would be validated against
twelve months it does not run in.

**Examination replaces `exam_windows`** — rejected: deletes a working calendar
feature with its own UI and gives the calendar a result model.

**Term required** — rejected: board examinations and unscheduled tests have no
term, and inventing one is data a school did not enter.

**Store both `academic_year_id` and `academic_cycle_id`** — rejected here (and
accepted elsewhere) because no reader needs the year on this table.

---

# Related

- ADR-009 — academic year as operational context
- ADR-016 — examination grain
- `docs/architecture/reviews/2026-08-academic-domain-and-temporal-model-audit.md`
