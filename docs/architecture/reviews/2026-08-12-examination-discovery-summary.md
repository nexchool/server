# Examination discovery — summary

**2026-08-12.** Condensed from `2026-08-12-examination-discovery-audit.md`. Read that for evidence and
story-by-story reconciliation.

---

## What already exists

**Of 107 tables in the codebase, two touch this domain.**

| Exists | What it is |
|---|---|
| `exam_windows` | A **calendar reservation** — a date range timetable/events must avoid. Full vertical: service, REST writes, GraphQL read, overlap detection, CSV import, PDF/CSV/HTML export, admin-web dialog + activity log. **Not an examination.** |
| `grades` | The **grade-level master** ("Grade 9"). A false friend — it is not grading scales. |

**Confirmed absent** (zero hits across `modules/`, `core/`, `scripts/`, `migrations/`): `obtained_marks`,
`max_marks`, `passing_marks`, `question_paper`, `answer_sheet`, `report_card`, `Assessment`,
`GradingScale`, `grade_boundary`. No exam module in admin-web or the Expo client.

**Infrastructure that is strong and reusable:** notifications (types, channels, dispatcher, templates,
Celery, relationship-derived audiences) · academic calendar (holidays, events, exam windows, terms, import/
export) · documents (`person_documents` + ADR-015, S3 + `view_url` indirection) · PDF (`weasyprint==68.1`,
Jinja pipeline, tenant branding) · RBAC (ADR-006/013, one catalogue, 166 keys) · tenant scoping ·
lifecycle-event pattern (student + staff) · attendance correction/approval/lock · bulk import ·
`is_own_studentship` self-access · ADR-014 Teaching Assignment service.

---

## What can be reused

`exam_windows` as the calendar reservation · the whole notification stack · the existing calendar (add an
exam layer) · WeasyPrint pipeline · `person_documents` **mechanics** (not the table) · RBAC (keys only) ·
`is_own_studentship` · Teaching Assignment service for marks authority · `student_class_enrollments` for
cohort · `class_subjects` (already models electives) · `AcademicSettings` for policy · `parse_workbook` ·
the attendance correction vertical as the marks-lock precedent.

---

## What must change first

| Fix | Why | Cost |
|---|---|---|
| **`roll_number` → `student_class_enrollments`** | It is a lifetime field on `students`. Historical report cards would print today's roll number; answer sheets keyed on it mis-file | Migration + back-fill + cache guard |
| **Rename `grades.*` → `assessment.*`** | 7 dead keys already granted to Teacher and Student, never enforced, **one letter from the live `grade.*` master**. `has_permission` resolves `.manage` on the string prefix, so a typo silently grants or denies and the key-existence test cannot catch it | Catalogue + revoke migration (`seed_roles_for_tenant` only ever adds) |
| **Leave `academic_result` alone** | Single overwritten `String(20)`, no year dimension (debt 14d). Examination must not extend it | Decision only |
| **`subjects.default_grading_scale_id`** | Ghost column — no table, no FK, no reader anywhere | Make real or drop |

---

## What must be built

`examinations` · `exam_papers` · `exam_marks` · `grading_schemes` + `grading_bands` · `exam_results` ·
`exam_documents` · `examination_lifecycle_events`.

```
AcademicYear
  └── Examination                    the EVENT ("Half Yearly 2026-27")
        ├── ExamPaper                the SITTING (subject × class × date × maxima)
        │     ├── ExamMark           per student; status present|absent|exempted|malpractice
        │     └── ExamDocument       question paper, answer sheet
        ├── ExamResult               per student SNAPSHOT, versioned, immutable once published
        │     └── ExamDocument       report card PDF
        └── examination_lifecycle_events
```

---

## Jira problems

**Blocking**

1. **The Examination grain contradicts itself.** NXS-67 = 1 class + 1 subject; NXS-68 §8/§9 and NXS-73 =
   many subjects, many classes, 600 total marks. Both cannot be true. NXS-73's report card is
   **unbuildable** under NXS-67's model.
2. **Absence is inexpressible.** NXS-71 allows only "required, numeric, 0..max" — no absent, exempted or
   malpractice. NXS-72 then requires every student to have marks before publishing, which no real cohort
   satisfies.
3. **Parent portal contradicts ADR-011.** No Parent role, context or Account exists; the household shares
   the student login. Six stories assume otherwise.
4. **NXS-77 rebuilds architecture ADR-013 explicitly rejected**, and is the per-module permission system
   `authorization-domain.md` forbids.
5. **Grading is assumed but never specified** — auto-grade against a system that does not exist and no
   story creates.
6. **Report cards specified as mutable** ("regenerate when grading rules change") — a downloaded card
   silently changes.

**Serious:** "Class" and "Section" treated as separate (a Class **is** a section, ADR-012) · "Assessment"
introduced as a fourth undefined term with values identical to Exam Type · status mixes derived time facts
with decisions, and "Postponed" has no new-date field · "Pending Verification" is a state nothing enters ·
unpublish has no consequence management · roll number used as an identifier though nullable, non-unique and
non-historical · question-paper confidentiality unaddressed · ~90,000 answer sheets per cycle at trust scale
with no bulk path · **no story owns the model, lifecycle or grading**.

**Moderate:** second notification inbox and second calendar duplicate existing ones · NXS-76 restates four
other stories' rules · NXS-66's "Upcoming" card contradicts itself · Exam Code has no stated need · no
room/venue entity exists · version numbering rule undefined · delete-exam contradicts cancel-don't-delete ·
20 notification types with no audience mapping · ICS/Outlook export is a hidden integration.

**Absent entirely:** grace marks, practical/theory, supplementary/re-exam, moderation, re-evaluation,
weighted term aggregates, rank, hall tickets, seating, invigilation, answer-sheet retention.

---

## Critical decisions

| # | Decision | Recommendation |
|---|---|---|
| D1 | Examination grain | **Event + papers.** Forced by report cards |
| D2 | Examination vs `exam_window` | **Both.** Window = calendar time reservation; Examination = academic event; optional FK. Do not delete the window — it is a live shipped feature |
| D3 | Grading scope | **Tenant-wide in MVP**, structured for per-board later (blocked by the flat grade catalogue) |
| D4 | Status stored vs derived | **Store decisions, derive time facts** |
| D5 | Document abstraction | **New `exam_documents`, reusing `person_documents` mechanics** — ADR-015's `person_id` is NOT NULL |
| D6 | Marks permission namespace | **Rename to `assessment.*`** before use |
| D7 | Report card = marksheet or annual? | **Product must answer.** Build per-exam first, but call it a marksheet |
| D8 | Parent access | **Honour ADR-011**; re-confirm that the child sees everything |
| D9 | `academic_result` | **Leave legacy**, derive later |

D1, D2 and D5 warrant ADRs (ADR-016/017/018).

---

## Recommended MVP

**In:** the 7 new tables + roll-number fix · lifecycle (draft → scheduled → marks entry → published, plus
cancel and revise) · marks with absence, bulk import by admission number, lock + correction · tenant
grading schemes · result snapshot with publish/revise versioning · immutable versioned report card PDF (one
template) · question papers + answer sheets with release gate · exam layer on the **existing** calendar ·
**4** notification events on the **existing** stack · ~11 permission keys + Exam Coordinator profile ·
GraphQL-only for business ops, REST only for upload/download/PDF · 5 admin-web screens + 1 Expo result view.

**Out:** dashboard · separate exam calendar · separate notification centre · My Exam Documents portal ·
permission matrix UI · parent-specific access · ICS/Google/Outlook export · Exam Code · room master ·
practicals, grace marks, supplementary, moderation, rank.

---

## Recommended implementation order

```
EX-00  Architecture decisions + ADRs (D1–D9)        ← blocks everything
EX-01  Roll number becomes per-year                 ← cheap now, expensive after marks exist
EX-02  Grading schemes + bands
EX-03  Examination + ExamPaper model & lifecycle    ← the load-bearing decision
EX-04  Scheduling UI (fan one subject-set across sections)
EX-05  Marks entry (with absence, teacher scope via ADR-014)
EX-06  Bulk marks import
EX-07  Marks lock & corrections
EX-08  Result computation & publication (snapshot, versioned)
EX-09  Report card generation (immutable PDF)
EX-10  Exam documents (question papers, answer sheets)
EX-11  Permission keys (rename grades.* first)
EX-12  Calendar layer
EX-13  Notifications (4 events)
EX-14  Student result view (Expo + admin-web)
EX-15  Dashboard                                    ← Phase 2
```

Nothing user-visible until EX-04, and that is correct: this epic's risk sits entirely in the model.

**Do not start with NXS-66 (dashboard) or NXS-67 (create exam form).** Both encode the contradictory grain,
and the dashboard is a projection of a model that does not yet exist.
