# Academic domain & temporal model — summary

**2026-08-12.** Condensed from `2026-08-academic-domain-and-temporal-model-audit.md`. Read that for evidence,
file paths and the scenario-by-scenario reasoning. Discovery only — nothing was changed.

---

## 1. Current architecture

**The temporal model is a tenant-wide singleton.**

- `AcademicSettings` — `UNIQUE (tenant_id)`, *"One row per tenant"*, holds `current_academic_year_id`.
  **One current academic year for the whole organization.**
- `academic_calendars` — `UNIQUE (tenant_id, academic_year_id)`. **One calendar per tenant per year**
  (holidays, weekly holiday config, working days).
- `academic_terms` — keyed on `(tenant, year, name)`. **No programme, grade or campus scope.**
- `student_class_enrollments` — `UNIQUE (tenant, student, academic_year) WHERE is_current`.
  **One current placement per student per year.**
- 18 tables carry `academic_year_id`. The year reaches the server as a **per-request parameter**
  (`?academic_year_id=`), from `ActiveAcademicYearContext` — there is no server-side `g.academic_year_id`.

**The structure below the year is sound.** `classes` (= Section, ADR-012) already carries campus × programme
× grade × medium × stream × year. Teaching assignments are effective-dated (ADR-014), timetables are per
class, attendance keys on `(class, date)`. `subject_contexts` (191 live rows) is a genuinely strong curriculum
model — display name, short code, **`exam_code` ("Board paper number")**, mandatory/elective, language roles,
elective groups, medium variants.

**Three dimensions exist as columns but are unused in production** (queried, 316 live classes):

| Column | Populated | Reality |
|---|---|---|
| `classes.medium_id` | **0** | `mediums` table is **empty**; medium is folded into programme names — `"GSEB English Medium"` vs `"GSEB Gujarati Medium"` are two programmes |
| `classes.stream` | **0** | Free text; vocabulary hardcoded as `VALID_STREAMS` in `school_setup/bulk_generator_service.py:32` |
| `classes.start_date`/`end_date` | **0** | Written and serialized, never populated, **never read** |

---

## 2. Dangerous assumptions

| # | Assumption | Evidence | Priority |
|---|---|---|---|
| 1 | **April–March is the academic year, hardcoded in Python** | `teachers/constraint_services.py:295` — never reads `academic_years`; 7 call sites (leave balances). A June–April school is wrong and **cannot be configured right** | **P0** |
| 2 | **Terms are tenant-wide** | ADR-009 promised variation would attach to (Programme, AY); `academic_terms` has no `programme_id`. **The escape hatch was never built** | **P0** |
| 3 | **Stream is a hardcoded string, outside the unique constraint** | `uq_classes_unit_programme_grade_section_year` excludes stream ⇒ Grade 11 Sci-A and Com-A **collide**. The bulk generator parses `"Sci-A"` but the constraint won't store the result. Never exercised — 0 live rows | **P0** |
| 4 | **Subjects vary by (programme, grade) only** | `subject_contexts` has no `stream_id` ⇒ Grade 11 Science and Commerce get the same subjects, papers and results | **P0** |
| 5 | **One result per student, ever** | `students.academic_result` = single overwritten `String(20)`, no year (debt 14d) | **P0** |
| 6 | **One roll number for life** | `students.roll_number`, not on the enrollment ⇒ historical marksheets print today's number | **P0** |
| 7 | **One current enrollment per student per year** | `uq_sce_current_per_student_year` — blocks every batch, coaching and parallel offering | **P1** |
| 8 | **Two answers to "what year is it"** | `AcademicSettings.current_academic_year_id` vs `dashboard/service.py:46` (`is_active` + latest). **All 5 live years are `is_active=true`**, so the flag is meaningless | **P1** |
| 9 | **One calendar per tenant** | `academic_calendars` UNIQUE (tenant, year) ⇒ no programme- or campus-specific vacations | **P1** |
| 10 | **Fees are per year** | `fee_structures.academic_year_id`; a second enrollment risks double-counting billable students | **P1** |
| 11 | **Grades are flat and tenant-wide** | "Std 10" vs "Grade 10" across boards; programme span inexpressible; graduation underivable | **P1** |

---

## 3. Required before Examination (P0)

1. **Stream becomes a real dimension** — `streams` table, `classes.stream_id` **inside** the unique
   constraint, `subject_contexts.stream_id`. Examination keys papers and schemes on
   (programme, grade, **stream**); without it Science and Commerce silently share one exam.
2. **Terms gain applicability** (cycle or explicit scope). Assessment patterns anchor to periods; tenant-wide
   terms cannot express Pattern A for Grades 1–9 and Pattern B for Grade 10.
3. **Roll number moves to the enrollment.**
4. **Decide `academic_result`** — Examination must not extend it.
5. **Rename the dead `grades.*` permission namespace** (7 unenforced keys, one letter from the live
   `grade.*`).

Items 3–5 are carried from `2026-08-12-examination-discovery-audit.md`.

---

## 4. Proposed target model

**One new entity, one promoted dimension, one re-scoped index.**

```
Tenant
 └── AcademicYear ............. the LABEL ("2026-27") — UNCHANGED, 18 tables depend on it
      └── AcademicCycle ....... NEW: the dated period a set of students operates in
            · name, start_date, end_date
            · cycle_kind: main | supplementary | short_course
            · applicability (all nullable = applies to everything):
                  programme_id · school_unit_id · grade_from/grade_to · stream
            ├── AcademicPeriod ..... = today's academic_terms, re-parented
            ├── AcademicCalendar ... re-parented (holidays, working days)
            └── Class .............. + academic_cycle_id, + stream_id
                  └── StudentClassEnrollment
                        · uniqueness per (student, CYCLE), not (student, YEAR)
```

**Why a Cycle, not per-programme Academic Years:** per-programme years break ADR-009's "one 2026-27", force
all 18 dependent tables to decide *whose* year they mean, and give a single-programme school two rows where
it needs one. A Cycle is additive — a one-cycle school never sees it.

**A vacation batch / coaching programme is NOT a new entity — it is a Class in a short Cycle.** Of the six
things Scenario C needs (campus, teachers, timetable, subjects, selective enrollment, 40-day duration),
`Class` already provides five. Only the dates are missing. Inventing a `Batch` would duplicate the other five.

| Scenario | Resolution | New code? |
|---|---|---|
| A — GSEB June→April, CBSE April→March | Two cycles under one 2026-27, `programme_id` set | None |
| B — Grades 1–8 vs 9–12 differ | Two cycles with `grade_from`/`grade_to` | None |
| C — 40-day vacation batch | `cycle_kind='short_course'` + its classes + second enrollment | None once uniqueness moves |
| D — Science/Commerce/Arts | Stream as a real dimension | Additive |
| E — JEE/NEET coaching | Same as C | None |
| Assessment patterns | `AssessmentScheme → AssessmentComponent` on (programme, grade, stream, cycle) | Examination's work |

---

## 5. Configuration boundaries

| Item | Class | Note |
|---|---|---|
| Academic Year, **Academic Cycle**, Period, Class, Enrollment, **Stream** | **Core entity** | Identity, dates, lifecycle |
| Assessment Scheme, Grading Scheme, Promotion rules, attendance lock/approval | **Policy** | Selects behaviour among entities |
| **Stream vocabulary**, weekly holiday config, ID formats | **Configuration** | Data, not code |
| **"Current" year/cycle**, **the April–March boundary**, "is this class active" | **Derived** | Must be computed, not stored |
| Feature flags | **Tenant setting** | Already correct |

**Two current violations — both the *opposite* of the config-table anti-pattern: domain data frozen into
Python.** `VALID_STREAMS` (should be configuration) and the April–March cycle (should be derived).

We are **not** proposing generic `config_key`/`config_value` tables. Every item above is either a real entity
or a typed policy row.

---

## 6. Migration plan

Additive, phased, no big bang. **While every year has exactly one cycle, every change below is
behaviour-neutral** — the second cycle activates them.

| Change | Migration | Data preserved | Breaking? |
|---|---|---|---|
| `streams` table + `classes.stream_id` | Additive | Yes — **0 live rows have a stream** | No |
| Stream into the unique constraint | Yes | Yes | No |
| `subject_contexts.stream_id` (nullable) | Additive | Yes — NULL = all streams | No |
| Roll number → enrollment | Additive + backfill | Yes | No |
| `AcademicCycle` + one default cycle per existing year | Additive + backfill | Yes | No |
| `classes.academic_cycle_id` | Additive + backfill | Yes | No |
| Terms & calendar re-parented to cycle | Backfill | Yes | Low |
| Enrollment uniqueness → cycle | Index swap | Yes | No while 1 cycle/year |
| Fix the April–March hardcode | Code | Yes | **Behavioural** — leave balances change for non-April schools |
| Retire `academic_result` | Later | Yes (read-only first) | Deferred |

**Two sequencing traps** (both already learned and recorded in the debt register): a dual-written concept
must have its **serializer, query layer and every writer** swept together; and the migration chain must be
verified **from an empty database**, not from one already at head.

---

## 7. Priorities

- **P0 (before Examination):** stream as a dimension · term applicability · roll number → enrollment ·
  `academic_result` decision · `grades.*` rename.
- **P1 (before batches/coaching/multi-cycle):** `AcademicCycle` · enrollment uniqueness per cycle · one
  "current" resolver · fix the April–March hardcode · calendar per cycle · fees per cycle ·
  programme-scoped grades or aliases.
- **P2 (defer safely):** medium — fill or retire · class dates — drive or drop · bell schedules per cycle ·
  snapshot subject/grade names into documents · give `subject_contexts` a UI (debt 43).
- **P3 (future):** `school_events.applies_to` investigation · PromotionPolicy as data · cross-cycle
  transcripts.

---

## 8. Open product decisions

1. **Is a batch enrollment academic?** Transcript + attendance + results, or participation only?
2. **Do boards genuinely need different cycle dates**, or are shared-year-different-terms enough? This is
   the difference between P1 and "ADR-009 was right".
3. **Grade vocabulary across boards** — one row with per-programme aliases, or two rows?
4. **Medium** — fill the dimension, or accept that a medium *is* a programme and retire `mediums`?
5. **Is coaching a school offering or a separate business?**
6. **Report card scope** — per examination, per term, or annual?
7. **Can a student's stream change mid-year** — transfer or correction?

---

## 9. Why this model supports multiple school operating models

**Six things in today's architecture would force custom code for 10 different schools:**

1. The **April–March hardcode** — unfixable by configuration.
2. The **hardcoded stream vocabulary**, plus stream's absence from the class unique constraint.
3. **Tenant-wide terms** — ADR-009 promised this would be configuration and it is not.
4. **One calendar per tenant** — no per-board vacations.
5. **One current enrollment per student per year** — blocks every batch and coaching programme.
6. **Subjects that cannot vary by stream** — Science and Commerce share one subject set.

**The smallest change that removes all six:**

> **One new entity — `AcademicCycle` (dates + applicability) between AcademicYear and Class — plus promoting
> Stream from a hardcoded string to a real dimension, plus re-scoping one partial unique index from year to
> cycle.**

One table, one dimension, one index, and three behaviour-neutral re-parentings.

**What stays untouched, and that is the point:** the Academic Year label (ADR-009 holds, 18 FKs intact);
`classes` as the section (ADR-012 holds); **teaching assignments, timetables and attendance need no change at
all** — they are already per-class and date-aware; and `subject_contexts` needs one nullable column to become
a complete curriculum model.

**The honest caveat:** none of this makes different *assessment patterns* work — that is Examination's job
(`AssessmentScheme → AssessmentComponent` + a grading scheme). But those stay *policies* only if the
structure can express `(programme, grade, stream, cycle)`. **Today it expresses two of the four.** Closing
that gap is why items 1–4 are P0: Examination is what would otherwise bake the gap in permanently.
