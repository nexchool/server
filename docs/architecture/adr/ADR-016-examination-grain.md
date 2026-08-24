# ADR-016 — An Examination Is an Event; a Paper Is What a Student Sits

## Status

Accepted — implemented 2026-08-12 (migration
`114_an_examination_is_an_event_with_papers`; models
`modules/examinations/models.py`)

---

## Date

2026-08-12

---

# Context

Two different things a school says are both called an "exam".

*"The Half Yearly is in September"* names an **event**: one thing, with one
name, one set of rules, one result per child, one report card at the end.

*"Maths is on Tuesday, 9am, Room 101, 80 marks"* names a **sitting**: one
subject, one section, one date, its own maximum.

The product requirements arrived describing both as one entity, and
inconsistently: one screen modelled an exam as *class + subject + date + total
marks*, while another showed a report card for the same "exam" listing six
subjects and 600 marks. Both cannot be true of one row.

Choosing the sitting as the grain is the tempting one, because it is what gets
scheduled. It does not survive contact with results. Under it, a Grade 10 half
yearly is six unrelated rows all called "Half Yearly", and there is no entity a
percentage, an overall grade, a pass decision or a report card can attach to.
The aggregate would have to be recomputed by matching on a name string.

The opposite error is equally available: model only the event, and put subjects
inside it as a list. Then a subject has no date, no room, no start time and no
maximum of its own, and theory-and-practical — sat on different days, marked by
different people — has nowhere to live.

A third question sits underneath both: **who does an examination apply to?**
The obvious answer is to put `programme_id`, `grade_id`, `stream_id` or a list
of class ids on the examination. This is the same question AcademicCycle
answered three weeks earlier, and the same answer applies.

---

# Decision

**An Examination is the event. An ExamPaper is the sitting. Applicability is
derived from the papers.**

```
Examination            "Half Yearly", belongs to an AcademicCycle
  ├── ExamPaper        Grade 10 A · Maths      · 10 Sep · 100
  ├── ExamPaper        Grade 10 A · Science    · 12 Sep ·  80 (Theory)
  ├── ExamPaper        Grade 10 A · Science    · 13 Sep ·  20 (Practical)
  └── ExamPaper        Grade 10 B · Maths      · 10 Sep · 100
```

Three consequences, each deliberate:

**An Examination declares no applicability.** There is no programme, grade,
stream, campus or class column on it, and a test asserts their absence. Which
sections sit an examination is `SELECT DISTINCT class_id FROM exam_papers` — a
query, not a claim. A header saying "Grade 10" while its papers name Grade 9 is
a contradiction the schema cannot hold, which is better than one it merely
discourages.

**A paper names a `class_subject`, not a subject.** The offering already knows
the class, the subject, whether it is mandatory or elective, and its term. A
paper for a subject a section does not take is therefore not expressible.

**Theory and practical are two papers**, distinguished by `component_label`.
That is what a school sits, and it is what makes different dates, rooms and
maxima natural rather than a special case. Adding them back into one subject
total is a result-time concern.

An Examination with a single paper is ordinary, not degenerate: a weekly
subject test is exactly that.

---

# Consequences

## What this makes easy

- One report card per examination per student, with a real entity behind it.
- Grade 10 A and Grade 10 B sitting the same examination on the same day, with
  one event and separate papers.
- A JEE mock with three papers and no relationship to the school timetable.
- Asking "which sections sit this" without a second table to keep in step.

## What this makes harder, and why that is accepted

Creating an examination for a whole grade means writing several papers. A
Grade 10 half yearly across two sections and six subjects is twelve rows. That
is real work for the UI — a fan-out step in the scheduling screen — and it is
the honest shape: twelve sittings *are* twelve things a school must date and
room.

## What we deliberately did not build

**No AssessmentScheme table.** A reusable "Grade 10 Science = Theory 80 +
Practical 20" that stamps papers out is a *template over this model*, not a
different model. Building it now would mean guessing at reuse rules before any
school has expressed one, and every paper would then carry both its own maxima
and a scheme's. It can be added later without touching `exam_papers`.

**No applicability table.** Rejected above.

---

# Alternatives considered

**Sitting as the grain** — rejected: no entity for a result or a report card,
and aggregates matched on a name string.

**Event with an embedded subject list** — rejected: a subject then has no date,
room or maximum, and theory/practical is inexpressible.

**Applicability declared on the Examination** — rejected: a second owner of a
fact the papers already carry, and the contradiction becomes storable. This is
the error ADR-012 records and the rule AcademicCycle already follows.

---

# Related

- ADR-012 — academic domain reconciliation (the one-concept-one-owner rule)
- ADR-017 — an examination's temporal context
- ADR-018 — examination documents
- `docs/architecture/reviews/2026-08-12-examination-discovery-audit.md`
