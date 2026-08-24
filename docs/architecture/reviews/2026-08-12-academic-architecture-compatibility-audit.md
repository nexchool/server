# Academic architecture — final pre-implementation compatibility audit

**Date:** 2026-08-12 · **Status:** validation of a proposed architecture. Discovery only — no code,
migrations, ADRs, Jira or repository changes.
**Predecessors:** `2026-08-12-examination-discovery-audit.md`, `2026-08-academic-domain-and-temporal-model-audit.md`,
`2026-08-09-stabilization-audit.md`. Not repeated here.
**Brief:** try to break the proposed target architecture.

**Labels:** **FACT** = read from code or queried from the live database · **INFERENCE** · **RECOMMENDATION** ·
**UNKNOWN**.

---

## Headline: the proposal survives, with one correction and two additions

I tried to break it. Three things came out of the attempt:

1. **The correction — the blocker is not the enrollment index; it is `students.class_id`.** Re-scoping
   `uq_sce_current_per_student_year` from year to cycle is *not* what unblocks Scenarios F/G/J. **FACT:**
   `student_class_enrollments` has only **~8 non-test consumers**, while `students.class_id` — a **singular
   column** — has **55 server references** and **694 in admin-web + Expo**. Every read path for "which class
   is this student in" goes through the cache, and the cache can hold exactly one class. The proposal as
   written would break `tests/test_caches_follow_their_owner.py::test_no_student_anywhere_disagrees_with_their_enrollment`
   the first time a student held two current enrollments. **The smaller, safer change is an enrollment
   *purpose*, with the cache mirroring the primary enrollment only.** Details in Part 2.

2. **The first addition — a P0 nobody has caught: there is no student↔subject link.** **FACT:** zero tables
   match `student_subject`, `subject_enroll`, `elective_choice`; there is **no function in
   `modules/students/` that returns a student's subjects**; `class_subjects.is_elective_bucket` marks *that a
   slot is elective* but **nothing records which elective each student chose**. A student's subjects are
   resolvable only as "whatever their class offers". Grade 11 Science where some take Biology and others
   Computer Science is **not representable**, and Examination cannot answer "who sits the Physics paper".
   This is larger than Stream, because it bites *within* a single Science section. Details in Part 10.

3. **The second addition — reject applicability columns on AcademicCycle.** The brief asked whether
   applicability should be declared on the Cycle or derived through Classes. Declaring it creates precisely
   the two-owner contradiction the brief names. **Derive it.** Details in Part 3.

**One correction to my own previous audit, in the school's favour.** I flagged fee/billable double-counting
as a P1 risk of multi-enrollment. **FACT — it is not a risk.** `modules/subscription/usage.py:53` counts
`Student` rows filtered on `student_status`; it never touches enrollments. A second enrollment cannot
double-count. `modules/platform/services.py` imports the same single definition. **SAFE.**

---

## Part 1 — Hidden assumptions

Traced model → service → route/resolver → serializer → client → test. Answers are **FACT** unless marked.

| # | Assumption | Holds? | Evidence | Priority |
|---|---|---|---|---|
| 1 | One academic year per tenant | No — 5 coexist | 18 tables carry `academic_year_id` | — |
| 2 | One *current* academic year | **Yes, twice, inconsistently** | `AcademicSettings` `UNIQUE(tenant_id)`; and `dashboard/service.py:46` (`is_active` + latest). **All 5 live years are `is_active=true`** | P1 |
| 3 | One academic cycle | **Yes** — no cycle concept exists | — | P1 |
| 4 | One enrollment per student per year | **Yes** | `uq_sce_current_per_student_year` | P1 |
| 5 | **One class per student** | **Yes — structurally** | `students.class_id` singular; **55 server + 694 client refs** | **P0** |
| 6 | One programme per student | Yes, via the class | — | P1 |
| 7 | One stream or none | **Yes** | `classes.stream` free text, **0 of 316 live rows populated** | **P0** |
| 8 | Stream is a fixed set | **Yes — hardcoded** | `VALID_STREAMS` frozenset, `school_setup/bulk_generator_service.py:32` | **P0** |
| 9 | One calendar per organization | **Yes** | `academic_calendars` `UNIQUE(tenant_id, academic_year_id)` | P1 |
| 10 | One set of terms per organization | **Yes** | `academic_terms` keyed `(tenant, year, name)` — no programme/grade/campus | **P0** |
| 11 | One grading system | N/A — none exists | 0 hits for `GradingScale`; `subjects.default_grading_scale_id` is a ghost column | **P0** (build correctly) |
| 12 | One assessment pattern | N/A — none exists | — | **P0** (build correctly) |
| 13 | One result per student | **Yes** | `students.academic_result` `String(20)`, overwritten, no year | **P0** (decision) |
| 14 | One roll number per student | **Yes** | `students.roll_number`, lifetime | **P0** |
| 15 | One campus | No | `Class.school_unit_id`; `core/branch_scope.py` | — |
| 16 | One timetable context | No | `TimetableVersion` per class | — |
| 17 | One fee structure per student/year | No | `fee_structure_classes` binds to classes | P1 |
| 18 | One attendance context | No — **correctly modelled** | `attendance_sessions` unique `(tenant, class_id, session_date)` | — |
| 19 | One promotion path | Yes | `promoted_from_enrollment_id` chain | P2 |
| 20 | One academic period | Yes (see #10) | — | **P0** |
| 21 | One subject set for a grade | Yes — via class | `class_subjects` | P1 |
| 22 | One subject set for (programme, grade) | **Yes** | `subject_contexts` has no `stream_id` | **P0** |
| 23 | One academic start/end boundary | **Yes** | Only `AcademicYear` carries dates that anything reads | P1 |
| 24 | **April–March hardcoded** | **Yes** | `teachers/constraint_services.py:295` — never reads `academic_years`; 7 call sites | **P0** |
| 25 | `is_active` means "current" | **Broken** | No uniqueness; 5/5 live rows true | P1 |
| 26 | `current_academic_year_id` is globally current | **Yes** | `AcademicSettings` docstring: *"One row per tenant"* | P1 |
| 27 | Academic year ≡ operating dates | **Yes** | `classes.start_date/end_date` exist but are **0-populated and never read** | P1 |
| 28 | **Class ≡ a student's whole academic experience** | **Yes** | `students.class_id` + **no student↔subject link** | **P0** |

**Two caches, not one.** `students` carries `class_id`, `academic_year_id` **and** a deprecated
`academic_year` `String(20)`. `test_caches_follow_their_owner.py` guards **only `class_id`**.

---

## Part 2 — StudentClassEnrollment blast radius

**FACT — the full non-test consumer set is eight files:**

| Consumer | Uses | Verdict |
|---|---|---|
| `students/class_enrollment_service.py` | the owner — writes `is_current`, `class_id`, syncs the cache | **NEEDS CHANGE** — must learn "primary vs additional" |
| `students/promotion_service.py` | `is_current`, `academic_year_id`, `promoted_from_enrollment_id` | **NEEDS CHANGE** — must promote only primary enrollments |
| `students/lifecycle_service.py` (via the primitive) | closes placement | **SAFE** |
| `classes/section_merge.py:137` | students in a class by `is_current` | **SAFE** — class-scoped, purpose-agnostic |
| `transport/services_rollover.py:110` | `is_current` in the target year = "promoted, not graduated" | **NEEDS CHANGE** — a coaching enrollment would read as promoted |
| `academics/academic_year/services.py:73` | counts enrollments to guard year deletion | **SAFE** — a count |
| `scripts/reconcile_student_class_enrollments.py` | repairs cache vs enrollment | **NEEDS CHANGE** — must reconcile against primary |
| `scripts/seed_academic_dummy_data.py`, `seed_demo_data.py` | create rows | **NEEDS CHANGE** — set purpose |

**FACT — the real dependency is elsewhere.** `students.class_id`: **55 server references** across student
list/search/filter/sort, class student counts, announcements audience (`announcements/services.py:208`),
student leaves, global search, dashboard, `schedule/services.py:236` (a student's timetable today),
transport, bulk import, promotion. **694** `class_id`/`classId` references in admin-web + Expo.

**FACT — one test sweeps the whole table:**
`test_caches_follow_their_owner.py:175::test_no_student_anywhere_disagrees_with_their_enrollment` asserts
*every* student's `class_id` equals their current enrollment's. Two current enrollments break it.

**Classification of the domains the brief named:**

| Domain | Reads | Verdict |
|---|---|---|
| **Fees / billable count** | `Student.student_status` only (`subscription/usage.py:53`) | **SAFE — cannot double-count** |
| Promotion | enrollment chain | **NEEDS CHANGE** (primary only) |
| Graduation | `student_lifecycle_events` | **SAFE** |
| Attendance | `(class_id, session_date)` | **SAFE** — naturally separates offerings |
| Student profile / list / search | `students.class_id` | **SAFE** if the cache stays primary-only |
| Permissions | `core/branch_scope.py` via class | **SAFE** |
| Notifications | `Student.class_id.in_(class_ids)` | **SAFE** if primary-only; **UNKNOWN** whether a coaching audience is ever wanted |
| Transport | rollover reads `is_current` | **NEEDS CHANGE** |
| Hostel | `hostel_allocations.academic_year_id` | **SAFE** |
| Reports / dashboards | `students.class_id` | **SAFE** if primary-only |
| Imports / exports | `students.class_id` | **SAFE** |
| GraphQL / REST | `Student.currentClass`, `class_id` | **SAFE** if primary-only |
| Mobile | `class_id` in payloads | **SAFE** if primary-only |

### RECOMMENDATION — do not re-scope the index generically. Add purpose.

```
student_class_enrollments
  + enrollment_purpose : primary | supplementary        (NOT NULL, default 'primary')

  uq_sce_current_per_student_year
    → UNIQUE (tenant, student, academic_year)
        WHERE is_current AND enrollment_purpose = 'primary'
```

**Why this is smaller and safer than cycle-scoping:**

- All existing rows backfill to `primary`. The index is **behaviour-identical** on day one.
- `students.class_id` keeps meaning **the student's academic class** — which is what a school means by "his
  class". JEE coaching is not a child's class. **All 55 + 694 references keep working, unchanged.**
- The cache-sweep test needs one clause (`purpose='primary'`), not a rewrite.
- It does **not** require `AcademicCycle` to exist. **Scenarios F, G and J become representable without the
  cycle work** — which decouples the two changes and lets coaching ship before multi-cycle.
- Only 4 of the 8 consumers change, each in one predicate.

**Cycle-scoping the index is still correct eventually** (a student re-enrolled in a second *main* cycle in
one year), but it is P1 and it is not what unblocks the coaching scenarios.

**UNKNOWN — product decision.** Does a supplementary enrollment appear on a transcript and produce results,
or is it participation only? If the former, `enrollment_purpose` may need a third value
(`short_course` vs `coaching` vs `remedial`). I recommend starting with two and widening on evidence.

---

## Part 3 — AcademicCycle placement: reject applicability columns

The brief asked whether the Cycle should declare `programme_id` / `school_unit_id` / `grade_from` /
`grade_to` / `stream_id`, or whether applicability should be derived through its Classes.

**RECOMMENDATION — derive it. The Cycle carries only `name`, `start_date`, `end_date`, `cycle_kind`.**

This reverses the applicability columns I proposed in the previous audit. The brief's own example is the
proof:

> Cycle says programme = CBSE, grades 9–12. Class says programme = GSEB, grade 8. Both claim the same cycle.

With declared applicability that contradiction is **representable**, so it will eventually be *represented*,
and then two sources disagree about which classes belong to a cycle. Enforcing consistency means validating
every class write against its cycle's declared scope — a second owner plus a constraint to keep them in step.
That is the exact shape ADR-012 and ADR-013 both rejected.

**FACT — the Class already carries every dimension authoritatively**: `programme_id`, `school_unit_id`,
`grade_id`, `medium_id`, `department_id`, `stream`, `academic_year_id`, and a structural unique constraint
over them. Adding `academic_cycle_id` makes the cycle **one more dimension of the Class**, exactly like
programme and campus. "Which classes are in the GSEB cycle" is then a query, not a claim — and it cannot
disagree with itself.

**Worked check — Scenario B.** GSEB June→April, CBSE April→March:

```
AcademicYear "2026-27"
  ├─ Cycle "GSEB Main"  2026-06-01 → 2027-04-30   kind=main
  │    ← Class(GSEB, Grade 1, A, campus=City, cycle=GSEB Main)
  └─ Cycle "CBSE Main"  2026-04-01 → 2027-03-31   kind=main
       ← Class(CBSE, Grade 9, A, campus=City, cycle=CBSE Main)
```

Applicability is evident, unambiguous, and needs no columns. A misfiled class is an operator error visible on
one screen, not a schema contradiction.

**Cost of deriving, stated honestly:** you cannot ask "which programme is this cycle for" before any class
exists, so the cycle picker on the class form cannot pre-filter by programme. **INFERENCE — acceptable**: a
school has 2–4 cycles, and the list is short enough to choose from by name. Add a *derived, non-authoritative*
summary ("used by: GSEB, Grades 1–8") on the cycle screen if operators want it.

**Scenario A stays simple.** One cycle is auto-created with each academic year (same name, same dates). The
class form defaults to it and **hides the field when the year has exactly one cycle**. A Nursery–10 school
never sees the word "cycle".

---

## Part 4 — AcademicPeriod / Term

**FACT.** `academic_terms`: `(tenant, academic_year_id, name)` unique, plus `code`, `sequence`,
`start_date`, `end_date`, `is_active`, soft delete. **2 live rows.** `class_subjects.academic_term_id`
already references it (a subject offered only in one term).

**RECOMMENDATION — Period belongs to the Cycle, and nothing else changes.**

Answers to the brief's questions:

| Question | Answer |
|---|---|
| Period belongs directly to Cycle? | **Yes.** A term is a subdivision of a dated operating period. Re-parent `academic_year_id` → `academic_cycle_id` |
| Can an assessment occur outside a Period? | **Yes — keep the reference nullable.** A surprise unit test, a re-exam and a board exam scheduled by the board all sit outside the school's terms |
| Multiple assessments per Period? | **Yes** — that is the normal case |
| Can one Period span multiple grades? | **Yes** — and it should. Cycle-scoping already gives per-programme and per-grade-range variation *through the cycle* |
| Different grades, different periods? | **Yes, if they are in different cycles.** If Grades 1–8 and 9–12 genuinely have different terms, that is Scenario C — different cycles |
| Different streams, different periods? | **No, and do not build it.** No scenario given requires Science and Commerce to have different *term dates*; they need different *assessments*, which is the scheme's job |
| Can a school have no terms? | **Yes** — 2 live rows across 5 years proves it is already optional |

**Do not create a separate "AssessmentPeriod" entity.** Unit Test Period, Preliminary Period and Board Exam
Period are all *dated subdivisions of a cycle* — the same thing `academic_terms` already is. Adding a second
period-shaped table would be two owners of "a named date range inside a cycle". If a school wants a
"Preliminary" period, it creates a term named Preliminary. `exam_windows` remains the *calendar reservation*
and is not a period.

---

## Part 5 — Stream

**FACT.** `classes.stream` — free text; `VALID_STREAMS = frozenset(("Science","Commerce","Arts","Vocational"))`
hardcoded at `school_setup/bulk_generator_service.py:32`; **NOT in
`uq_classes_unit_programme_grade_section_year`**, so Grade 11 Sci-A and Com-A collide; **0 of 316 live rows
populated**, so the path has never run in production. `subject_contexts` has **no** `stream_id`.

**RECOMMENDATION — a tenant-owned `streams` table, referenced by Class and SubjectContext.**

| Question | Answer | Why |
|---|---|---|
| Tenant-owned? | **Yes** | A school invents "Integrated Science"; a platform-global list would need a deploy per school — the "configuration, not forks" rule |
| Vocabulary configurable? | **Yes** — this is the whole point | Replaces `VALID_STREAMS` |
| Reusable across programmes? | **Yes** — one `Science` row usable by GSEB and CBSE | Science is Science; per-programme copies would multiply rows and split reports |
| Globally reusable (platform-seeded)? | **Seed the common four per tenant**, editable | Scenario A never touches them; Scenario E renames or adds |
| Belongs to Grade? | **No** | A grade does not have streams; a *class* is in a stream. Grades 1–10 have none |
| Belongs to Class? | **Yes** — `classes.stream_id` | It is a dimension of the section, like medium and programme |
| SubjectContext references Stream? | **Yes, nullable** | NULL = applies to every stream at that (programme, grade). This is what makes Science ≠ Commerce subjects |
| In the Class unique constraint? | **Yes — required** | Otherwise Sci-A and Com-A collide. This is a correctness fix, not a preference |
| Affects promotion? | **No** | Promotion moves grade; stream is chosen at Grade 11 entry |
| Affects grading? | **Indirectly** — through the scheme's attachment tuple | |
| Affects examination? | **Yes, decisively** | It selects the subject set, hence the papers |
| Affects fees? | **Possibly** — `fee_structure_classes` binds to classes, so already expressible | No change needed |

**Stream change mid-year (Scenario I) — FACT, and a real gap.** `lifecycle_service.transfer_section` refuses
only `CLASS_NOT_FOUND`, `SAME_CLASS` and `WRONG_YEAR` — it does **not** check grade, programme or stream. So
Science-A → Commerce-A already "works". **But** since Phase 34 a same-year move **modifies the current
enrollment in place** rather than closing and reopening it. The result: the enrollment record shows the
student as always having been in Commerce. Their Science membership survives only as a `SectionTransferred`
lifecycle event.

**INFERENCE — acceptable for section moves, wrong for stream moves.** Moving 10-A → 10-B is a room change.
Moving Science → Commerce changes what the child studies and is examined in; marks already recorded against
Physics must remain attributable to a period when they were a Science student.

**RECOMMENDATION (P1, not P0):** when the destination class differs in **stream, grade or programme**, close
the current enrollment and open a new one — i.e. treat it as the promotion path does, not the room-change
path. Same primitive, one added condition. Examination is unaffected in MVP because marks bind to
`(exam_paper, student)` and the paper carries its own class.

---

## Part 6 — Grade

**FACT** (re-confirmed): `grades` is flat and tenant-wide; `name` unique per tenant among active rows;
`sequence` orders; 2 FKs in (`classes.grade_id`, `subject_contexts.grade_id`); **no Expo file references it**.

**RECOMMENDATION — Option A: one canonical catalogue + programme display aliases. And it is P1, not P0.**

Why not B (programme-scoped grades): it duplicates every grade per programme, and the single `sequence` —
which makes promotion order, grade-wise reporting and class-list sorting work organization-wide — would
fragment. The stabilization audit already recorded that single sequence as the flat model's one genuine
virtue. Do not trade it away for a display problem.

Why A is enough:

```
grades:  id, name (canonical, e.g. "Grade 10"), sequence
grade_programme_aliases:  grade_id, programme_id, display_name
    (GSEB → "Std 10", CBSE → "Grade 10", ICSE → "Class X")
```

Nursery / LKG / UKG / Grade 1–12 are all just rows with sequences. Grade *span* per programme is then
derivable from which aliases exist, or from an explicit `is_offered` flag if a school needs it.

**Why P1 and not P0:** Examination keys on `(programme, grade, stream)`. With a shared catalogue that tuple
still resolves **correctly and unambiguously** — GSEB Grade 10 and CBSE Grade 10 are distinct tuples sharing
a grade row. The problem is **cosmetic** (a GSEB report card saying "Grade 10" instead of "Std 10"), and an
alias table is purely additive and can land after Examination without touching exam data.

**Do not build this before Examination.**

---

## Part 7 — Medium

**FACT.** `mediums` table has **0 rows**. `classes.medium_id` is NULL on all 316 classes. Production encodes
medium into programme *names*: `"GSEB English Medium"` and `"GSEB Gujarati Medium"` are two rows in
`academic_programmes`. **`subject_contexts` already has `medium_id` and `variant_of_context_id`** — the
correct model exists there and is unused for this.

**INFERENCE — why this happened.** `medium_id` is **not** in the class unique constraint. Two Grade 1 A
sections differing only by medium would violate it. Splitting the programme was the only way to open parallel
English and Gujarati sections, and it works. This is a workaround that became the convention.

**RECOMMENDATION — DEFER.**

Not KEEP (the column is dead weight), not RETIRE (it may be right later), not REFACTOR now:

- Programme identity is **inside the class unique constraint**. Splitting `"GSEB English Medium"` into
  (programme=GSEB, medium=English) rewrites `programme_id` on every class, every `subject_context`, every
  fee structure bound to those classes — a high-blast-radius change **for no new capability**, since parallel
  mediums already work.
- Examination does not care: it keys on `(programme, grade, stream)`, and today's programme *is* the medium
  distinction. Papers and results come out correct either way.
- **Conceptually medium is independent of board** (CBSE-English and CBSE-Hindi share a syllabus and differ in
  language of instruction), so the current model is theoretically wrong — but it is wrong in a way that
  costs duplicated programme rows, not incorrect results.

**Revisit when** a school needs one *subject* taught in two mediums within one section — which is exactly
what `subject_contexts.medium_id` + `variant_of_context_id` were built for. Until then, **do not touch it.**

---

## Part 8 — AssessmentScheme

Stress-tested against all 14 cases in the brief.

**RECOMMENDATION — `AssessmentScheme → AssessmentComponent`, attached to
`(programme, grade, stream, cycle)`. Two tables. Not five.**

```
assessment_schemes
  programme_id, grade_id, stream_id (nullable = all streams), academic_cycle_id
  name, grading_scheme_id, is_active

assessment_components
  scheme_id, name, kind, sequence
  max_marks, weight
  academic_term_id (nullable — see Part 4)
  counts_toward_promotion : bool
  is_optional : bool
```

| Case | Representation |
|---|---|
| Term 1 + Term 2 | 2 components |
| Unit tests + Semester + Preliminary + Final | 4 components |
| Weekly subject tests (Scenario D) | components with `kind='unit_test'`, one per week or one aggregate |
| Continuous assessment | 5 components, weighted |
| Practical + Theory | 2 components on the same subject |
| Project + Written | 2 components |
| Weighted components | `weight` |
| Optional components | `is_optional` |
| Not counting toward promotion | `counts_toward_promotion=false` |
| Different by grade | different `grade_id` |
| Different by stream | different `stream_id` |
| Different by programme | different `programme_id` |
| Different by cycle | different `academic_cycle_id` |
| Internal + external marks | 2 components |

**Why `stream_id` is in the tuple:** Scenario E — Science has practicals, Commerce does not. Without stream
they share one scheme.

**Why `academic_cycle_id` is in the tuple — and this is the part I pressure-tested against the brief's "do
not add cycle merely because it exists":**

The reason is **not** history. History is protected by snapshotting the computed result (already required for
report-card immutability). The reason is **forward planning**: a school defines next year's pattern while
this year's is still live and still producing results. Without a temporal dimension the same
`(programme, grade, stream)` cannot hold two schemes at once, so editing next year's pattern would silently
change this year's in-flight calculations. There is precedent for carrying schemes forward:
`academics/services/academic_structure_rollover.py` and `holiday_rollover.py` already copy structure between
years. **Schemes roll over the same way.**

**Rejected attachment points:**
- **Class** — a scheme per section means 20 identical rows per grade and drift the moment one is edited.
- **Academic period** — a period holds *when*, a scheme holds *what and how much*. Components reference a
  period; the scheme does not live in one.
- **Subject** — see Part 9.

**Explicitly do not build:** `AcademicPattern`, `AssessmentPolicy`, `AssessmentType`, `AssessmentPeriod`,
`AssessmentWeight` as separate tables. `kind` and `weight` are **columns**; a period is `academic_terms`.
Naming each paragraph of a document as a table is the error ADR-012 and ADR-013 both record.

---

## Part 9 — Grading

**FACT.** No grading exists. `subjects.default_grading_scale_id` (migration 023) points at a
`grading_scales` table that was never created and is read by **nothing in any repo** — a ghost column, and a
standing warning about adding a hook before a need.

**RECOMMENDATION — two tables, attached to the AssessmentScheme, with the outcome snapshotted onto the result.**

```
grading_schemes   tenant, name, scheme_type: percentage | letter | band | grade_point | pass_fail
grading_bands     scheme_id, label, min_value, max_value, grade_point, is_pass, sequence
```

| Requirement | Covered by |
|---|---|
| Percentage | `scheme_type='percentage'`, no bands needed |
| Pass/Fail | two bands with `is_pass` |
| Letter grades / A1-A2-B1 | bands with labels |
| Grade bands | bands |
| Grade points | `grade_point` |
| **CGPA / GPA** | **derived** from grade points across subjects — a computation, not a table |
| Board-specific | a scheme per board, selected by the assessment scheme's `programme_id` |
| Weighted assessments | `assessment_components.weight` — grading is applied after weighting |

**Attachment point — `AssessmentScheme.grading_scheme_id`. Reasoning:**

- **Not `AssessmentComponent`** — practical-vs-theory on different scales is real but rare; a nullable
  component-level override can be added later **without migration of existing data**. Do not build it now.
- **Not `SubjectContext`** — this is precisely what `default_grading_scale_id` attempted. Per-subject grading
  is the configuration fewest schools use and the one most likely to be left inconsistent.
- **Not `Examination`** — an examination is an event; how marks become grades is a policy of the pattern, and
  two examinations under one scheme must grade identically.
- **Not `Result`** — but the **computed grade must be stored on the result** as a snapshot, so a later
  scheme edit cannot rewrite a published report card.

**Guard rail:** grading is a **platform capability**, not an Examination feature. It must live outside
`modules/examination/` so attendance grades, co-scholastic grades and conduct grades can use it later.

---

## Part 10 — New real-world scenarios that materially affect architecture

I investigated the brief's list plus the domain. Most are already representable or are product scope rather
than architecture. **Four materially affect the architecture. One is a P0.**

### 🔴 N1 — Student-level subject selection does not exist (**P0, new**)

**FACT.** No `student_subjects` / `subject_enrollments` / `elective_choice` table. **No function in
`modules/students/` returns a student's subjects.** `class_subjects.is_elective_bucket` marks a slot as
elective; **nothing records which elective each student picked.**

**Consequence.** A student's subjects = their class's subjects, for everyone in the class. So:

- Grade 11 Science where some take Biology and others Computer Science: **not representable**.
- "Who sits the Physics paper" → "everyone in 11-Sci-A", including the four who dropped it.
- Marks entry lists every student for every subject; results total subjects a child never took;
  percentages are wrong.

**This is bigger than Stream** because it bites *within* one section, and Stream does not fix it.

**Does an existing entity cover it?** No. `class_subjects` is class↔subject. `student_class_enrollments` is
student↔class. **The student↔subject edge is genuinely absent**, and it is the join Examination needs.

**RECOMMENDATION — the smallest form is a subject-election row, not a full enrollment:**

```
student_subject_elections
  student_class_enrollment_id, class_subject_id, status: taking | dropped | exempted
```

Only rows for **elective** offerings need to exist; mandatory subjects are implied by the class. That keeps
Scenario A at zero rows (a Nursery–10 school with no electives writes nothing) while making Grade 11 correct.
**INFERENCE:** deriving the exam cohort as *"enrolled in the class, minus explicit non-takers, plus explicit
takers of elective slots"* keeps the simple case free.

**P0 for Examination.** Without it, exam cohorts are wrong for every school with electives, and the wrongness
is silent.

### 🟠 N2 — Repeat year and the promotion chain (**P1**)

**FACT.** `promoted_from_enrollment_id` chains enrollments; promotion writes `enrollment_status="promoted"`
**even for students it classified as repeating** (debt 14d). A repeater gets a new enrollment in the same
grade with a status saying they advanced. **Affects transcripts and "how many years in Grade 9".**

### 🟠 N3 — Supplementary / compartment / improvement exams (**P1**)

**FACT.** Nothing exists. **RECOMMENDATION:** a second `Examination` linked to the first by
`supersedes_examination_id`, with results that override per subject. **No new entity beyond a nullable FK** —
but the *result* model must anticipate "this subject's outcome came from a later attempt". Decide the column
now; build the flow later.

### 🟠 N4 — Cross-section and additional subjects (**P2**)

A student taking a subject with another section (a common Grade 11 arrangement) has no representation —
`class_subjects` binds a subject to one class. N1's election table covers *dropping*; taking a subject
**elsewhere** additionally needs the election to reference a `class_subject` outside the student's own class.
**RECOMMENDATION:** allow that FK to point anywhere in the tenant, and let branch scope validate. Costs
nothing now, unblocks the case later.

### Assessed and deliberately excluded (representable, or not architecture)

| Scenario | Verdict |
|---|---|
| Theory + practical, internal + external, moderation/grace | **AssessmentComponent** — configuration |
| Re-evaluation | Workflow on results (correction pattern exists in attendance) — P2 |
| Joining / leaving mid-cycle | **Already works** — enrollment is dated; exam cohort resolves at marks-entry time |
| Transfer between campuses / programmes | **Already works** — `transfer_section` (see Part 5 caveat) |
| Transfer from another school | **Already works** — admission applications (migration 099) |
| Accelerated / skipping a grade | **Already works** — promotion targets any grade |
| Bridge / remedial / weekend / evening / summer / olympiad | **All the same shape as coaching** — a Class in a cycle with a supplementary enrollment (Part 2). **No new entity** |
| Special education, international curriculum, vocational, open schooling | **Programme** — already configuration |
| Language-specific sections | **Programme today, medium later** (Part 7) |
| Academic probation | A student status value — P3 |
| Alumni returning, external/private candidates | **Genuinely unsupported** — a person sitting an exam without an enrollment. **Out of MVP**; do not model speculatively |
| Exchange / temporary students | Supplementary enrollment — P3 |

---

## Part 11 — Configuration vs domain vs policy

| Concept | Class | Why |
|---|---|---|
| AcademicYear | **A — core entity** | Identity, dates, 18 FKs |
| **AcademicCycle** | **A — core entity** | Identity, dates, lifecycle, children. Not a setting |
| AcademicPeriod / Term | **A — core entity** | Dated subdivision referenced by components and `class_subjects` |
| **Stream** | **A — core entity** | Dimension of a Class; selects subjects and assessments. Its *list* is C |
| Grade | **A — core entity** | Exists; aliases are C |
| Programme | **A — core entity** | Exists |
| **AssessmentScheme** | **B — policy** | Selects how a (programme, grade, stream, cycle) is assessed |
| **AssessmentComponent** | **A — core entity** (child of a policy) | Has identity, max marks, weight; assessments reference it |
| **GradingScheme / GradingBand** | **B — policy** | Selects how a number becomes a grade |
| PromotionPolicy | **B — policy** (today: code) | P2 |
| **Batch / CoachingProgramme** | **NOT AN ENTITY** | A **Class** in a cycle + supplementary enrollment. Building either duplicates five properties Class already has |
| Calendar | **A — core entity** | Has publish/archive lifecycle |
| **Current cycle / current academic year** | **D — derived** | Compute from dates + today. Storing it is what produced two disagreeing owners |
| **Exam type** | **C — configuration** | Already a string on `exam_windows`; a vocabulary table if a school needs its own |
| **Assessment type** (`component.kind`) | **C — configuration** | A column, not a table |
| **Enrollment purpose** | **C — configuration** (a typed column) | Closed business set; CHECK constraint like `staff.employment_status` |
| Stream vocabulary | **C — configuration** | Replaces `VALID_STREAMS` |
| Feature flags, ID formats, attendance lock policy | **E — tenant setting** | Already correct on `AcademicSettings` |
| `student_lifecycle_events`, `attendance_corrections` | **F — operational record** | Append-only; already correct |

**No generic `config_key`/`config_value` table is proposed anywhere.** The two current violations are the
*opposite* error — domain data frozen into Python: `VALID_STREAMS` and the April–March boundary.

---

## Part 12 — Backward compatibility & migration

Assuming all eight changes. **The load-bearing property: while every year has exactly one cycle and every
enrollment is `primary`, every change below is behaviour-neutral.**

| # | Change | Migration | Backfill | Nullable transitional | Serializer | GraphQL | REST | admin-web | Expo | Seeds | Tests | Breaking |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `streams` table + `classes.stream_id` | additive | none needed — **0 live rows** | yes | class payload +`stream` | +field | unchanged | stream picker | none | set null | class fixtures | **No** |
| 2 | stream into class unique constraint | index swap | none | — | — | — | — | — | — | — | uniqueness tests | **No** |
| 3 | `subject_contexts.stream_id` | additive | NULL = all streams | yes | +field | +field | +field | no UI today (debt 43) | none | none | context tests | **No** |
| 4 | roll number → enrollment | additive + backfill | copy current value | yes | unchanged (keep the key) | unchanged | unchanged | sort/display swap | reads payload | set both | cache guard | **No** |
| 5 | `academic_cycles` + one cycle per year | additive + backfill | name = year name, same dates | — | +field | +query | — | hidden when 1 cycle | none | create default | year fixtures | **No** |
| 6 | `classes.academic_cycle_id` | additive + backfill | point at the year's default cycle | yes → NOT NULL later | +field | +field | +field | hidden when 1 | none | set | class fixtures | **No** |
| 7 | terms + calendar re-parented to cycle | backfill | via the default cycle | yes | unchanged | unchanged | unchanged | unchanged | reads holidays | set | term/calendar tests | **Low** |
| 8 | `enrollment_purpose` + index clause | additive | all existing → `primary` | no (default) | +field | +field | — | none initially | none | set | **cache sweep +1 clause** | **No** |
| 9 | `student_subject_elections` (N1) | additive | none — empty for schools without electives | — | +field on student | +field | — | elective picker on the student form | none | none | new | **No** |
| 10 | assessment schemes + components | additive | none | — | new | new | none (GraphQL-only) | new screen | none | none | new | **No** |
| 11 | grading schemes + bands | additive | none | — | new | new | none | new screen | none | seed a default | new | **No** |
| 12 | fix the April–March hardcode | code only | none | — | — | — | — | — | — | — | leave tests | **Behavioural** for non-April schools |

**Migration ordering constraints (FACT, from prior phases):**

1. Verify the chain **from an empty database**, not from one at head — `alembic_version` is `varchar(32)` by
   default and several revision names exceed it (fixed in `migrations/env.py`, but the rule stands).
2. Generated ids in migrations must be **derived from the source row** (`md5(...)::uuid::text`), never
   `prefix || gen_random_uuid()` — length is then guaranteed and re-runs cannot duplicate.
3. A migration must **carry data before it constrains**; never require an out-of-band script.
4. When a concept moves, sweep **serializer + query layer + every writer** together.

**Old API compatibility:** every change is additive; no existing field changes meaning. `students.class_id`
keeps its exact current semantics (the primary class), which is what protects all 694 client references.

---

## Part 13 — Six organizations modelled

Notation: `Cycle(name, dates, kind)`, `Class(programme, grade, stream, section, campus, cycle)`.

### Org 1 — Nursery–10, one board, one campus (Scenario A)

```
Year 2026-27
  Cycle("2026-27", Jun 2026→Apr 2027, main)          ← auto-created, never seen by the user
    Terms: Term 1, Term 2
    Calendar: one
    Classes: (GSEB, Nursery, –, A, Main, cycle) … (GSEB, Grade 10, –, B, Main, cycle)
    Enrollments: purpose=primary
    SubjectContexts: (GSEB, Grade 10, Gujarati/Science/Maths/English), stream_id NULL
    Elections: NONE — no electives
    Scheme: (GSEB, Grade 10, stream NULL, cycle) → [Term 1 50%, Term 2 50%]
```
**Operator sees:** programme, grade, section, campus. **No cycle, no stream, no elections.** ✅

### Org 2 — GSEB + CBSE (Scenario B)

```
Year 2026-27
  Cycle("GSEB Main", Jun→Apr, main)   Terms: T1, T2   Calendar A (Diwali break)
  Cycle("CBSE Main", Apr→Mar, main)   Terms: T1, T2   Calendar B (different holidays)
  Classes point at their own cycle; applicability is DERIVED
  Schemes differ per programme
```
✅ No contradiction — a class names one cycle; nothing else claims membership.

### Org 3 — Grades 1–8 vs 9–12 on different cycles (Scenario C)

```
Year 2026-27
  Cycle("Junior", Jun→Apr, main)   ← Classes Grades 1–8
  Cycle("Senior", Apr→Mar, main)   ← Classes Grades 9–12
```
✅ Grade range is evident from the classes; **no `grade_from`/`grade_to` columns needed** (Part 3).

### Org 4 — Grade 11 streams (Scenario E)

```
Cycle("2026-27", main)
  Class(CBSE, Grade 11, Science,  A, Main, cycle)
  Class(CBSE, Grade 11, Commerce, A, Main, cycle)   ← needs stream in the unique constraint
  SubjectContexts:
    (CBSE, 11, Science)  → Physics, Chemistry, Maths, Biology, Computer Science
    (CBSE, 11, Commerce) → Accountancy, Economics, Business Studies
  Elections (N1): within Science-A, student X takes Biology, student Y takes Computer Science
  Schemes: Science → [Theory 70, Practical 30]; Commerce → [Theory 100]
```
✅ **only with both stream (Part 5) and elections (N1).** Without N1 the Physics paper lists students who
dropped it. **This is the case that proves N1 is P0.**

### Org 5 — Grade 11 Science + JEE coaching + vacation batch (Scenarios F, G, J)

```
Year 2026-27
  Cycle("2026-27", Apr→Mar, main)
    Class(CBSE, 11, Science, A, City, cycle)
      Enrollment(student=Riya, purpose=primary)      → students.class_id = this class
  Cycle("JEE 2026", Apr→Mar, short_course)
    Class(CBSE, 11, Science, JEE-1, City, cycle)
      Enrollment(student=Riya, purpose=supplementary) → cache untouched
  Cycle("Grade 11 Vacation 2026", May 1→Jun 10, short_course)
    Class(CBSE, 11, Science, VAC-1, Hostel, cycle)
      Enrollment(student=Riya, purpose=supplementary)
```
✅ **No `CBSE+Science+JEE` programme.** Three enrollments, one primary. Attendance separates naturally
(`(class_id, date)`). Timetables separate naturally (per class). `students.class_id` still names the regular
section, so all 55 server and 694 client references stay correct. Fees bind per class. **Billing counts Riya
once** (Student row, by status).

**Contradiction check:** the unique index permits exactly one *primary* current enrollment per student per
year — satisfied. ✅

### Org 6 — Multiple campuses + hostel (Scenario H)

```
Campuses: City, Hostel, Junior
  Cycle("Junior 2026-27", Jun→Apr) ← Classes at Junior campus
  Cycle("Senior 2026-27", Apr→Mar) ← Classes at City + Hostel
  Calendars per cycle; branch scope (core/branch_scope.py) already restricts by campus
```
✅ Campus is already a Class dimension and already branch-scoped. **No change required.**

**No contradictions found across the six.** The one case that fails without the additions is Org 4 (needs
stream + elections) and Org 5 (needs enrollment purpose).

---

# A. SAFE TO IMPLEMENT NOW

Architecturally validated, additive, behaviour-neutral on existing data:

1. **`streams` table + `classes.stream_id` + stream in the class unique constraint.** 0 live rows to migrate.
2. **`subject_contexts.stream_id`** (nullable = all streams).
3. **`student_subject_elections`** (N1) — empty for schools without electives.
4. **`enrollment_purpose` on `student_class_enrollments`**, all existing rows → `primary`; the partial unique
   index gains `AND enrollment_purpose = 'primary'`.
5. **Roll number → `student_class_enrollments`**, `students.roll_number` kept as a guarded cache.
6. **`academic_cycles`** (name, start_date, end_date, cycle_kind) with one auto-created cycle per existing
   year, **no applicability columns**.
7. **`classes.academic_cycle_id`**, backfilled to the year's default cycle.
8. **Terms and calendars re-parented to the cycle.**
9. **`grading_schemes` + `grading_bands`** as a platform capability outside Examination.
10. **`assessment_schemes` + `assessment_components`** keyed `(programme, grade, stream, cycle)`.
11. **Fix `get_current_academic_year()`** (`teachers/constraint_services.py:295`) to read the tenant's cycle.

# B. MUST DECIDE BEFORE IMPLEMENTATION

Only genuine blockers.

| # | Decision | Why it blocks |
|---|---|---|
| **B1** | **Is a supplementary enrollment academic?** Does a coaching/vacation enrollment produce results and appear on a transcript, or is it participation only? | Determines whether `enrollment_purpose` has 2 values or more, and whether Examination may target supplementary classes. Cannot be added later without reprocessing results |
| **B2** | **Elective granularity (N1).** Do we record only *deviations* from the class's subject list (my recommendation), or every student↔subject pair explicitly? | Deviation-only keeps Scenario A at zero rows; explicit pairs are simpler to query but write ~6 rows per student per year. Changing later is a full backfill |
| **B3** | **`students.academic_result` — retire or keep?** | Examination must not write to it. Confirm it becomes read-only legacy |
| **B4** | **Marks permission namespace.** Rename the dead `grades.*` (7 keys, granted, unenforced, one letter from live `grade.*`) before Examination uses it | A revoke migration is needed because `seed_roles_for_tenant` only ever adds |
| **B5** | **Do boards genuinely need different cycle *dates*** (Scenario B), or only different terms and schemes? | If only terms/schemes, `academic_cycles` drops from P0-adjacent to P2 and the whole change shrinks. **Ask a real trust** |

# C. MUST NOT CHANGE

Existing architecture that is correct. Preserve it.

1. **`classes` as the Section (ADR-012).** Never create a `sections` table.
2. **`class_subject_teachers` as the single Teaching Assignment owner (ADR-014)**, resolved through
   `modules/academics/teaching_assignment.py` with `on=<date>`. Never query the tables directly.
3. **Attendance keyed on `(tenant, class_id, session_date)`.** The best-modelled domain; it separates
   offerings for free.
4. **`AcademicYear` as the organizational reporting label (ADR-009).** 18 FKs depend on it.
5. **`exam_windows`** — the calendar's time reservation. Not Examination. Complete vertical, in use.
6. **`subject_contexts`** — the strongest curriculum model in the codebase. Add `stream_id`; change nothing else.
7. **Tenant scoping**: `TenantBaseModel` + `with_loader_criteria`; every new model registered in
   `tests/test_tenant_isolation_invariants.py::SCOPED_MODELS`.
8. **Authorization (ADR-006/013)** — authority on the employment. No per-module permission system.
9. **The lifecycle-event pattern** (`student_lifecycle_events`, `staff_lifecycle_events`) — append-only,
   corrections are new events.
10. **The attendance correction/approval/lock vertical** — the precedent for marks locking.
11. **`students.class_id` semantics** — "the student's academic class". Protecting this is what keeps 694
    client references working.
12. **Branch scope** (`core/branch_scope.py`) — campuses already work.

# D. HIDDEN BLOCKERS

Discovered in this pass; missed by all three previous audits.

| # | Blocker | Evidence | Impact |
|---|---|---|---|
| **D1** 🔴 | **No student↔subject link anywhere.** Elective choice is unrecordable | 0 tables match; no subject function in `modules/students/`; `is_elective_bucket` marks the slot, not the chooser | Exam cohorts wrong for any school with electives, **silently**. **P0** |
| **D2** 🔴 | **`students.class_id` is the real blast radius, not the enrollment index** | 55 server + 694 client refs vs ~8 enrollment consumers; `test_no_student_anywhere_disagrees_with_their_enrollment` sweeps every student | Naive multi-enrollment breaks a passing test and 694 client call sites. Fixed by `enrollment_purpose` |
| **D3** 🟠 | **A mid-year stream change erases the prior placement** | Phase 34 made same-year moves **modify the enrollment in place**; `transfer_section` checks only year, not grade/programme/stream | Scenario I loses "was in Science until October" from the enrollment chain (survives only as a lifecycle event). **P1** |
| **D4** 🟠 | **`students` has three temporal/placement caches, one guarded** | `class_id`, `academic_year_id`, deprecated `academic_year` `String(20)`; `test_caches_follow_their_owner` covers `class_id` only | `academic_year_id` can drift silently. **P1** |
| **D5** 🟢 | **Billing is SAFE — correcting my own earlier P1** | `subscription/usage.py:53` counts `Student` rows by `student_status`; `platform/services.py` imports the same definition | Multi-enrollment **cannot** double-count. No work needed |
| **D6** 🟠 | **Promotion marks repeaters as "promoted"** | debt 14d; `enrollment_status="promoted"` written regardless | Transcripts misreport. **P1** |

# E. NEW REAL-WORLD SCENARIOS

Only those that materially affect architecture (full triage in Part 10).

| Scenario | Verdict |
|---|---|
| **Elective combinations within one section** (N1) | **P0** — needs `student_subject_elections` |
| **Cross-section subject** (a subject taken with another class) | **P2** — same table, FK allowed to point outside the class |
| **Supplementary / compartment / improvement exams** | **P1** — `supersedes_examination_id` + per-subject result override. Decide the column now |
| **Repeat year** | **P1** — promotion must stop labelling repeaters "promoted" |
| Remedial / bridge / weekend / evening / summer / olympiad | **No new entity** — all are a Class in a cycle + supplementary enrollment |
| External / private candidates, alumni re-sitting | **Out of MVP** — a person sitting an exam with no enrollment. Do not model speculatively |

# F. MVP / P1 / FUTURE

**MVP (blocks Examination)**
- `streams` + `classes.stream_id` + unique constraint · `subject_contexts.stream_id`
- **`student_subject_elections`** (D1)
- Term applicability (via cycle, or explicit scope)
- Roll number → enrollment
- `assessment_schemes` + `assessment_components`
- `grading_schemes` + `grading_bands`
- `academic_result` decision (B3) · `grades.*` rename (B4)

**P1 (before batches/coaching go live)**
- `academic_cycles` + `classes.academic_cycle_id` + cycle-scoped terms and calendars
- `enrollment_purpose` (or earlier, if coaching ships first — it is independent of cycles)
- One "current" resolver; retire/constrain `is_active`
- Fix the April–March hardcode
- Stream/grade/programme change closes and reopens the enrollment (D3)
- Guard `students.academic_year_id` (D4) · promotion vs repeaters (D6)
- Grade display aliases · supplementary exams
- Fees reference the cycle

**FUTURE**
- Medium as a real dimension (Part 7 — deferred deliberately)
- Component-level grading override · CGPA/GPA · PromotionPolicy as data
- Cross-section subjects · external candidates · cross-cycle transcripts
- `school_events.applies_to` investigation · `subject_contexts` UI (debt 43)

# G. FINAL TARGET DOMAIN MODEL

```
Tenant (= Organization)
 ├── SchoolUnit (Campus)                          [EXISTS]
 ├── AcademicProgramme (Board)                    [EXISTS]
 ├── Grade  ── GradeProgrammeAlias (P1)           [EXISTS + additive]
 ├── Stream                                       [NEW — A]
 ├── Medium                                       [EXISTS, dormant — DEFER]
 │
 ├── AcademicYear  ("2026-27" — the reporting label)   [EXISTS, UNCHANGED]
 │    └── AcademicCycle  (name, start_date, end_date, cycle_kind)   [NEW — A]
 │          │             NO applicability columns — derived via Classes
 │          ├── AcademicPeriod   (= academic_terms, re-parented)    [EXISTS]
 │          ├── AcademicCalendar (re-parented)                      [EXISTS]
 │          │     ├── Holiday · SchoolEvent · ExamWindow            [EXISTS — UNCHANGED]
 │          └── Class (= Section)                                   [EXISTS + cycle_id, stream_id]
 │                · programme · grade · stream · medium · campus · division · section
 │                · UNIQUE (tenant, campus, programme, grade, STREAM, section, year)
 │                │
 │                ├── ClassSubject                                  [EXISTS]
 │                │     └── ClassSubjectTeacher = Teaching Assignment (ADR-014) [EXISTS]
 │                ├── ClassTeacherAssignment                        [EXISTS]
 │                ├── AttendanceSession → Record → Correction       [EXISTS — UNCHANGED]
 │                ├── TimetableVersion → TimetableEntry             [EXISTS — UNCHANGED]
 │                └── StudentClassEnrollment                        [EXISTS + purpose, roll_number]
 │                      · enrollment_purpose: primary | supplementary
 │                      · UNIQUE (tenant, student, year) WHERE is_current AND purpose='primary'
 │                      └── StudentSubjectElection                  [NEW — A]
 │                            · class_subject_id, status: taking | dropped | exempted
 │
 ├── SubjectContext  (programme × grade × STREAM × subject)         [EXISTS + stream_id]
 │     · display_name · short_code · exam_code · type · role
 │     · medium_id · variant_of_context_id · elective_group_key
 │
 ├── AssessmentScheme  (programme, grade, stream, cycle)            [NEW — B/policy]
 │     ├── AssessmentComponent (kind, max_marks, weight, period?,   [NEW — A]
 │     │                        counts_toward_promotion, is_optional)
 │     └── GradingScheme → GradingBand                              [NEW — B/policy]
 │
 └── Examination  (see 2026-08-12-examination-discovery-audit.md)
       └── ExamPaper → ExamMark → ExamResult (snapshot) → ExamDocument
```

**New entities: five** — Stream, AcademicCycle, StudentSubjectElection, AssessmentScheme(+Component),
GradingScheme(+Band). **Everything else is additive columns on entities that already exist.**

# H. MIGRATION ORDER

Each step stands alone and leaves the tree working.

```
 1. streams table + classes.stream_id (nullable)              additive, 0 rows to migrate
 2. stream into the class unique constraint                   index swap
 3. subject_contexts.stream_id (nullable)                     additive
 4. student_subject_elections                                 additive, empty
 5. enrollment_purpose + partial index clause                 additive, all → 'primary'
 6. roll_number → student_class_enrollments (+ cache guard)   additive + backfill
 7. grading_schemes + grading_bands                           additive, new
 8. assessment_schemes + assessment_components                additive, new
 9. fix get_current_academic_year()                           code only ⚠ behavioural
10. academic_cycles + default cycle per year                  additive + backfill
11. classes.academic_cycle_id (nullable → NOT NULL)           additive + backfill
12. terms + calendars re-parented to cycle                    backfill
13. ── EXAMINATION BEGINS ──
14. (P1) stream/grade change closes+reopens enrollment
15. (P1) grade display aliases · promotion vs repeaters · academic_year_id guard
```

**Steps 1–8 are the Examination prerequisites.** 10–12 can land before or after Examination **provided
Examination references the Class** (which carries the cycle) rather than storing `academic_year_id` directly
— otherwise it must wait for 12. **This is a real sequencing constraint: decide B5 before step 13.**

# I. EXAMINATION READINESS GATE

| # | Prerequisite | Status |
|---|---|---|
| 1 | Stream is a real dimension (table + class FK + unique constraint) | **[ ] FAIL** — 0 rows, hardcoded vocabulary, outside the constraint |
| 2 | Subjects can vary by stream (`subject_contexts.stream_id`) | **[ ] FAIL** — column absent |
| 3 | **A student's subject set is knowable** (elections) | **[ ] FAIL** — no student↔subject link exists anywhere |
| 4 | Assessment patterns are configuration (scheme + components) | **[ ] FAIL** — nothing exists |
| 5 | Grading is a platform capability | **[ ] FAIL** — nothing exists; ghost column only |
| 6 | Terms can differ by programme/grade | **[ ] FAIL** — tenant-wide per year |
| 7 | Roll number is per-year | **[ ] FAIL** — lifetime field |
| 8 | `academic_result` will not own results | **[ ] FAIL** — decision B3 open |
| 9 | Marks permission namespace is safe | **[ ] FAIL** — dead `grades.*`, one letter from live `grade.*` |
| 10 | Teaching Assignment service resolves markers | **[✓] PASS** — ADR-014 implemented, date-aware |
| 11 | Attendance pattern available for marks lock/correction | **[✓] PASS** — `attendance_corrections` |
| 12 | Tenant isolation covers new models | **[✓] PASS** — `TenantBaseModel` + guard tests |
| 13 | Branch scope covers new domains | **[✓] PASS** — `core/branch_scope.py` |
| 14 | Document + PDF + notification infrastructure | **[✓] PASS** — ADR-015, WeasyPrint, dispatcher |
| 15 | Enrollment supports concurrent offerings | **[ ] FAIL** — needs `enrollment_purpose` (P1 for Examination itself, P0 for coaching) |
| 16 | Cohort resolvable as of a date | **[✓] PASS** — enrollments are dated |

**Gate: 5 PASS / 11 FAIL. Examination is NOT ready to start.** Items 1–9 are steps 1–8 of §H.

# J. FINAL RECOMMENDATION

> **Can we now freeze the academic architecture and start implementation?**

**Architecture: YES — freeze it, with the three corrections in this audit.
Examination implementation: NO — not yet. Eight prerequisite steps first.**

**What is now settled and should be frozen:**

- `AcademicCycle` is the right temporal entity, and it must carry **no applicability columns** — applicability
  is derived through Classes. This is the change I most wanted to break, and deriving is strictly better:
  it makes the brief's contradiction example *unrepresentable* rather than merely discouraged.
- **A Batch is not an entity.** A Class in a short cycle plus a supplementary enrollment covers vacation
  batches, coaching, remedial, weekend, evening, summer and olympiad programmes with **one mechanism**.
  Do not build `Batch` or `CoachingProgramme`.
- **Concurrency is solved by `enrollment_purpose`, not by re-scoping the index** — 4 consumers change instead
  of 694 client references, and `students.class_id` keeps its meaning.
- Stream is a core entity with configurable vocabulary; Period belongs to Cycle; grading attaches to the
  scheme; `exam_windows`, `subject_contexts`, attendance, teaching assignments and branch scope stay exactly
  as they are.
- **Medium: defer.** Do not touch it. Do not build grade-scoped grades either — aliases, later.

**What remains, precisely:**

1. **Five product decisions (B1–B5).** B5 in particular — *do boards need different cycle dates, or only
   different terms and schemes?* — decides whether `academic_cycles` is P0-adjacent or P2, and it is the one
   question I cannot answer from the repository. **Ask a real trust before step 10.**
2. **Eight implementation steps (§H 1–8)** before Examination starts.
3. **One discovery this audit produced that changes the plan: D1.** There is no student↔subject link, so a
   student's subject set is unknowable. Every previous audit — including both of mine — keyed Examination on
   `(programme, grade, stream)` and assumed the cohort fell out of the class. **It does not.** Without
   elections, exam cohorts are wrong for every school with electives, and wrong *silently*.

**Exact implementation order:** §H steps 1 → 8, then re-run this gate. If all sixteen items pass, Examination
begins at step 13 with the backlog in `2026-08-12-examination-discovery-audit.md` §19.

**One opinionated closing note.** The instinct to build `AcademicCycle` first is wrong. It is the largest
change here and the one whose necessity is least certain (B5). **Steps 1–8 contain no cycle work at all**, and
they are exactly what Examination needs. Build those, ship Examination, and let the first trust that actually
runs two boards on two calendars tell you whether cycles are needed — by which point the schema will be ready
for them and the change will still be additive.

---

*Prepared 2026-08-12 against commit `70ab3a4`, with the live local database queried for populated-column and
reference-count evidence. Discovery only — no repository changes of any kind.*

**Not investigated:** the panel app's academic surface; Expo's academic screens beyond route/shape audits;
Finance beyond the year and billable-count coupling; whether any reporting aggregate blends attendance across
classes (flagged in the temporal audit, still open).
