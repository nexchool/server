# ADR-018 — Examination Documents Reuse the Shared Store; Results Are Frozen Snapshots

## Status

Accepted — implemented 2026-08-12 (migration
`114_an_examination_is_an_event_with_papers`; owner kinds in
`modules/examinations/documents.py`)

---

## Date

2026-08-12

---

# Context

Two storage questions arrived together, and both had an obvious wrong answer.

**Where do question papers and answer sheets live?** The obvious answer is a
new `exam_documents` table with an S3 key, a mime type, a size and an uploader.
That is the fourth time this codebase would have written those columns —
`student_documents`, `announcement_attachments` and `person_documents` came
before it — and migration 106 already consolidated them. Its docstring says so,
using `exam_paper` as the worked example:

> A domain that wants documents registers an owner kind and gets the whole
> store: upload, listing, deletion, completeness, tenant-scoped keys. It does
> not write storage code, and it does not get its own table.

**What is a result?** The obvious answer is a view: sum the marks, apply the
grading bands, show a percentage. It is wrong for a reason that only shows up
months later. A published result is a *statement the school made on a date*. If
it is recomputed on every read, then editing a grading band in December
silently rewrites what a parent was told in August — and the school now has two
different official answers with no way to tell which was given.

---

# Decision

## Documents: register owner kinds, add no table

```
documents  (owner_kind, owner_id)          — migration 106, unchanged
   ├── owner_kind = "exam_paper"  → question_paper
   └── owner_kind = "exam_mark"   → answer_sheet
```

The owners are chosen so the reference is exact. A **question paper** belongs to
the `exam_paper` — the Mathematics paper, not the whole Half Yearly. An
**answer sheet** belongs to the `exam_mark`, which is precisely "this student,
this sitting". Keying an answer sheet on the student alone would lose which
sitting it came from; keying it on the paper alone would lose whose it is.

Each kind supplies `resolve_tenant`, which is the price of a polymorphic
reference: the store refuses to write a document whose owner it cannot place in
a school. Cleanup is the other half — a domain deleting an owner calls
`delete_all_for`.

## Results: snapshot, versioned, never edited

`exam_results` stores the computed figures — totals, percentage, grade label,
pass — rather than deriving them on read, plus a `snapshot` JSON holding the
context they were computed in.

**A correction inserts version N+1 and leaves N where it is.** `is_current`
names the one in force, guarded by a partial unique index; a second current
result for one student is refused by the database. Nothing updates a published
row.

**Calculation and storage are separate.** How a result is computed —
weighting, best-of-N, whether a failed subject caps the aggregate — is a
service concern that will change as schools ask for it. What was *published*
must not.

---

# Consequences

## What this makes easy

- Reprinting a marksheet from two years ago and getting what it said then.
- Editing grading bands without a migration and without touching history.
- Question papers and answer sheets with no new storage code, no second S3
  path convention and no fourth copy of the mime/size columns.

## What this costs

A result that is wrong because the *marks* were wrong must be revised, not
edited: recompute, insert a new version, stand the old one down. That is more
work than an UPDATE, and it is the work that makes the record trustworthy.

A published result can drift from what recomputing would now produce. That is
not a defect — it is the distinction between a record and a view.

## What a reader must not conclude

That an ExamResult is a report card. It is one examination's outcome for one
student. A report card may aggregate several examinations across a year, and
nothing here prevents that: it will read results, not replace them. Deciding
whether the first deliverable is a per-examination marksheet or an annual
report card remains open.

---

# Alternatives considered

**An `exam_documents` table** — rejected: a fourth copy of storage columns that
migration 106 consolidated specifically to prevent, and its docstring names this
exact case.

**Answer sheets on `person_documents`** — rejected: `person_id` is NOT NULL and
a script is about a sitting, not about a human's papers. ADR-015 would have to
be bent.

**Results as a view** — rejected: a published statement that changes when
configuration changes.

**Results updated in place with an `updated_at`** — rejected: the previous
figures are the thing somebody asks about, and an UPDATE destroys them.

---

# Related

- ADR-015 — person-owned documents (and the store it generalised into)
- ADR-016 — examination grain
- migration 106 — `a document belongs to the person, and the store belongs to everyone`
