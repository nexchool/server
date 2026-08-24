# Academic domain & temporal model — discovery audit

**Date:** 2026-08-12 · **Status:** discovery only. No code, migrations, schema, GraphQL, REST, client or Jira
changes were made. No ADRs written.
**Scope:** whole repository (server, admin-web, panel, client) + the live local database.
**Question:** what is the correct temporal and academic model for Nexchool that lets different schools,
programmes, grades, streams and batches run on different cycles and policies while the core domain stays stable?

**Evidence labels** (§28): **FACT** = read from code or queried from the database. **INFERENCE** = strongly
implied. **RECOMMENDATION** = proposal. **UNKNOWN** = needs a decision or information not in the repo.

> **Method note.** Where the schema *could* theoretically express something, that is recorded as schema
> capability, **not** as support. Several dimensions that exist as columns are unused in practice, and the
> live database was queried to establish which. That distinction is the substance of this audit.

---

## 1. Executive summary

**FACT — the temporal model is a tenant-wide singleton, and its variation escape hatch was never built.**

`ADR-009-academic-year-operational-context.md:324` states the doctrine:

> *"Academic Year belongs to the organization — a trust running CBSE and GSEB has one 2026-27, not two.
> What varies per Programme (terms, promotion rules…) attaches to (Programme, Academic Year)."*

The first half is implemented. **The second half is not.** `academic_terms` is keyed on
`(tenant_id, academic_year_id, name)` with **no `programme_id`, no `grade_id`, no `school_unit_id`**
(`modules/academics/backbone/models.py`). So the very mechanism ADR-009 nominated to carry per-programme
variation does not exist. Today a trust running GSEB and CBSE gets **one set of terms for both**.

That single gap is what makes Scenarios A, B and E unrepresentable — not the shared academic-year label,
which is a reasonable decision.

**FACT — three dimensions exist as columns but are unused in production.** Queried against the live
database (316 classes):

| Column | Rows populated | Reality |
|---|---|---|
| `classes.medium_id` | **0** | `mediums` table is **empty (0 rows)**. Medium is encoded into *programme names*: `"GSEB English Medium"` and `"GSEB Gujarati Medium"` are two separate `academic_programmes` |
| `classes.stream` | **0** | Free text; vocabulary hardcoded as `VALID_STREAMS` in `modules/school_setup/bulk_generator_service.py:32` |
| `classes.start_date` / `end_date` | **0** | Written and serialized, never populated, and **never read for any logic** |

So the schema *looks* multi-dimensional and in practice is not. Two of these (stream, class dates) are the
natural seams for the fix; the third (medium) is a naming decision already taken in the field.

**FACT — "what year is it?" has two different answers in the codebase.**

1. `AcademicSettings.current_academic_year_id` — `UniqueConstraint("tenant_id")`, docstring *"One row per
   tenant — current year, defaults, feature flags"*.
2. `modules/dashboard/service.py:46::_active_academic_year()` — `is_active=True ORDER BY start_date DESC`.

And `AcademicYear.is_active` has **no uniqueness constraint**. In the live database **all 5 academic years
have `is_active = true`**, so that flag cannot answer the question at all — resolution (2) silently degrades
to "the most recent year".

**FACT — one hardcoded academic calendar exists in Python.**
`modules/teachers/constraint_services.py:295`:

```python
def get_current_academic_year() -> str:
    """Return current academic year string using April–March cycle."""
    today = school_today()
    if today.month >= 4:
        return f"{today.year}-{str(today.year + 1)[2:]}"
    return f"{today.year - 1}-{str(today.year)[2:]}"
```

It never reads `academic_years`. Seven call sites, all teacher leave balances. **For a June–April school
every leave balance is filed against the wrong year string**, and no configuration can correct it.

**FACT — one calendar per tenant per year.** `academic_calendars` carries
`UniqueConstraint("tenant_id", "academic_year_id")`. Weekly holiday configuration, working days and the
published summary are therefore tenant-wide. Programme-specific or campus-specific vacations are not
expressible. The only per-scope hook anywhere in the calendar is `exam_windows.applicable_class_ids` (JSONB).

**FACT — no batch, cohort, offering or session concept exists.** Zero domain hits for `cohort`,
`course_offering`, `coaching`, `JEE`, `NEET`, `intensive`, `short_term`. Scenario C is greenfield.

**FACT — the constraint that actually blocks Scenarios C and E-overlap is one partial index.**
`student_class_enrollments` carries `uq_sce_current_per_student_year`: unique on
`(tenant_id, student_id, academic_year_id) WHERE is_current = true`. **A student cannot hold two current
enrollments in one academic year.** A vacation batch, a coaching programme and a hostel programme alongside
regular school are all the same shape of problem, and all are blocked by this one index.

**The encouraging finding.** `subject_contexts` (191 live rows) is a genuinely good abstraction that already
does most of what §9 asks — and it already carries an `exam_code` column commented *"Board paper number for
this (programme, grade, subject)"*. Someone thought about examinations here. It is the right place to build on.

**Bottom line.** The core structure (`classes` carrying campus × programme × grade × medium × stream ×
year) is sound and does not need replacing. What is missing is (a) a **dated period** that is not the whole
tenant's year, (b) **applicability** on terms and calendars, and (c) **stream as a real dimension**. Those
are three additive changes, not a rewrite.

---

## 2. Current domain map (derived from code)

**FACT.** Established by reading models, not the docs. Per ADR-012 the v2 vocabulary maps onto v1 tables;
**never create `sections`, `teaching_assignments` or `academic_enrollments`.**

```
Tenant  (= Organization; core/models.py)
 │
 ├── SchoolUnit ................ "Campus"; branch-scope anchor (core/branch_scope.py)
 │
 ├── AcademicProgramme ......... "Board" — and, in practice, ALSO the medium
 │                               (live data: "GSEB English Medium", "GSEB Gujarati Medium")
 │
 ├── Grade ..................... FLAT, TENANT-WIDE catalogue. Not scoped to programme.
 │                               2 FKs in: classes.grade_id, subject_contexts.grade_id
 │
 ├── Medium .................... table EMPTY (0 rows). Unused.
 │
 ├── Department ................ type='academic_division' (Primary / Secondary …)
 │
 ├── AcademicYear .............. name, start_date, end_date, is_active (NO uniqueness)
 │    ├── AcademicTerm ......... (tenant, year, name) — NO programme / grade / campus scope
 │    ├── AcademicCalendar ..... UNIQUE (tenant, year) — one calendar per tenant
 │    │     ├── Holiday
 │    │     ├── SchoolEvent .... applies_to default 'entire_school'
 │    │     └── ExamWindow ..... applicable_class_ids JSONB ← the only per-scope hook
 │    └── BellSchedule
 │
 ├── AcademicSettings .......... UNIQUE (tenant) — current_academic_year_id, policies
 │
 └── Class  (= SECTION, ADR-012)
      · academic_year_id, school_unit_id, programme_id, grade_id
      · medium_id (unused), department_id, stream (unused, free text)
      · section, name (nullable), grade_level (deprecated)
      · start_date / end_date  ← EXIST, never populated, never read
      · teacher_id  [CACHE ONLY, ADR-014] · merged_into_class_id
      · UNIQUE (tenant, school_unit, programme, grade, section, academic_year)
      │        ↑ NOTE: stream and medium are NOT in this constraint
      │
      ├── ClassSubject ......... weekly_periods, is_mandatory, is_elective_bucket, academic_term_id
      │     └── ClassSubjectTeacher = TEACHING ASSIGNMENT (effective-dated, ADR-014)
      ├── ClassTeacherAssignment
      ├── StudentClassEnrollment  = ACADEMIC ENROLLMENT
      │     · UNIQUE (tenant, student, academic_year) WHERE is_current  ← blocks overlap
      │     · promoted_from_enrollment_id (promotion chain)
      │     · NO roll_number (it lives on students, lifetime)
      ├── AttendanceSession → AttendanceRecord → AttendanceCorrection
      └── TimetableVersion → TimetableEntry

SubjectContext  (programme × grade × subject) — 191 live rows
  · display_name, short_code, exam_code ("Board paper number")
  · type: mandatory | elective · role: first/second/third_language | core | co_curricular
  · medium_id, variant_of_context_id, elective_group_key, default_weekly_periods
  ↑ the strongest existing abstraction; NOT stream-aware
```

**FACT — 18 tables carry `academic_year_id`** (queried from `information_schema`): `academic_calendars`,
`academic_terms`, `admission_applications`, `bell_schedules`, `classes`, `exam_windows`,
`fee_structure_classes`, `fee_structures`, `holidays`, `hostel_allocations`, `school_events`,
`student_class_enrollments`, `student_lifecycle_events`, `students`, `transport_enrollments`,
`transport_fee_plans`, `transport_route_schedules`, `transport_schedule_exceptions`.

**FACT — how the year reaches the server.** There is **no server-side `g.academic_year_id`**. The year is a
client selection passed per request as `?academic_year_id=` (≈12 route sites), held in
`admin-web/src/contexts/ActiveAcademicYearContext.tsx` and seeded by `ActiveScopeProvider.tsx` from
`status.academic_year.active_id` (i.e. `AcademicSettings.current_academic_year_id`), falling back to the
first row of the years list. `ActiveUnitContext.tsx` does the same for campus.

**INFERENCE — this is better than it looks.** Because the year is a *parameter* rather than a server global,
most services already accept it explicitly. Introducing a finer-grained period is therefore mostly a matter
of what the client selects and what the classes point at — **not** a rewrite of request handling.

---

## 3. Academic Year audit

### 3.1 Does the code assume one active academic year per tenant?

**FACT — yes, in two places, inconsistently.**

| # | Mechanism | Evidence | Assumption | Risk |
|---|---|---|---|---|
| 1 | `AcademicSettings.current_academic_year_id` | `backbone/models.py:36`; `UniqueConstraint("tenant_id")`; docstring *"One row per tenant"* | Exactly one current year for the whole organization | **High** — no programme, campus or grade can differ |
| 2 | `_active_academic_year()` | `dashboard/service.py:46` — `is_active=True ORDER BY start_date DESC` then any-latest fallback | The newest active year is "the" year | **High** — all 5 live rows are `is_active=true`, so this silently means "latest" |
| 3 | `get_current_academic_year()` | `teachers/constraint_services.py:295` | **April–March, hardcoded**, returns a string, never reads the table | **Critical for non-April schools** |
| 4 | `AcademicYear.is_active` | `academic_year/models.py:35` — plain boolean, no partial unique index | A flag marks the current year | **Medium** — unmaintained; 5/5 active in live data |
| 5 | Client selection | `ActiveAcademicYearContext.tsx` | One year selected app-wide at a time | **Low** — a UI affordance, easily widened |

### 3.2 The thirteen questions in §5

**FACT** unless stated.

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Multiple academic years coexist? | **Yes** | 5 rows live; 18 tables FK to it; history preserved |
| 2 | Multiple cycles active simultaneously? | **No** | `AcademicSettings` unique per tenant; no cycle concept exists |
| 3 | Different programmes, different cycles? | **No** | ADR-009 forbids; and terms have no `programme_id` to carry the variation it promised |
| 4 | Different grades, different cycles? | **No** | Nothing below Programme carries dates except `classes.start_date/end_date`, which are unpopulated and unread |
| 5 | Different campuses, different cycles? | **No** | Same |
| 6 | Overlapping student affiliations? | **No** | `uq_sce_current_per_student_year` — one current enrollment per student per year |
| 7 | Batch independent of the year? | **No** | No batch concept; and every enrollment needs an `academic_year_id` |
| 8 | Calendar tied to one global year? | **Yes** | `academic_calendars` UNIQUE (tenant, year) |
| 9 | Timetable assumes one year? | **Indirectly** | `TimetableVersion → class_id → Class.academic_year_id`; `bell_schedules.academic_year_id` |
| 10 | Examinations assume one year? | **Yes** (what exists) | `exam_windows.academic_year_id` NOT NULL |
| 11 | Fees assume one year? | **Yes** | `fee_structures.academic_year_id`, `fee_structure_classes.academic_year_id` |
| 12 | Attendance assumes one year? | **No — and this is correct** | `attendance_sessions` key on `(class, date)`; the year enters only as an optional filter via `Class.academic_year_id` (`attendance/services.py:583`) |
| 13 | Promotion assumes one year? | **Yes** | `promoted_from_enrollment_id` chains year→year; `is_current` per year |

**INFERENCE.** Attendance is the model citizen: it binds to the **class and the date**, which are the facts
that actually exist, and treats the year as a query filter. Everything that binds to `academic_year_id`
*structurally* is what will resist a finer-grained temporal model.

---

## 4. Concept separation (§6)

**FACT — Nexchool currently collapses five of the seven concepts into `AcademicYear`.**

| Concept | Exists? | Where | Verdict |
|---|---|---|---|
| **Academic Year** (the label, "2026-27") | **Yes** | `academic_years` | Keep. Correct, and 18 tables depend on it |
| **Academic Cycle** (the actual operating period) | **No** | Collapsed into `AcademicYear.start_date/end_date` | **Missing — this is the central gap** |
| **Academic Period** (Term / Semester) | **Partly** | `academic_terms` — but tenant-wide per year | Exists, wrongly scoped |
| **Assessment Period** (Unit Test 1, Mid Term) | **No** | Nearest is `exam_windows` (a calendar reservation) | Missing; Examination's problem |
| **Assessment Event** | **No** | — | Missing; Examination's problem (see the 2026-08-12 Examination audit) |
| **Batch / Cohort** | **No** | — | Missing |
| **Enrollment** | **Yes** | `student_class_enrollments` | Exists, but single-current-per-year |

**RECOMMENDATION — do not collapse Year and Cycle, and do not split them into two user-facing concepts
either.** The distinction that matters is: an **Academic Year is a name the organization reports under**; a
**Cycle is a dated period a set of students actually operates in**. A single-programme school has exactly one
cycle per year and should never see the word. A trust with GSEB (June–April) and CBSE (April–March) has two
cycles under one 2026-27, which is precisely what ADR-009 said should be possible and did not build.

---

## 5. Batch / short-term programmes (§7)

**FACT — nothing reusable exists.** Searched `batch`, `cohort`, `session`, `course`, `offering`, `camp`,
`vacation`, `summer`, `intensive`, `coaching`, `JEE`, `NEET`, `short_term`. All hits are either unrelated
(`batch_size`, `db.session`, `StudentPromotionBatch` = a promotion run) or prose. `vacation` appears only as
a calendar import type.

**RECOMMENDATION — a vacation batch is NOT a new entity. It is a Class in a short Cycle.**

Derivation, not preference. Test the scenario against what a Class already is:

| Scenario C requirement | Already a property of `Class`? |
|---|---|
| Different campus | ✅ `school_unit_id` |
| Different teachers | ✅ `class_subject_teachers` |
| Different timetable | ✅ `TimetableVersion` per class |
| Different subjects | ✅ `class_subjects` |
| Only some students attend | ✅ enrollment is per student |
| Runs ~40 days | ❌ **the only thing missing** — a Class has no meaningful dates |

Five of six requirements are already satisfied by `Class`. Inventing a `Batch` entity would duplicate all
five to gain the sixth. **The honest reading is that a batch is a Class whose Cycle is 40 days long.**

The same reasoning covers JEE/NEET coaching (Scenario E): a Class, in a coaching Cycle, with its own subjects
and its own enrollments. **One mechanism, three scenarios.**

**Two things must change for this to work:**

1. `uq_sce_current_per_student_year` must become **per cycle**, not per year — otherwise a child in the
   vacation batch cannot also be in regular Grade 11.
2. A Class must be able to say which Cycle it belongs to.

**UNKNOWN — a product decision.** Is a vacation-batch enrollment an *academic enrollment* (appears on the
transcript, carries attendance and results) or a *participation* (a record that they attended, no academic
weight)? The answer determines whether it reuses `student_class_enrollments` or needs its own table. I
recommend reusing enrollment with an explicit **enrollment purpose** — but this is genuinely a business call.

---

## 6. Programme / Board / Grade / Stream (§8)

### CBSE Grade 10 vs GSEB Grade 10 vs ICSE Grade 10

**FACT — representable, and already done in production.** `classes` carries both `programme_id` and
`grade_id`, and the structural unique constraint includes `programme_id`. Live data shows exactly this:
`Grade 1 A` exists twice, once per programme.

**FACT — but the Grade entity is shared, and that has consequences** (re-confirmed from
`2026-08-09-stabilization-audit.md` §6, still open): `grades.name` is unique **tenant-wide**, so "Std 10"
(GSEB house style) and "Grade 10" (CBSE) are either one row — one board's vocabulary imposed on the other —
or two rows at the same level, which splits every grade-wise report. A programme's grade *span* is also
inexpressible, so a section can be opened on a grade that programme does not run.

### Grade 11 Science / Commerce / Arts

**FACT — Stream is a second-class citizen and is unused.**

- `classes.stream` is a free-text column, **NULL on all 316 live classes**.
- The vocabulary is **hardcoded in Python**: `VALID_STREAMS = frozenset(("Science", "Commerce", "Arts",
  "Vocational"))` at `modules/school_setup/bulk_generator_service.py:32`. A school with "Humanities" or
  "Vocational — IT" needs a **code change**, which violates the CLAUDE.md rule *"Configuration, not forks…
  Onboarding a new org must require zero code changes."*
- **`stream` is NOT in the structural unique constraint**
  (`uq_classes_unit_programme_grade_section_year`). So Grade 11 Science-A and Grade 11 Commerce-A, both with
  `section='A'`, **collide at the database level**.
- **INFERENCE — the bulk generator works around this by encoding the stream into the section label.** Its
  docstring says `"Sci-A" -> stream="Science", section="A"`, and it then filters on `Class.stream`; but with
  stream outside the unique index, two streams sharing a section letter cannot both be stored. The parser
  exists; the constraint does not permit its result. Since no live row has a stream, **this path has never
  been exercised in production**.
- `subject_contexts` — the table that decides which subjects a (programme, grade) offers — **has no
  `stream_id`**. So Grade 11 Science and Grade 11 Commerce currently resolve to the *same subject set*.

**RECOMMENDATION — Stream must become a real dimension before Examination.** It determines subjects, which
determines papers, which determines results. Building Examination on a (programme, grade) key silently
merges Science and Commerce.

### JEE / NEET coaching

**FACT — completely unsupported** (0 hits).

**RECOMMENDATION — coaching is a Class in its own Cycle, not a new concept** — the same answer as the
vacation batch (§5). It is not a Stream (a student is *in* Science *and* takes JEE), and making it a
Programme would combinatorially explode programmes (GSEB × English × Science × JEE).

---

## 7. Subject / curriculum audit (§9)

**FACT — this is the healthiest part of the academic domain.** `subject_contexts` (191 live rows) models
"how a (programme, grade) offers a subject" and already supports almost everything §9 asks:

| §9 requirement | Supported? | Evidence |
|---|---|---|
| Different name per context | ✅ | `display_name` |
| Different code per context | ✅ | `short_code`, **`exam_code`** (*"Board paper number"*) |
| Different weekly periods | ✅ | `default_weekly_periods`, and `class_subjects.weekly_periods` per section |
| Mandatory vs elective | ✅ | `type` ∈ (mandatory, elective); `class_subjects.is_mandatory`, `is_elective_bucket` |
| Elective groups ("pick one of three") | ✅ | `elective_group_key` |
| Language slots | ✅ | `role` ∈ (first/second/third_language, core, co_curricular) |
| Medium variants of one subject | ✅ | `medium_id`, `variant_of_context_id` |
| Grade-specific subjects | ✅ | `grade_id` |
| Programme-specific subjects | ✅ | `programme_id` |
| **Stream-specific subjects** | ❌ | **no `stream_id`** — the one real gap |
| Different marks / credits / grading per context | ❌ | no marks, credits or grading anywhere (see the 2026-08-12 Examination audit) |

So Grade 10 (Gujarati, Science, Maths, English) and Grade 11 Commerce (Accountancy, Economics, Business
Studies) are representable **only if** Grade 11 Science and Grade 11 Commerce are different *programmes* —
which would be modelling a stream as a board. Adding `stream_id` to `subject_contexts` is the correct fix
and is additive (nullable).

**Caveat (FACT).** `2026-08-09-stabilization-audit.md` §7 records `subject_contexts` as having **no component
consumer in any client** — the service→hook chain ends at nothing. It is live (written by
`school_setup/seed_service.py`, read by `promote_service.apply_for_grade`) but unreachable from any screen
(debt 43). **It is good architecture with no user interface**, which is why its quality has gone unnoticed.

---

## 8. Assessment pattern abstraction (§10)

**FACT — nothing exists.** No assessment, scheme, pattern, weight or period concept anywhere.

**RECOMMENDATION — one entity, not five.** The four patterns in §10 differ only in (a) the **list of
assessment components**, (b) their **weights**, and (c) which **period** each belongs to. That is one policy
object with children:

```
AssessmentScheme          ← policy, attached to (programme, grade, [stream], cycle)
  └── AssessmentComponent ← name, kind (test/exam/project/practical/classwork),
                            weight, max_marks, period ref, counts_toward_promotion
```

Pattern A (Term 1, Term 2) is a scheme with two components. Pattern B (Unit Tests, Semester, Preliminary,
Board) is a scheme with four. Pattern D (continuous) is a scheme with five, weighted. **No code branches.**

Do **not** build `AcademicPattern` + `AssessmentPolicy` + `AssessmentType` + `AssessmentPeriod` +
`AssessmentWeight` + `AssessmentScheme` as six tables. That is the error ADR-012 and ADR-013 both record:
naming each paragraph of a document as a table.

**The anchor point matters more than the shape.** A scheme must attach to the same tuple that decides
subjects — `(programme, grade, stream)` — because that is what varies. Adding `stream` to that tuple is
therefore a prerequisite for assessment patterns as well as for Examination.

---

## 9. Grading policy (§11)

**FACT — no grading exists.** Confirmed in the 2026-08-12 Examination audit: zero hits for `GradingScale`,
`grade_boundary`, letter-grade constants. `modules/subjects/models.py:47` carries
`default_grading_scale_id` — *"future FK to grading_scales"* — a **ghost column** with no table, no FK and no
reader in any repo.

**FACT — a naming hazard.** The permission catalogue already contains a dead `grades.*` namespace (7 keys,
granted to Teacher and Student, never enforced — debt 6c), one letter from the live `grade.*` master used
for the grade-level catalogue.

**RECOMMENDATION — grading is a platform capability, not an Examination feature.**

```
GradingScheme (tenant) ── scheme_type: percentage | letter | band | pass_fail
  └── GradingBand ── label, min_value, max_value, grade_point, is_pass
```

Attach at the **scheme** level (so `AssessmentScheme → GradingScheme`), which gives per-programme,
per-grade and per-stream variation for free through the scheme's own applicability. Do not attach a grading
scheme to a Subject in MVP — that is the combination fewest schools use, and `default_grading_scale_id`
already shows what happens when a hook is added before a need.

---

## 10. Result / promotion / progression (§12)

**FACT.**

- `students.academic_result` — a single `String(20)`, nullable, **overwritten**, with **no year dimension**.
  Written at `students/services.py:1227`, read only at `promotion_service.py:123` as
  `str(...).strip().lower() == "fail"`. Registered as debt **14d**.
- `student_class_enrollments` carries `enrollment_status` and the `promoted_from_enrollment_id` chain — **this
  is the real progression spine** and it is per year.
- Promotion writes `enrollment_status="promoted"` even for students it classified as repeating (debt 14d).
- **Graduation is a manual workflow act** (`lifecycle_service.graduate_student`), not derived. The canon's
  "highest grade of a Programme" cannot be computed because grades are not scoped to programmes
  (stabilization audit §6, consequence 2).

**RECOMMENDATION — the distinctions in §12 map onto three owners, not one field:**

| Concept | Owner |
|---|---|
| Assessment Result | Examination module (per component) |
| Examination Result | Examination module (per examination, snapshot) |
| Term Result | derived from assessment results within a period |
| **Annual Result** | **`student_class_enrollments`** — it already has the year and the chain |
| **Promotion Decision** | **`student_class_enrollments.enrollment_status`** + the promotion chain |
| Graduation | `student_lifecycle_events` (already correct) |
| Next Enrollment | the next `student_class_enrollments` row |

**`students.academic_result` should be retired, not extended.** It is a cache of the annual outcome that
predates the enrollment chain, and it cannot answer "what happened in 2024-25".

---

## 11. Temporal model — the proposal

### The question

Can Nexchool support School A (June→April), School B (April→March), School C (Grade 1 June→April, Grade 10
April→March), School D (40-day Grade 11 vacation batch + regular Grade 11), School E (6-month JEE offering)
**without core code changes?**

**FACT — today: A and B yes; C, D and E no.**

- **A and B** work because `AcademicYear.start_date/end_date` are free — *except* that teacher leave
  balances go through the hardcoded April–March helper, which is wrong for School A.
- **C** fails: nothing below Programme carries dates, terms are tenant-wide, and the calendar is tenant-wide.
- **D and E** fail: no cycle concept, and `uq_sce_current_per_student_year` forbids the second enrollment.

### RECOMMENDATION — introduce one entity: the Academic Cycle

```
Tenant
 └── AcademicYear ................ the LABEL the organization reports under ("2026-27")
      │                            KEEP AS IS — 18 tables depend on it, ADR-009 holds
      │
      └── AcademicCycle ........... NEW. The dated period a set of students operates in
            · name ("GSEB Main", "CBSE Main", "Grade 11 Vacation Batch", "JEE 2026")
            · start_date, end_date
            · cycle_kind: main | supplementary | short_course
            · APPLICABILITY (all nullable = "applies to everything"):
                  programme_id · school_unit_id · grade_from / grade_to · stream
            │
            ├── AcademicPeriod ..... = today's academic_terms, RE-PARENTED to the cycle
            │                         (this is ADR-009's unbuilt promise, finally built)
            ├── AcademicCalendar ... re-parented to the cycle (holidays, working days)
            └── Class .............. gains academic_cycle_id
                  └── StudentClassEnrollment
                        · uniqueness becomes (student, CYCLE) not (student, YEAR)
```

**Why a Cycle and not per-programme Academic Years.** Making `academic_years` per-programme would:
break ADR-009's "one 2026-27"; require every one of the 18 dependent tables to decide *whose* year it means;
and give a single-programme school two rows where it needs one. A Cycle is **additive** — a school with one
cycle never sees the concept, because the default cycle is created with the year and everything points at it.

**Why applicability columns rather than a join table.** A cycle applies to at most one programme, one campus
and one grade range in every scenario given. Nullable columns express that in one row and one index; a join
table would be four tables to express "all of them", which is the shape ADR-013 rejected.

### How each scenario resolves

| Scenario | Resolution | New code? |
|---|---|---|
| **A** — GSEB June→April, CBSE April→March | Two cycles under one 2026-27, each with `programme_id` set | None |
| **B** — Grades 1–8 vs 9–12 differ | Two cycles with `grade_from`/`grade_to` | None |
| **C** — 40-day vacation batch | A cycle with `cycle_kind='short_course'`; its classes; students get a second enrollment | None once uniqueness moves to cycle |
| **D** — Science / Commerce / Arts | **Stream as a real dimension** (separate change, §6) | Additive |
| **E** — JEE / NEET coaching | A cycle with `cycle_kind='short_course'`, its own classes, subjects, timetable | None |
| Different assessment patterns | `AssessmentScheme` on (programme, grade, stream, cycle) | Examination's work |

---

## 12. Configuration vs domain model (§14)

Classified per the requested taxonomy. **The rule I applied:** if it has identity, dates or a lifecycle, it
is an entity; if it selects behaviour among entities, it is policy; if it is a display or derivation
preference, it is configuration; if it can be computed, it must not be stored.

| Item | Class | Why |
|---|---|---|
| Academic Year | **A — core entity** | Has identity, dates, and is referenced by 18 tables |
| **Academic Cycle** | **A — core entity** | Has identity, dates, a lifecycle, and children. Not a setting |
| Academic Period / Term | **A — core entity** | Dated subdivision that assessments and fees reference |
| **Stream** | **A — core entity (a dimension of Class)** | Determines subjects, teachers, timetable and results. Its *vocabulary* is C |
| Class / Section | **A** | Already correct |
| Enrollment | **A** | Already correct |
| Assessment Scheme | **B — policy** | Selects how a (programme, grade, stream) is assessed |
| Grading Scheme | **B — policy** | Selects how a number becomes a grade |
| Promotion rules | **B — policy** | Selects who advances |
| Attendance approval / lock policy | **B — policy** | Already correctly on `AcademicSettings` |
| Stream vocabulary | **C — configuration** | Should be a table, **not** `VALID_STREAMS` in Python |
| Weekly holiday config | **C — configuration** | Already JSONB on `academic_calendars`; acceptable — it drives a derivation, not a decision |
| Admission-number / employee-ID format | **C — configuration** | Already correct on `AcademicSettings` |
| **"Current" academic year / cycle** | **D — derived** | Should be computed from cycle dates and today, **not** stored in `AcademicSettings.current_academic_year_id` |
| **April–March boundary** | **D — derived** | Must come from the cycle, not `constraint_services.py:295` |
| Whether a class is "active" | **D — derived** | Already the practice (`is_setup_complete`, teacher `status`) |
| Feature flags | **E — tenant setting** | Already correct |

**Two current violations of this taxonomy:** `VALID_STREAMS` is a domain vocabulary hardcoded in Python
(should be C), and the April–March cycle is a derived value hardcoded in Python (should be D). Neither is a
generic config-table anti-pattern — they are the opposite mistake, **domain data frozen into code**.

---

## 13. Temporal overlap & concurrency (§15)

**FACT — not supported.** The blocker is precise and singular:

```
uq_sce_current_per_student_year:
  UNIQUE (tenant_id, student_id, academic_year_id) WHERE is_current = true
```

A student in 2026-27 may hold **exactly one** current enrollment. Regular school + vacation batch + JEE
coaching + hostel programme is therefore one enrollment too many, three times over.

| Overlap | Supported today? | After the cycle change? |
|---|---|---|
| Student in two classes | ❌ the index above | ✅ one current per **cycle** |
| Teacher teaching in two cycles | ✅ **already** | `class_subject_teachers` is effective-dated (ADR-014); no year coupling |
| Two timetables at once | ✅ **already** | `TimetableVersion` is per class |
| Class membership overlap | ❌ | ✅ |
| Campus movement (batch at another campus) | ✅ **already** | `Class.school_unit_id` is per class |
| Attendance in two contexts | ✅ **already** | `attendance_sessions` key on (class, date) |

**INFERENCE — the concurrency story is much better than the temporal story.** Teaching assignments,
timetables, attendance and campus are all already per-class and date-aware. **Enrollment is the only place
where the one-year-one-place assumption is hard-coded into a constraint.** That is a single-index change,
not an architectural overhaul — which is the most actionable finding in this audit.

---

## 14. Calendar audit (§16)

**FACT.** `academic_calendars` — `UniqueConstraint("tenant_id", "academic_year_id")`. One calendar per tenant
per year, holding `weekly_holidays_config`, `published_summary`, `preferences`, and a
draft→published→archived lifecycle.

| Requirement | Supported? |
|---|---|
| School-wide holidays | ✅ `holidays` |
| Programme-specific holidays | ❌ |
| Campus-specific holidays | ❌ |
| Grade-specific holidays | ❌ |
| Exam periods | ✅ `exam_windows` (+ `applicable_class_ids`) |
| Batch-specific events | ❌ |
| Coaching schedules | ❌ |

**FACT.** `school_events.applies_to` defaults to `'entire_school'`, which suggests narrower scoping was
anticipated. **UNKNOWN** — I did not enumerate what other values it accepts or whether any reader branches on it.

**RECOMMENDATION.** Re-parent `academic_calendars` from `(tenant, year)` to `(cycle)`. A single-cycle school
is unaffected (one cycle per year ⇒ one calendar per year). A trust with two cycles gets two calendars, which
is exactly what "GSEB breaks for Diwali, CBSE does not" requires. Add optional applicability to `holidays`
only if a school actually needs a holiday narrower than its cycle — do not add it speculatively.

**`exam_windows` stays exactly as it is** (per the instruction, and because it is a live, complete vertical:
service, REST writes, GraphQL read, overlap detection, import/export, admin-web dialog). Its place in the new
model: **the calendar's reservation of examination time within a cycle**, distinct from the Examination
entity itself — the same conclusion the 2026-08-12 Examination audit reached (decision D2 there).

---

## 15. Timetable audit (§17)

**FACT.** `TimetableVersion → class_id`; `TimetableEntry` per version; `bell_schedules.academic_year_id`;
versioning, drafts, rollover and clock-time conflict detection across differing bell schedules all exist
(migration 096 consolidated two implementations into this one).

**INFERENCE — the timetable is already fine for the scenarios.** Because a version belongs to a **class**,
"Grade 11 Science regular timetable + JEE coaching timetable + hostel batch timetable" is three classes with
three versions. No hack required — *provided* a student may be enrolled in all three (§13).

**The one coupling worth noting:** `bell_schedules.academic_year_id` means bell schedules are per year, not
per cycle. A vacation batch running 8am–12pm needs its own bell schedule; that works today (it is just
another row), but it would be filed under the year rather than the batch. **P2** — cosmetic until cycles exist.

---

## 16. Fees / finance impact (§18)

**FACT.** `fee_structures.academic_year_id` and `fee_structure_classes.academic_year_id`.
`transport_fee_plans`, `transport_enrollments`, `hostel_allocations` likewise carry the year.

**INFERENCE — this will become a blocker, but not for Examination.** A student in regular school + vacation
batch + JEE coaching needs three fee structures in one academic year. Since `fee_structure_classes` binds a
structure to **classes**, and each of those offerings is its own class, the structure side already works. What
breaks is the **billable-student count** and any logic that assumes one enrollment per student per year
(the same index as §13).

**RECOMMENDATION — do not redesign Finance now.** Record that when cycles land, `fee_structures` should
reference the **cycle** rather than the year. Note also (from the Examination audit) that
`INACTIVE_STUDENT_STATUSES` and the billable count already had a history of drift; a second enrollment per
student is exactly the kind of change that would silently double-count. **P1, with an explicit test.**

---

## 17. Attendance impact (§19)

**FACT — attendance is correctly modelled and needs no change.** `attendance_sessions` is unique on
`(tenant, class_id, session_date)`; the academic year appears only as an optional list filter
(`attendance/services.py:583`). `attendance_records` hang off the session; corrections, approval and locking
all key on the session.

**INFERENCE — a student can attend a short-term batch without corrupting their regular history**, because
attendance is recorded against the **class**, and the batch is a different class. The two histories are
naturally separate and naturally joinable.

**One caveat (INFERENCE).** Attendance *percentage* reporting that aggregates "all sessions for this student
this year" would silently blend regular and batch attendance. I did not find such an aggregate, but report
cards typically carry one. **Flag for whoever builds attendance reporting: aggregate by cycle, not by year.**

---

## 18. Document / report impact (§20)

**FACT** (carried from the 2026-08-12 Examination audit, re-confirmed):

- `students.roll_number` is a **lifetime** integer on the student, not on the enrollment. A historical
  marksheet prints today's roll number.
- `person_documents` (ADR-015) is person-owned and has no academic-year dimension — correct for identity
  documents, wrong for anything academic-year-specific.
- No report card, transcript or certificate generation exists. PDF infrastructure (`weasyprint==68.1`,
  two `pdf_service.py` implementations, calendar export) does exist.

**RECOMMENDATION.** Any academic document must **snapshot** its context — cycle, class, roll number,
programme, grade, stream — at generation time. This is the same immutability conclusion the Examination audit
reached for report cards, and it is what makes §21 (historical reconstruction) work.

---

## 19. Historical data (§21)

**FACT — coexistence works; reconstruction is partly broken.**

| Requirement | Status |
|---|---|
| 2024-25, 2025-26, 2026-27 coexist | ✅ 5 years live; 18 tables carry the year |
| A student's Grade 10 (2025-26) placement is reconstructible | ✅ `student_class_enrollments` keeps every row with `is_current=false` |
| …their section, campus, programme, grade | ✅ via the enrollment's `class_id` |
| …their **roll number that year** | ❌ **lost** — lifetime field, overwritten |
| …their **result that year** | ❌ **lost** — `academic_result` is a single overwritten field |
| …their subjects that year | ⚠️ via `class_subjects`, **unless the class's subjects were later edited** |
| Historical reports unaffected by config changes | ❌ **not guaranteed** — grading, subject names (`subject_contexts.display_name`) and grade names are all mutable and read live |

**RECOMMENDATION.** History requires **snapshots at the moment of record**, not live joins through mutable
configuration. That is a principle the codebase already applies in `person_merges` (full snapshot) and
`attendance_corrections` (previous value retained) — it simply has not been applied to academic outcomes.

---

## 20. Dangerous global assumptions

| # | File / object | Assumption | Why dangerous | Actually valid? | Recommended change | Priority |
|---|---|---|---|---|---|---|
| 1 | `teachers/constraint_services.py:295` | **April–March is the academic year**, hardcoded | Every leave balance for a June–April school is filed under the wrong year; unfixable by configuration | **No** | Derive from the cycle/year the tenant actually runs | **P0** |
| 2 | `academics/backbone/models.py` `AcademicTerm` | Terms are tenant-wide per year | ADR-009 nominated (Programme, AY) to carry variation and this table cannot; blocks Scenarios A, B, E | **No** | Re-parent to cycle (or add applicability) | **P0** |
| 3 | `classes/models.py` + `school_setup/bulk_generator_service.py:32` | Stream is free text with a **hardcoded** four-value vocabulary, and is **absent from the unique constraint** | Grade 11 Sci-A and Com-A collide; a new stream needs a code change; `subject_contexts` cannot vary subjects by stream | **No** | Stream table + `classes.stream_id` in the unique constraint + `subject_contexts.stream_id` | **P0** |
| 4 | `subject_contexts` | Subjects vary by (programme, grade) only | Science and Commerce resolve to the same subject set ⇒ same exam papers | **No** | Add `stream_id` (nullable) | **P0** |
| 5 | `students.academic_result` | One overwritten result per student, ever | No academic history; Examination would extend a dead end | **No** | Leave legacy; results own outcomes | **P0** (decision) |
| 6 | `students.roll_number` | One roll number for life | Historical marksheets print the wrong number | **No** | Move to the enrollment; snapshot into results | **P0** |
| 7 | `student_class_enrollments` `uq_sce_current_per_student_year` | One current placement per student per **year** | Blocks batches, coaching, any concurrent offering | Valid *within* a cycle only | Scope the index to the **cycle** | **P1** |
| 8 | `AcademicSettings` UNIQUE (tenant) `current_academic_year_id` | One current year per organization | Cannot support programmes on different cycles | Partly — the *label* can be shared; the *period* cannot | Derive "current" from cycle dates | **P1** |
| 9 | `academic_calendars` UNIQUE (tenant, year) | One calendar per tenant | Programme/campus-specific vacations impossible | **No** | Re-parent to cycle | **P1** |
| 10 | `dashboard/service.py:46` vs `AcademicSettings` | Two different answers to "what year is it" | Screens can disagree; `is_active` is unmaintained (**5/5 rows active**) | **No** | One resolver, one owner | **P1** |
| 11 | `AcademicYear.is_active` | A boolean marks the current year | No uniqueness; all live rows true ⇒ meaningless | **No** | Drop or constrain; prefer derivation | **P1** |
| 12 | `fee_structures.academic_year_id` | Fees are per year | A student with three offerings needs three structures; billable count may double-count | Valid until cycles exist | Reference the cycle | **P1** |
| 13 | `grades` flat, tenant-wide unique name | One grade vocabulary per organization | "Std 10" vs "Grade 10" across boards; programme span inexpressible; graduation underivable | **No** | Programme-scoped grades **or** display aliases | **P1** |
| 14 | `classes.medium_id` / `mediums` | Medium is a dimension | Table **empty**; medium is folded into programme names in production | The workaround works, but duplicates programmes | Decide: fill the dimension or retire it | **P2** |
| 15 | `classes.start_date` / `end_date` | A class has its own period | Written, serialized, **never populated, never read** | Not currently | Either drive them from the cycle or drop them | **P2** |
| 16 | `bell_schedules.academic_year_id` | Bell schedules are per year | A batch's schedule files under the year | Works, imprecise | Reference the cycle | **P2** |
| 17 | Subject/grade names read live in reports | Config changes rewrite history | A renamed subject changes last year's marksheet | **No** | Snapshot at record time | **P2** |
| 18 | `school_events.applies_to='entire_school'` | Events are school-wide by default | Narrower scoping anticipated but **UNKNOWN** whether implemented | Unknown | Investigate before extending | **P3** |

---

## 21. Target academic architecture

**Smallest architecture that supports the scenarios.** Additive; nothing existing is replaced.

### CORE STRUCTURE (entities — unchanged unless marked)

```
Tenant → SchoolUnit (Campus)
Programme (board)          · Grade · Medium · Department (division)
Stream                     ← NEW (a table; today a hardcoded string)
Class (= Section)          + stream_id, + academic_cycle_id
Subject · SubjectContext   + stream_id
Student · Staff · Teacher
StudentClassEnrollment     + roll_number, uniqueness re-scoped to cycle
```

### ACADEMIC CONTEXT (the temporal spine)

```
AcademicYear      the reporting label — UNCHANGED (18 tables depend on it)
AcademicCycle     ← NEW. dates + applicability (programme/campus/grade range/stream)
AcademicPeriod    = today's academic_terms, re-parented to the cycle
```

### POLICIES (behaviour selection, not entities)

```
AssessmentScheme → AssessmentComponent    ← NEW (Examination)
GradingScheme    → GradingBand            ← NEW (platform capability)
PromotionPolicy                           ← NEW (later; today it is code)
Attendance approval / lock policy         ← EXISTS on AcademicSettings
```

### CONFIGURATION

Stream vocabulary (becomes data) · weekly holiday config · admission/employee-ID formats · feature flags.

### OPERATIONS (consume the above; mostly unchanged)

Timetable · Attendance · Examination · Marks · Results · Fees · Transport · Hostel.

**Why this is the smallest correct change:** exactly **one new temporal entity** (Cycle), **one dimension
promoted** to first class (Stream), **one index re-scoped** (enrollment), and **two re-parentings**
(terms, calendar). Everything else is already right — teaching assignments are effective-dated, timetables are
per class, attendance is per class-day, and `subject_contexts` is already a strong curriculum model.

---

## 22. Migration strategy

Nothing here is a big-bang rewrite. Each step stands alone and leaves the tree working.

| Change | Migration? | Old data preserved? | Old APIs? | admin-web | Expo | Breaking? | Phased? |
|---|---|---|---|---|---|---|---|
| Stream table + `classes.stream_id` | Yes, additive | Yes — `stream` is NULL everywhere, **nothing to migrate** | Yes | New picker on class create/edit | None (Expo does not read stream) | **No** | Yes |
| `stream` into the unique constraint | Yes | Yes — no live row has a stream | Yes | None | None | **No** | Yes |
| `subject_contexts.stream_id` (nullable) | Yes, additive | Yes — NULL = applies to all streams | Yes | Screen does not exist yet (debt 43) | None | **No** | Yes |
| `roll_number` → enrollment | Yes + backfill | Yes — copy current value | Yes | Sort/display swap | Reads payloads, not the column | **No** | Yes |
| `AcademicCycle` + default cycle per year | Yes + backfill | Yes — one cycle per existing year | Yes | Year picker may stay as-is initially | None | **No** | Yes |
| `classes.academic_cycle_id` | Yes + backfill | Yes — point at the default cycle | Yes | None initially | None | **No** | Yes |
| Terms re-parented to cycle | Yes + backfill | Yes | Yes | Terms screen | None | **No** | Yes |
| Calendar re-parented to cycle | Yes + backfill | Yes — one cycle ⇒ one calendar | Yes | Calendar screen | Reads holidays (debt 31) | Low | Yes |
| Enrollment uniqueness → cycle | Yes | Yes — identical while one cycle per year | Yes | None | None | **No** while 1:1 | Yes |
| Retire `academic_result` | Later | Yes — read-only until backfilled | Yes | Promotion filter | None | Deferred | Yes |
| Derive "current" instead of storing | Code | Yes | Yes | Uses the same status endpoint | None | Low | Yes |
| Fix the April–March hardcode | Code | Yes | Yes | None | None | **Behavioural** — leave balances change for non-April schools | Needs care |

**The load-bearing property:** while every year has exactly one cycle, **every one of these changes is a
no-op in behaviour.** The second cycle is what activates them. That is what makes this safe to land ahead of
need — and it is the opposite of the `default_grading_scale_id` mistake, because each column here has a
migration, a backfill and a reader from day one.

**Two sequencing traps** (both learned in earlier phases and recorded in the register):
1. A dual-written concept must have its **serializer, query layer and every writer** swept together — moving
   the serializer alone produced real bugs in the teacher/student cutover.
2. Verify the migration chain **from an empty database**, not from a database already at head.

---

## 23. Priorities

**P0 — would make Examination structurally wrong if ignored**

1. **Stream as a real dimension** (`streams` table, `classes.stream_id` in the unique constraint,
   `subject_contexts.stream_id`). Examination keys papers and schemes on (programme, grade, **stream**);
   without it Science and Commerce silently share one exam.
2. **Terms gain applicability** (via cycle or explicit scope). Assessment patterns anchor to periods; a
   tenant-wide term cannot express Pattern A for Grades 1–9 and Pattern B for Grade 10.
3. **Roll number → enrollment** (carried from the Examination audit). Marksheets print it.
4. **Decide `academic_result`'s fate** — Examination must not extend it.
5. **Rename the dead `grades.*` permission namespace** before Examination uses it (Examination audit §10).

**P1 — before broader academic expansion (batches, coaching, multi-cycle)**

6. `AcademicCycle` + default backfill.
7. Enrollment uniqueness re-scoped to the cycle.
8. One resolver for "current year/cycle"; retire the `is_active` flag or constrain it.
9. Fix the April–March hardcode.
10. Calendar re-parented to the cycle.
11. Fee structures reference the cycle; **guard the billable count against double-counting**.
12. Programme-scoped grades or display aliases.

**P2 — safe to defer**

13. Medium: fill the dimension or retire the empty table and the unused column.
14. `classes.start_date/end_date`: drive from the cycle or drop.
15. Bell schedules reference the cycle.
16. Snapshot subject/grade names into academic documents.
17. Give `subject_contexts` a UI (debt 43) — it is good architecture nobody can reach.

**P3 — future capability**

18. `school_events.applies_to` — investigate before extending.
19. PromotionPolicy as data rather than code.
20. Cross-cycle analytics and transcripts.

---

## 24. Open product decisions

1. **Is a batch enrollment academic?** Does a vacation-batch or coaching enrollment appear on the transcript,
   carry attendance and produce results — or is it participation only? Determines whether it reuses
   `student_class_enrollments`.
2. **Do boards genuinely need different cycle dates**, or is one organizational year with different *terms*
   enough? This is the difference between P1 and "ADR-009 was right all along". Worth asking a real trust.
3. **Grade vocabulary across boards** — "Std 10" and "Grade 10": one row with per-programme display aliases,
   or two rows?
4. **Medium** — fill the dimension, or accept that a medium is a programme and retire `mediums`?
5. **Is coaching a school offering or a separate business?** If schools bill it separately and it never
   appears on a report card, it may not belong in the academic domain at all.
6. **Report card scope** — per examination, per term, or annual (carried from the Examination audit, D7).
7. **Does a student's stream ever change mid-year**, and if so is that a transfer or a correction?

---

## 25. Final question

> *If Nexchool is deployed tomorrow to 10 completely different schools — each with different boards,
> academic-year dates, grade structures, streams, examination patterns, grading systems, campuses,
> short-term batches and coaching programmes — which parts of the current architecture would force us to
> write custom code, and what is the smallest architectural change that would eliminate that dependency?*

**Six things would force custom code. Only six.**

1. **The April–March hardcode** (`teachers/constraint_services.py:295`). A June–April school gets wrong
   leave-year strings today, and **no configuration can fix it**. This is the only place in the audited
   surface where a school's calendar is frozen into Python.
2. **The hardcoded stream vocabulary** (`VALID_STREAMS`, `bulk_generator_service.py:32`). A school with
   "Humanities" needs a deploy. And because `stream` is outside the class unique constraint, two streams
   sharing a section letter cannot coexist at all.
3. **Tenant-wide terms** (`academic_terms` has no programme/grade scope). Any school whose Grade 10 assesses
   differently from Grade 1 needs either duplicated terms or a code branch — and ADR-009 explicitly promised
   this would be configuration.
4. **One calendar per tenant** (`academic_calendars` UNIQUE (tenant, year)). A trust where CBSE and GSEB take
   different vacations cannot express it.
5. **One current enrollment per student per year** (`uq_sce_current_per_student_year`). Every short-term
   batch, coaching programme and parallel offering is blocked by this single partial index.
6. **Subjects that cannot vary by stream** (`subject_contexts` has no `stream_id`). Grade 11 Science and
   Commerce resolve to the same subject set, so their exams and results would too.

**The smallest change that eliminates all six:**

> **One new entity — `AcademicCycle` (dates + applicability) sitting between AcademicYear and Class — plus
> promoting Stream from a hardcoded string to a real dimension, plus re-scoping one partial unique index
> from year to cycle.**

That is **one table, one dimension, one index**, and three re-parentings (terms, calendar, classes) that are
behaviour-neutral while every year has one cycle.

**What it does *not* require, and this is the point:** the Academic Year stays (ADR-009 holds, 18 FKs
untouched); `classes` stays as the section (ADR-012 holds); teaching assignments, timetables and attendance
need **no change at all** — they are already per-class and date-aware; and `subject_contexts` needs one
nullable column to become a complete curriculum model.

**The honest caveat.** Nothing above makes different *assessment patterns* work — that is the Examination
module's job, and it needs `AssessmentScheme → AssessmentComponent` plus a grading scheme. But those are
**policies hanging off the structure**, and they only stay policies if the structure can express
`(programme, grade, stream, cycle)`. **Today it can express two of those four.** Closing that gap is the
prerequisite, and it is P0 precisely because Examination is what would otherwise bake the gap in permanently.

---

*Prepared 2026-08-12 against commit `70ab3a4`, with the live local database queried for populated-column
evidence. Discovery only — no code, migrations, schema, API, client, ADR or Jira changes were made.*

**Not investigated, stated so the backlog is not mistaken for complete:** the full business logic of all 18
`academic_year_id` tables (schema and key call sites only); Finance beyond the year coupling;
`school_events.applies_to` accepted values and readers; the panel app; Expo's academic screens in depth;
whether any reporting aggregate blends attendance across classes.
