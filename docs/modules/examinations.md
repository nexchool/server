# Examinations

## Purpose

The Examinations module holds the assessments a school runs and the outcomes
they produce: what is being sat, by whom, on which day, what each student
scored, what that adds up to, and what the school eventually tells a parent.

It is the module where a number becomes a statement. Everything up to marking
is bookkeeping that can be corrected quietly; publication is the moment the
school commits, and most of the design here exists to keep those two things
apart — so that a mark can be fixed without anyone being told twice, and a
published result can never be quietly edited.

The module defines no academic structure of its own. Sections, subjects,
offerings, cycles and enrollment belong to Academic Management, and an
examination reaches students only through them.

The module ships **switched off**. A school that does not run its assessments
here — because its board runs them, or because it reports only internal
marks — should not see it at all.

---

# Business Responsibilities

The Examinations module is responsible for:

- Scheduling an Examination
- Scheduling its Papers
- Opening a Paper for Marking
- Recording Marks
- Importing Marks in bulk
- Closing a Paper
- Requesting a Mark Correction
- Deciding a Mark Correction
- Computing a Result
- Publishing Results
- Revising a Published Result
- Issuing a Marksheet
- Filing Question Papers and Answer Sheets

---

# Module Ownership

## Exam Type

What a school calls its kinds of examination — Unit Test, Periodic Test, Half
Yearly, Preliminary, Board, Mock, Practical.

A **table, not a list in the code**. These differ by school and by board, and
adding one must never be a deploy. Nothing branches on the type: it labels and
groups, it does not decide.

## Examination

An assessment event the school holds. It belongs to an **Academic Cycle** —
the period when the school is actually operating — and optionally to a term.

An Examination **declares no classes, grades, mediums or streams.** Its papers
do. A "Half Yearly" is not a thing Grade 10 A sits; it is a thing the school
holds, of which Grade 10 A sits six papers.

It is named within its cycle. Two "Unit Test 1"s in one cycle are a picker with
two identical entries; the same name in the GSEB cycle and the CBSE cycle are
two different examinations, and both are legitimate.

Nothing guesses which cycle an examination belongs to. Several cycles run at
once, so a default or a date guess would silently file an examination in the
wrong operating period. It is named, or the school is asked.

## Exam Paper

One sitting: one subject, one section, one date. This is the grain a school
actually schedules and a student actually sits.

**Theory and practical are two papers**, not one paper with parts. They are sat
on different days, often in different rooms, and marked by different people. A
label says which is which so a result can add them back up.

A paper's class is read off the subject offering it examines rather than
supplied by the caller, so the two can never disagree about who sits it.

## Exam Mark

What one student got for one paper — or why they got nothing.

One mark per (paper, student). There is no subject-level mark and no
per-component mark: theory and practical are separate papers, so they are
separate marks.

## Mark Correction

A request to change a mark on a paper that has already been closed.

Closing a paper deliberately leaves no way back. The obvious way back — an
unlock button — puts the register into a state where a number can move with
nothing recording that it did. A correction is the way back, and it is a
request before it is a fact.

## Exam Result

A student's outcome for one examination: the totals, the percentage, the grade
and the pass, plus a snapshot of everything the calculation saw.

**Stored, not recomputed.** A published result is a statement the school made
on a date, and a grading scheme edited in December must not change what a
parent was told in August.

**Revised, never edited.** A correction after publication inserts a new version
and leaves the old one exactly where it is.

## Grading Scheme and Grading Band

How a number becomes a grade: a scheme, and the bands inside it.

Held as a **platform capability rather than an examination-owned one** —
attendance grades, co-scholastic grades and conduct grades will want the same
machinery, and a scheme living under Examination would have to be moved to give
it to them.

Nothing is hard-coded. A1/A2/B1 and Distinction/First Class/Pass are the same
table with different rows. Per-board grading needs no extra scoping: a CBSE
examination and a GSEB examination are different Examinations and each names
its own scheme.

## Examination Lifecycle Event

What happened to an examination, in the order it happened. Append-only: a
correction is a new event, never an edit to an old one.

---

# What This Module Does NOT Own

| Business Concept | Owner |
|------------------|-------|
| Person, Student | People Domain |
| Teacher, Employment | Staff Management |
| Academic Cycle, Term | Academic Domain |
| Section, Grade, Stream, Medium | Academic Domain |
| Subject, Subject Offering | Academic Domain |
| Academic Enrollment | Academic Domain |
| Teaching Assignment | Academic Domain |
| Business Authority | Authorization Domain |
| Document storage | Documents |

The module references these and never redefines them. In particular it has **no
examination-specific teacher**: who may mark a paper is answered by the same
teaching assignment that answers who teaches the subject.

---

# The Examination Lifecycle

```
Draft

↓

Scheduled

↓

Marks Entry

↓

Published
```

Any of the first three may be **Cancelled**. Published and Cancelled are
terminal — there is no unpublish, and there is no reopening.

Each move is recorded on the examination's own timeline —
`ExaminationScheduled`, `MarksEntryOpened`, `ResultsPublished`,
`ExaminationCancelled` — alongside `ResultsRevised`, which is on the timeline
without being a move: a revision leaves the examination published, because it
is already published and a second transition would be a second state machine
for the same fact.

The lifecycle is a single table read in one place, so a caller with expensive
validation of its own can refuse on the lifecycle first and say so in the
lifecycle's words — rather than reporting whatever its own checks happened to
notice about a draft.

---

# Marking

## The Register

A paper's register is its cohort: the students enrolled in the paper's class.
Eligibility comes from enrollment, not from counting — a child in a JEE batch
sits that batch's papers.

## Who May Mark

Whoever teaches this subject in this class **on the day of the paper**. It is
resolved through the same teaching-assignment service Attendance uses, so a
teacher who changed sections mid-year is judged against the day that matters.

## Which Campus

An examination declares no campus, exactly as it declares no classes — **its
papers carry the section, and the section carries the campus.** A user
restricted to one campus therefore sees an examination when any of its sittings
is in a section they hold, which is what lets a single "Half Yearly" belong to
every campus of a trust at once. Their papers, register, marks, corrections,
results and marksheets are their own.

An examination with no paper in their campus is not listed for them, the same
way a teacher with no class there is not — it appears the moment a paper lands
in one of their sections.

Two rules are easy to get backwards:

- **A list filters; an operation on one named thing refuses.** A reviewer
  opening a correction queue that happens to hold another campus's request
  wants their own rows, not an error. Asking for one paper, one child's
  marksheet or one revision out of branch is refused outright.
- **`papers_for` is not branch-scoped, and that is deliberate.** It is the
  calculation's input, not a screen's. Scoping it would make a student's result
  depend on who pressed calculate — a child enrolled in another campus's batch
  would total differently — and a result is a frozen snapshot, so the
  difference would be permanent. `papers_with_labels` is the screen's read and
  is scoped.

## Mark States

A student's outcome for a paper is one of five things, and the fifth is the
absence of a record:

| State | Meaning |
|---|---|
| Present | A number, including a genuine zero |
| Absent | Did not sit it |
| Exempted | Excused from it |
| Malpractice | Sat it; the attempt does not count |
| *(no record)* | **Not yet entered** — the teacher has not finished |

**Absence is a status, never a number.** A mark is stored only for a student
who was present; the database itself refuses the alternative. Recording zero
for an absent child would fail them and drag the aggregate, and a blank would
be indistinguishable from an unfinished register.

**Not yet entered never becomes anything else.** It is not a zero and not an
absence. Turning a teacher's unfinished work into a failed student is the exact
mistake the status column exists to make impossible.

## Bulk Import

A register may be uploaded as a workbook. Two steps: a preview that validates
and writes nothing, then an import that validates again and writes everything
or nothing.

**One register, one outcome.** This parts company with the student importer,
which commits row by row on purpose — five hundred students are five hundred
independent facts, and landing 497 of them is a good day. A paper's marks are
one register: landing 38 of 40 leaves a teacher unable to tell which two are
missing and makes re-uploading the sheet ambiguous.

**Import creates; it never overwrites.** A row for a student who already has a
mark is refused. Changing an existing mark is an update while the paper is
open and a correction once it is closed — both of which have somebody's name
attached. An importer that silently overwrote would be a way to move marks with
no record of who moved them.

Every imported row goes through the same validation ordinary entry uses. There
is no second rulebook.

---

# Corrections

Once a paper is closed, a mark changes by request.

```
Correction Requested

↓

Decision

↓

Approved → mark updated     Rejected → mark unchanged
```

Both outcomes are terminal and both are kept.

**The request states what it is changing *from*.** Without that, approving two
requests against the same mark applies the second one's arithmetic to a number
nobody is looking at any more. With it, the second is refused as stale and the
school is asked to look again.

**Approval re-validates from scratch.** The mark is re-read, the from-state
re-checked, and the new value run through exactly the same validation ordinary
entry uses.

Asking and deciding are different authorities — the same split that already
separates marking a register from closing it.

---

# Results

Marks stay the source of truth. A result is a **frozen presentation** of them.

## How a Result Is Computed

Recorded in full in ADR-020. In summary:

- **Present** contributes its marks and its maximum. **Absent** and
  **malpractice** contribute nothing to the numerator and their full maximum to
  the denominator — the student is measured against what they could have
  scored. **Exempted** contributes to neither, so an exemption can never lower
  a percentage. **Not yet entered** contributes to neither and makes the result
  *incomplete*.
- **Pass is three-valued.** A student may fail one subject while the aggregate
  passes, which is an ordinary Indian school rule. Where a school configured no
  pass rule at all, the answer is *neither* — a real answer, not a missing one,
  and better than inventing a verdict the school never asked for.
- **Rounded once, and the stored number is the graded number**, so a marksheet
  printing 90.000 beside an "A" is impossible. Computed in decimal, never
  floating point, and rounded the way a school would explain it to a parent
  rather than the way a language happens to.
- **A student exempted from everything has no percentage**, not zero — zero
  would say they failed every paper they were excused from.
- **Weighting is refused, not guessed.** Where a school has configured paper
  weights, the calculation stops and says so, because ignoring them would
  silently produce an unweighted result for a school that asked for a weighted
  one. Weighted aggregation is unbuilt (debt 52).

## Grading

Bands are matched on the rounded percentage, inclusive at both ends.

A school with no scheme, or a scheme with no bands, is legitimate — a school
that reports marks only still has a scheme. A gap between bands produces no
grade and a recorded warning rather than a nearest-band guess, because choosing
the nearest band would be inventing policy the school did not write down.

The resolved band — its label, its bounds, its pass and its grade point — is
copied into the result. **A result is never re-graded on read.**

## Incomplete Examinations Calculate

A paper may be closed with marks outstanding, so "closed" does not mean
"complete". Calculation is never blocked by missing marks; the result simply
records that it is incomplete, and publication is what refuses.

---

# Publication and Revision

## Publication

Publication is the moment computed figures become **the school's word**.

It computes nothing. It checks that every result is fit to be stated, stamps
them, moves the examination, and records the event — all in a single
transaction, because a school that has told half a class cannot afterwards say
which half.

Three things refuse publication: a student in the cohort with no result at all;
a result that is incomplete, because "not yet entered" cannot become the
school's word; and a grade that could not be resolved *when the school
configured bands that should have covered it*. That last distinction matters —
a school that configured no pass rule at all is publishable, and a blunt rule
would leave a marks-only school permanently unable to publish.

Publication never calculates on somebody's behalf. Doing so would make
publication a moment when the figures can still change.

## Revision

A published result is immutable forever. A genuine error found afterwards is
answered by **adding a version**, never by editing one.

The trigger is a correction approved *after* publication. Approving that
correction changes the mark and deliberately does not touch the published
result, which leaves a window where the marks and the published figures
disagree. **The window is the point** — reconciling them is a decision somebody
takes, not a side effect of approving a correction. A revision with no approved
correction behind it is refused: an official statement is not reissued because
somebody pressed a button.

**Scope is one student.** A result reads one student's marks and nothing else —
no rank, no cohort average, no shared denominator — so one child's corrected
mark cannot alter another's figures. Versioning a whole cohort would retire
thirty-nine correct published results to say nothing new about any of them.

**Revising and re-issuing are separate acts.** A revision starts unpublished,
because recomputing a number and telling a parent it changed are two decisions
and a school gets to make them separately.

## Current Is Not Official

Between a revision and its publication, the **current** version is a working
figure nobody has been told about, while the school's word is still the older
**published** one.

Anything showing a result to a parent asks for the official one. Anything
showing a school its own working state asks for the current one. Collapsing the
two would either show parents figures the school has not agreed to, or hide
from the school what it is about to say.

---

# The Marksheet

**A marksheet, not a report card**, and the name is the decision. This is one
examination's outcome for one student. An annual document aggregating unit
tests, half yearly and final is a different artefact that would *read* results
rather than replace them, and nothing here forecloses it (debt 49).

Rendered from a **published version**, never from live data. Everything the
document needs — the per-paper breakdown, the totals, the resolved band — was
captured when the result was computed. So a marksheet is reproducible from the
result alone, and a revision produces a v2 document while v1 stays retrievable
and unchanged **by construction**: they are different rows, and neither is ever
written to again.

No file is stored. There is nothing to keep in sync, and nothing that can
disagree with the result it claims to represent.

---

# Documents

Question papers and answer sheets are filed in the platform's shared document
store rather than in a table of this module's own.

The owners are chosen so the reference is exact:

- a **question paper** belongs to the paper — the Mathematics paper, not the
  whole Half Yearly;
- an **answer sheet** belongs to the mark — this student's outcome for this
  paper. That pair is precisely what an answer sheet is about, and keying it on
  the student alone would lose which sitting it came from.

---

# Authority

Authority is deliberately not one key. Whoever closes a register is not
necessarily whoever tells the parents.

| Act | Authority |
|---|---|
| View examinations and results | `examination.read` |
| Create, schedule, cancel | `examination.manage` |
| Publish and revise results | `examination.publish` |
| Enter marks | `assessment.enter` |
| Correct a mark | `assessment.update` + teaching authority for the paper |
| Decide a correction, close a paper | `assessment.manage` |
| View own marks / own classes / all | `assessment.read.self` / `.class` / `.all` |

A teacher who may correct a mark does not thereby reissue the school's word,
and a publisher does not thereby gain mark-correction authority.

---

# Surfaces

**GraphQL** carries the business operations: listing and reading examinations,
exam types, creating and scheduling and cancelling, adding papers, the marking
register and recording marks, the correction queue and its decisions, the
result board, calculating, publishing, revising and publishing a revision.

**REST carries only bytes** — the marks-sheet template and preview, the import
upload, and the marksheet PDF. Nothing about the transport makes these a second
way in: they answer to the same authority and the same switch.

---

# The Feature Switch

`examinations` is an optional module a super-admin turns on per school.

It is the first key that **defaults to off**. Every other optional feature
treats a missing answer as "on", which is right for a module a school was
already using and wrong for one nobody has ever had — left alone, that rule
would have handed examinations to every school on the deploy that introduced
it.

The switch is in front of **every** operation in the module, not the ones that
looked important, and it refuses in its own words rather than as a permission
failure: an officer holding every examination permission there is should not be
told they lack authority when the truth is that the school does not run this.

---

# Business Principles

## An examination declares nothing about who sits it.

Its papers do. This is what lets one examination span two boards, two mediums
and twenty campuses without a branch in the code.

## Absence is a status, never a number.

And an unfinished register is neither an absence nor a zero.

## Marks are the truth; a result is a photograph of them.

Nothing that computes a result changes a mark.

## A published result is immutable.

Corrections add versions. There is no unpublish.

## Configuration, not forks.

Exam types, grading schemes and bands are rows. Onboarding a board with
different grading requires no code.

## Refuse rather than guess.

An unnamed cycle, a weighted paper, a band gap: each stops and says so. A wrong
number with no indication that it is wrong is worse than no number.

## One rulebook.

Bulk import, correction approval and ordinary entry all run the same
validation. A second copy is a second set of rules that will drift.

---

# What Is Not Built Yet

Registered in `architecture/debt-register.md`; listed here so this document is
not read as a claim of completeness.

| | |
|---|---|
| debt 48 | No assessment scheme — a school repeating Theory 80 + Practical 20 across every subject configures it every time |
| debt 49 | Report card versus marksheet is undecided; only the per-examination marksheet exists |
| debt 51 | Once a paper closes, how many students were never marked is unrecoverable |
| debt 52 | Weighted aggregation is unbuilt, and paper weights block calculation until it is |
| debt 53 | Grading bands have no integrity constraints; overlaps and gaps are legal |
| debt 54 | ADR-019 is cited by the model and was never written |

Surfaces the roadmap names and this module does not yet have: question-paper
and answer-sheet screens (EX-10), an examination layer on the academic calendar
(EX-12), examination notifications (EX-13), the student's and parent's own view
of a result (EX-14), and an examinations dashboard (EX-15).

---

# Related

- `docs/architecture/adr/ADR-016-examination-grain.md` — applicability is derived from papers
- `docs/architecture/adr/ADR-017-examination-temporal-context.md` — an examination belongs to a cycle
- `docs/architecture/adr/ADR-018-examination-documents-and-result-snapshots.md` — frozen versioned snapshots
- `docs/architecture/adr/ADR-020-examination-result-computation.md` — how a result is computed
- `docs/modules/attendance.md` — the correction workflow this one follows
- `docs/modules/academic-management.md` — the structure every paper reaches through
