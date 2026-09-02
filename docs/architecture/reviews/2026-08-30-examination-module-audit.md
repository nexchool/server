# Examination module audit — 2026-08-30

**Scope:** `server/modules/examinations`, its four ADRs, its admin-web surface, and its
coupling to the Academic Calendar.
**Branch:** `develop` (identical to `main` for this module).
**Method:** read the code, not the docs. Every claim below carries a file:line citation
and was verified directly.

---

## Verdict

The module is **substantially complete and unusually well-built** — the domain modelling
is the best in this codebase. It is also **live on `main`, which is what prod deploys
from**, and it was switched on in prod for the only tenant by the stale-feature-key
landmine before migration 120 closed it.

The blocking problem is **cross-branch**: examinations has *zero* branch scoping.
Thirty-one other service files call `core/branch_scope`. This one calls it never. On a
multi-campus trust, a campus-restricted admin can list, schedule, mark and publish
examinations for every other campus.

The calendar relationship is real but **thin in the backend and unreachable from the
UI** — a school can create an "exam window" that reserves nothing, and an examination
that ignores it.

| Severity | Count |
|---|---|
| Critical | 3 — **1 fixed** (EX-A1, 2026-08-30) |
| High | 7 |
| Medium | 6 |
| Tests passing (3 files run) | 81 |
| Lines shipped | ~6,100 |

> **Update 2026-08-30:** EX-A1 (no branch scoping) is **fixed** — closed as debt 56, with
> `tests/test_branch_enforce_examinations.py` covering it in 14 tests. Full suite green at
> 2,232. The remaining fifteen findings stand as written.

---

## 1. What actually works

This module clears a higher bar than most of the codebase. The flaws further down sit on
a good foundation.

- **The marks state model is correct.** Present (including a genuine zero), absent,
  exempted, malpractice, and *not yet entered* — the last being the absence of a row,
  never a silent zero. This is the thing most school ERPs get wrong.
- **Results are frozen versioned snapshots**, never recomputed on read. Percentage
  computed once in `Decimal` with `ROUND_HALF_UP`. Pass/fail is three-valued, so
  "no grading scheme configured" cannot masquerade as "failed".
- **Publication computes nothing** — it stamps and seals. Revision inserts version N+1
  for one student and never touches version N.
- **Corrections state what they are changing from**, which defeats stale double-approval.
  Both approve and reject are terminal, and both are kept.
- **One transport per operation.** GraphQL carries every business operation; REST carries
  only four genuinely-infrastructural routes (marks template, preview, XLSX import,
  marksheet PDF). No REST/GraphQL duplication — the locked v2 rule holds.
- **Authorization is enforced in the services**, not just at the resolver edge.
  `assessment.*` and `examination.*` are real catalogue entries
  (`modules/rbac/catalog.py:86-94`).
- **Marking authority resolves through the teaching-assignment service**
  (`subject_teacher_of`, `marks_service.py:39`) — it builds on the post-ADR-014 shape
  rather than copying attendance's old `class_id + marked_by` shape, which is exactly
  what the roadmap warned about.
- **It ships dark.** `examinations` is the sole member of `DEFAULT_OFF_FEATURES`
  (`core/feature_flags.py:84`).
- **admin-web is complete** — six screens (list, detail, papers/marking register,
  results, corrections, wizard), each with tests, no stubs or mock data, and tenant-query
  conventions correctly followed throughout.

---

## 2. The flow, end to end

The lifecycle is a genuine sequence, and the module models it as one: a single table with
append-only lifecycle events.

```
Draft ──▶ Scheduled ──▶ Marks Entry ──▶ Published
  │      (dates fixed)  (per paper,     (sealed +
  │                      then lock)      versioned)
  └──▶ Cancelled
```

| Stage | What happens |
|---|---|
| **Setup** | An **Examination** is the event ("Half Yearly"). It belongs to an **Academic Cycle** and an **Exam Type**, and declares no classes, grades, mediums or streams of its own. |
| **Papers** | An **ExamPaper** is the sitting: one subject, one section, one date. Theory and practical are two papers, not one. The class is *derived* from the subject offering and never accepted from the caller — so a paper cannot contradict the offering it names. |
| **Marking** | One **ExamMark** per student per paper. Entry authority comes from the teaching assignment. Bulk entry via XLSX template → preview → import. A locked paper's cohort is its own mark rows, which is what lets the register survive promotion and transfer. |
| **Correction** | A **request → decision** workflow. The request records the value it is changing *from*, so a stale approval cannot silently overwrite a newer mark. |
| **Result** | Computed once into a frozen, versioned **ExamResult** snapshot. Never recomputed on read. |
| **Publish** | Stamps and seals — computes nothing. A **revision** writes version N+1 for a single student and leaves N intact. |
| **Marksheet** | Rendered on demand from a published version. No file is stored. |

---

## 3. The Academic Calendar relationship

There *is* a real link — `examinations.exam_window_id` → `exam_windows.id`
(`models.py:334-339`) — but it is far weaker than the words "reserved examination window"
imply, and no screen can set it.

An **Exam Window** is created in step 6 of the Academic Calendar wizard. It captures a
name, a type, a status, a date range, an optional description, and
`applicable_class_ids`. Its promise in the UI is *"These dates will be reserved for exams.
Timetable will avoid these days."*

What a school would reasonably assume the link enforces, against what it actually does:

| | Invariant | Reality |
|---|---|---|
| ✅ | The window belongs to this tenant, and to the same academic year | The only two checks that exist. `services.py:135-157` `_validate_window` |
| ❌ | Paper dates fall inside the window that reserved them | Paper dates are validated against the **academic cycle's** range, never the window's. An examination linked to a 10–20 December window can hold papers in March and nothing objects. `services.py:206-221` |
| ❌ | The examination only covers the classes the window applies to | `applicable_class_ids` is never read by the examinations module — zero references across the package. |
| ❌ | Deleting a window warns you that examinations depend on it | No guard. The FK is `ondelete="SET NULL"`, so deleting a window silently unlinks every examination pointing at it. The audit log records the window's deletion; nothing records the unlinking. `calendar/services.py:413` · `models.py:336` |
| ❌ | "Half Yearly" means the same thing on both sides | Two disjoint vocabularies. The calendar's `exam_type` is a hardcoded six-value string enum; the examination's `exam_type_id` is a tenant lookup table. Nothing maps them. `calendar/models.py:199` · `calendarOptions.ts:42-49` |
| ❌ | A school can actually make the link | The create wizard never sends `examWindowId`. It appears in the TypeScript types and the GraphQL read selection, but in no form, dropdown or mutation variable — so in practice the column is always `NULL`. `CreateExaminationWizard.tsx:183-188` |

Underneath all six sits a structural mismatch the code itself acknowledges: **exam windows
are scoped to the academic *year*, examinations to the academic *cycle*** — see the
docstring at `services.py:138-143`. That is why the only available check is the weak one.
Any real enforcement needs that mismatch resolved first.

---

## 4. Findings

Sixteen, ordered by what will hurt a real school first. Items tagged *(debt register)* are
already tracked; the rest are written down nowhere.

### Critical

#### EX-A1 — Examinations has no branch scoping at all; campus isolation does not exist

> **✅ FIXED 2026-08-30.** Closed as debt 56; see the debt register entry and
> `tests/test_branch_enforce_examinations.py` (14 tests). Detail below is kept as the
> record of what was wrong.

Every other tenant-scoped domain filters by campus through `core/branch_scope`.
Examinations references it zero times, so a branch-restricted sub-admin — a campus head —
is not restricted at all here. They can list, schedule, enter marks for, and publish
examinations belonging to every other campus in the trust.

```
grep "branch_scope|assert_class_allowed|filter_*_by_branch" modules/examinations/  → 0 hits
same grep across modules/                                                          → 31 files
ExamPaper.class_id → classes.id                                       models.py:438-440
core/branch_scope.py:261  filter_by_class_ids(query, class_fk_column)    ← drops straight in
```

The fix is cheap, which is the frustrating part: `ExamPaper` already carries a `class_id`
FK, so the existing `filter_by_class_ids` helper applies directly. This is the exact class
of bug the teachers/transport/hostel branch-scoping pass was built to close, and
examinations shipped after it without inheriting it. **Not in the debt register.**

**What the fix covers.** Anchored on ADR-016 — an examination declares no campus, its
papers carry the section, the section carries the campus. Scoped: the examination list and
its count, the papers a screen shows, the sections sitting, the marking register, recording
marks, adding papers (and creating with papers), the correction queue and pending
corrections, results and the result board, published results, marksheets, and both revision
paths. Two new helpers in `core/branch_scope.py`: `filter_examinations_by_branch` and
`filter_by_exam_mark_ids`, plus `assert_exam_paper_allowed`.

**Two things the fix got right only on the second attempt**, both worth knowing before
touching this again:

1. *A list filters; an operation on one named thing refuses.* Putting the assert inside
   `_paper_of` made `correction_queue` **raise** when the queue held another campus's
   request rather than simply not showing it. Queues are scoped at the query now.
2. *`papers_for` must stay unscoped.* It is the calculation's input, not a screen's —
   scoping it would make a student's frozen result depend on who pressed calculate. The
   screen's read is `papers_with_labels`, and that is what carries the filter.

**Deliberately still open:** `get_examination` is unscoped, so a campus head who knows an
id can read another campus's examination *header* (no papers, sections, marks or results
come with it). And `calculate_results` / `publish_results` act on the whole cohort by
design, so a campus head holding `examination.publish` publishes trust-wide — a business
question about how far that authority should reach, not a leak.

#### EX-A2 — Grading band bounds are coarser than the percentages matched against them *(debt register 53)*

Bands store `Numeric(6,2)` while the percentage they are matched against is
`Numeric(6,3)`. A school writing the ordinary "up to 59.999" upper bound gets **60.00**
stored, which silently overlaps the band starting at 60. The overlap resolves by lowest
`sequence`, so a student sitting exactly on the boundary quietly takes the higher grade —
no error, and no screen that would reveal it.

```
models.py:239-240  min_value / max_value   Numeric(6,2)
models.py:635      percentage              Numeric(6,3)
debt 53 — gaps, overlaps and duplicate boundaries are all storable;
          a shipped test fixture already contains a gap (33-80.99 uncovered)
```

Only `min_value <= max_value` is enforced. Nothing validates coverage, and there is no
configuration screen that would show a school its own gap.

#### EX-A3 — Setting a paper weight bricks result computation, and the column accepts NaN *(debt register 52)*

`paper.weight` is the one paper column `add_papers` accepts with **no validation
whatsoever** — no numeric, range or finite check, unlike `max_marks` and `pass_marks`.
Postgres `numeric` will store `NaN` in it. Separately, any non-null weight causes result
calculation to refuse outright with `WEIGHTED_CALCULATION_UNSUPPORTED`, because weighted
aggregation was never built.

```
models.py:459               weight = Numeric(6,2), nullable   ← unvalidated
results_service.py:240-245  any non-null weight → hard refusal
```

The refusal is deliberate and defensible. The unvalidated column that leads a school into
it is not: a school fills in weights because the field is there, then discovers it cannot
compute results at all.

### High

#### EX-B1 — An exam window reserves nothing; paper dates are never checked against it

Paper dates validate against the academic cycle's range instead of the linked window's.
The calendar UI promises "these dates will be reserved for exams"; the examination module
never reads those dates. `services.py:206-221`

#### EX-B2 — Deleting a calendar exam window silently unlinks its examinations

`delete_exam_window` has no dependency guard and the FK is `SET NULL`. The examination
survives with its calendar context erased, and nothing tells anyone. The notification text
also reads "Examination removed" when what was removed is a *window* — misleading to
whoever receives it. `calendar/services.py:413-426` · `models.py:334-339`

#### EX-B3 — Window class-applicability is ignored

`applicable_class_ids` lets a school say a window applies only to certain sections. The
examinations module never reads it, so the constraint has no effect on the thing it exists
to constrain.

#### EX-B4 — Two disjoint exam-type vocabularies, one of them hardcoded

The calendar's `exam_type` is a hardcoded enum of six values; the examination's is a
tenant-configurable lookup table. Beyond the inconsistency, the hardcoded half violates
the project's own "configuration, not forks" commitment — a board with different
examination nomenclature needs a code change.

```
calendar/models.py:199                exam_type = String(20) default "other"
admin-web/…/calendarOptions.ts:42-49  unit_test|mid_term|final|pre_board|board|other
```

#### EX-B5 — The calendar link is unreachable from the UI

The backend implements and validates `exam_window_id`; the create wizard never offers it.
The capability exists and no user can reach it, so the column is `NULL` in practice and
the whole coupling is currently theoretical.

#### EX-B6 — No cache invalidation across the calendar/examination boundary

`academicCalendarKeys` and `examinationsKeys` never invalidate each other. Latent while
EX-B5 holds, but it becomes a live staleness bug the moment the window link is wired up:
editing or deleting a window leaves examination screens showing the old one.

#### EX-B7 — How many students went unmarked is unrecoverable once a paper locks *(debt register 51)*

A paper closed with 33 of 35 students marked reports 33, and `marking_progress` returns
`outstanding = None` rather than a zero. The two missing students are genuinely not stored
anywhere. The reasoning is sound — the alternative was inventing them from today's class —
but a school auditing its own marking has no way to discover the gap after the fact.

### Medium

#### EX-C1 — The top-level docs still say this module does not exist

`.claude/CLAUDE.md` lists "exams/results/report cards do not exist yet" as a known gap,
and the v2 roadmap says "Examination is deliberately outside the top 10". Both were true
when written and are now wrong. `.claude/memory/v2-refactor.md` stops at Phase 62 — **no
entry records that this module was designed, built or shipped**, despite that file's own
rule requiring it be kept current.

This is why a fresh session reads the canon and concludes the module doesn't exist. It is
the most likely cause of someone re-planning or duplicating work already done.

#### EX-C2 — ADR-019 is cited in code but was never written *(debt register 54)*

`modules/examinations/models.py:162` justifies tenant-wide grading scope with "(ADR-019)".
The ADR directory holds 015, 016, 017, 018 and 020 — there is no 019. The decision was
real (recorded in the discovery audit as D3) but never became a document, so the code
cites a rule a reader cannot check.

#### EX-C3 — No AssessmentScheme; schools re-enter the same paper shape every time *(debt register 48)*

Theory 80 + Practical 20 is two papers, correctly. But a school repeating that shape
across Unit Test 1, Half Yearly and Final re-enters it each time. Deliberately deferred
pending a real school expressing reuse rules; worth revisiting before onboarding a trust
with many programmes.

#### EX-C4 — Report card versus marksheet is undecided *(debt register 49)*

Only the per-examination marksheet exists. An annual report card aggregating unit tests +
half yearly + final is a different artefact that would *read* results rather than replace
them. Nothing prevents it; nothing implements it. This blocks the student/parent surface
below.

#### EX-C5 — Students and parents have no way to see a result

Zero examination code in the Expo `client` and zero in `panel`. admin-web can publish a
result that no parent can view. This is documented as intentional (EX-14, "not built yet")
and gated behind the report-card decision above — so it is a scope boundary rather than an
oversight, but it does mean publication currently ends at the admin screen.

#### EX-C6 — The whole module landed as two commits and reached main in 23 minutes

Migrations 107–119, all source, four ADRs, the module doc and the discovery audit arrived
in two commits on 2026-08-25 and merged to `main` the same night:

```
363c756  2026-08-25 00:16  feat(examinations): the examination module, on the academic foundation it needs
c268e3a  2026-08-25 00:36  docs(examinations): the module doc the canon was owed
2e269e3  2026-08-25 00:39  Merge: merge(develop): v2 academic foundation, the examination module, and fixes
```

The discovery audit is dated 2026-08-12 *inside its text* but is bundled into the same
commit as the finished implementation, so git shows no independent pre-implementation
review gate. The single-commit choice was argued explicitly in the commit message and is
defensible for a dependency chain; the absence of a separable review point is what makes a
defect like EX-A1 easy to miss.

Related and already fixed: the stale `examinations: true` key that migration 043 wrote
years earlier defeated `DEFAULT_OFF_FEATURES` and switched the module on in prod on ship
day. Migration `120_a_retired_feature_key_is_not_an_answer` deletes the key.

---

## 5. Recommended order

Only the first item is blocking.

1. **Branch-scope the module.** Apply `filter_by_class_ids` on every paper/mark/result
   query and `assert_class_allowed` on every write. `ExamPaper.class_id` makes this
   mechanical. Add the debt-register entry it never got.
2. **Close the grading-band boundary.** Widen band bounds to `Numeric(6,3)` to match
   percentage, then validate coverage on write — refuse overlaps, warn on gaps. Do not
   silently repair existing rows.
3. **Validate or remove `paper.weight`.** Until weighted aggregation is designed, reject a
   non-null weight at `add_papers` rather than accepting it and refusing later. That turns
   a dead end into an honest error.
4. **Decide the calendar contract explicitly.** Either the window governs (enforce date
   containment and class applicability, guard deletion, unify the type vocabulary, wire
   the wizard) or it is purely advisory — and then say so in the UI, because "these dates
   will be reserved" currently promises something the system does not do.
5. **Resolve the year-versus-cycle mismatch**, since option A above depends on it.
6. **Update the canon.** Correct `CLAUDE.md`, add the missing phase entry to
   `.claude/memory/v2-refactor.md`, and write ADR-019 from the discovery audit's D3.
   Cheap, and it stops the next session re-deriving all of this.

---

## Sources

- `server/modules/examinations/` — `models.py`, `services.py`, `results_service.py`,
  `marks_service.py`, `resolvers.py`, `marks_import_routes.py`
- `server/docs/modules/examinations.md`
- `server/docs/architecture/adr/ADR-016`, `-017`, `-018`, `-020`
- `server/docs/architecture/debt-register.md` (items 48, 49, 51, 52, 53, 54)
- `server/docs/architecture/reviews/2026-08-12-examination-discovery-audit.md`
- `server/modules/academics/calendar/` — `models.py`, `services.py`, `routes.py`
- `admin-web/src/{types,hooks,services,components,app}` — examination + calendar surfaces
- `core/feature_flags.py`, `core/branch_scope.py`, `modules/rbac/catalog.py`

Test run: `tests/test_examination_{domain,services,feature_flag}.py` → **81 passed**.
