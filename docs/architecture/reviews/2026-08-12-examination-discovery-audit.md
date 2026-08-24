# Examination — discovery & architecture audit

**Date:** 2026-08-12 · **Status:** pre-implementation discovery. Nothing built, nothing migrated, no Jira modified.
**Scope:** whole repository (server, admin-web, panel, client) + Jira epic NXS-65 and its 12 child stories.
**Source of truth:** the repository. Jira is the proposal under audit.

> **Location note.** This report was requested at `docs/audits/`. The repository's
> established location for point-in-time audits is
> `server/docs/architecture/reviews/` (see `2026-08-09-stabilization-audit.md`),
> and `server/docs/` is the only documentation canon (user decision, 2026-08-08).
> Filed here to follow that convention.

**Evidence labelling** (RULE 9): **FACT** = confirmed by reading code. **INFERENCE** = strongly implied.
**RECOMMENDATION** = my proposal. **UNKNOWN** = needs a decision or information I do not have.

---

## 1. Executive summary

**FACT — Examination is almost entirely greenfield.** Of **107 `__tablename__` declarations** across
`server/modules/` and `server/core/`, exactly **two** touch this domain:

| Table | What it actually is | Owner |
|---|---|---|
| `exam_windows` | A reserved *date range* on the academic calendar that timetable and events must avoid | `modules/academics/calendar/` |
| `grades` | The **grade-level master** ("Grade 9", "Std 1") — *not* grading scales | `modules/grades/` |

There is **no** marks table, **no** grading scale, **no** question paper, **no** answer sheet, **no** report
card, **no** assessment, and **no** examination entity. Verified by searching concepts, not filenames:
`obtained_marks`, `max_marks`, `passing_marks`, `question_paper`, `answer_sheet`, `report_card`,
`ReportCard`, `Assessment`, `GradingScale`, `grade_boundary` — **all return zero hits** in
`modules/`, `core/`, `scripts/` and `migrations/`.

**The single most important finding is not a gap — it is a modelling error in Jira.** The stories
contradict each other about what an Examination *is*:

- **NXS-67** models it as **one class + one subject + one date + one total marks + one passing marks**.
- **NXS-68 §8/§9** models it as **many subjects and many classes**, with "Total Marks must equal the sum
  of configured subject marks".
- **NXS-73** shows a report card headed *"Half Yearly Exam (Science)"* with **6 subjects and 600 total marks**.

These cannot all be true of one entity. Implementing NXS-67 literally produces six rows all named
"Half Yearly Exam" for one Grade 9 half-yearly, and then no entity exists that a report card or an
overall percentage can hang off. **This is the same one-concept-two-owners disease that Phases 1–2 of the
v2 refactor spent their entire budget curing** (`class_teachers` ×3, `students.class_id`, dual-written
identity columns). Building it in deliberately would be a regression in architectural discipline.

**Six further blocking findings**, each detailed below:

1. **The Parent portal is unbuildable as specified.** ADR-011 says the household **shares the student's
   login**; there is no Parent role, no Parent context, and no parent Account. Six stories specify parent
   features. (§10)
2. **NXS-77 (permission matrix UI) is architecture ADR-013 explicitly rejected**, and would be the
   per-module permission system `authorization-domain.md` forbids. (§10)
3. **A dead `grades.*` permission namespace already exists and is already granted** to Teacher and Student
   — 7 keys, never enforced anywhere, one letter away from the live `grade.*` master. (§10)
4. **`students.roll_number` is a lifetime field, not per-year** — historical report cards would print the
   student's *current* roll number. (§14)
5. **`academic_result` is a single overwritten `String(20)`** with no year dimension — it cannot hold a
   result history. (§14)
6. **`subjects.default_grading_scale_id` is a ghost column** — no table, no FK, no reader anywhere in any
   repo. Someone anticipated grading and stopped. (§14)

**Verdict: do not start coding.** Three architecture decisions (§22) must be made first, and the Jira
backlog needs restructuring (§21). The *infrastructure* Examination needs — documents, PDF, notifications,
calendar, authorization, tenancy, lifecycle events — is in good shape and should be reused nearly wholesale.

---

## 2. Current architecture relevant to Examination

**FACT.** Established by reading the code, not the docs.

### 2.1 Transports

| Concern | Transport | Evidence |
|---|---|---|
| Business reads | **GraphQL** (40 root queries) | `graphql_api/schema.py::_build_query_type` |
| Business writes | **GraphQL** (22 mutations) and migrating | `_build_mutation_type`; `docs/architecture/phase-g-write-migration.md` |
| Sign-in/out, refresh, password | REST (infrastructure by canon) | `modules/auth/routes.py` |
| Uploads / downloads / exports | REST (infrastructure by canon) | debt register 23, 29 |

**FACT.** `docs/architecture/graphql-conventions.md` binds any new module: §1 module owns its GraphQL and
the schema only composes; §2 every field declares what it requires; §3 paging walks by key (offset where no
stable key exists); §4 batching is synchronous — **async DataLoader does not work here** (sync WSGI +
sync SQLAlchemy); §5 refusals carry codes, not English; §6 the type is what a client renders; §7 one field,
one authority; §8 verify an empty grep before deleting a route.

**RECOMMENDATION.** Examination is a *new* module, so it has no REST legacy and no Expo consumer. It should
be **GraphQL-only for every business operation from day one**, with REST used only for file upload/download
and PDF/CSV export. This introduces no third pattern and creates zero dual-transport debt.

### 2.2 Tenancy

**FACT.** `core/database.py::_tenant_scope_execute` injects `tenant_id` into every ORM SELECT on a
`TenantBaseModel` subclass via `with_loader_criteria`. It has four documented fail-open exits: no request
context, non-SELECT (bulk UPDATE/DELETE), no resolved tenant, and not inheriting `TenantBaseModel`.

**FACT.** Every one of the 62 GraphQL root fields carries `IsAuthenticated` + `RequiresTenant` (verified by
introspecting the built schema, 2026-08-12); the only unguarded root is `graphqlStatus`, a wiring check that
echoes back what the caller sent.

**Consequence for Examination:** every new model **must** inherit `TenantBaseModel` (not `db.Model` with a
`tenant_id` column — that exact trap is recorded in the register as the `__tenant_scoped__` incident), and
every new field must carry the two guards. `tests/test_tenant_isolation_invariants.py::SCOPED_MODELS` must
gain each new table.

### 2.3 Academic spine

**FACT.** Per ADR-012, the v2 vocabulary maps onto existing v1 tables. **Never create `sections`,
`teaching_assignments` or `academic_enrollments`.**

| Canon concept | Actual table | Notes |
|---|---|---|
| Programme | `academic_programmes` | board: GSEB/CBSE/… |
| Academic Year | `academic_years` | organizational, not per-programme (ADR-009 corrected) |
| Grade | `grades` | **flat, tenant-wide catalogue**; `name` unique per tenant, `sequence` for order |
| **Section** | **`classes`** | a Class **is** a section — `section` is the label column ("A") |
| Medium | `mediums` | |
| Subject | `subjects` + `class_subjects` | `class_subjects` carries `is_mandatory`, `is_elective_bucket`, `academic_term_id` |
| **Teaching Assignment** | **`class_subject_teachers`** | effective-dated, primary/assistant |
| Class Teacher | `class_teacher_assignments` | carries `allow_attendance_marking` |
| **Academic Enrollment** | **`student_class_enrollments`** | per-year placement; `is_current` partial unique index |

**FACT — ADR-014 is binding and implemented.** Operational modules must resolve teaching through
`modules/academics/teaching_assignment.py` (which supports `on=<date>` historical resolution), **never** by
querying `class_subject_teachers` directly. `classes.teacher_id` and `students.class_id` are **performance
caches only**, guarded by `tests/test_caches_follow_their_owner.py`.

**Consequence for Examination:** "which teacher may enter marks for this paper" is a Teaching Assignment
question, dated to the exam date — not a lookup on a cache column.

### 2.4 Authorization

**FACT.** ADR-013 maps the canon onto existing tables: Authority Profile = `roles`, Permission Key =
`permissions.name`, Business Authority = `staff_authorities` (**held by the employment, not the account**),
Delegation = `authority_delegations`, Scope = `core/branch_scope.py`, decision =
`modules/rbac/services.py::has_permission`.

**FACT.** `has_permission` implements `<resource>.manage ⇒ any <resource>.*`
(`rbac/services.py:168-178`). One catalogue: `modules/rbac/catalog.py` (166 permissions + 4 default roles),
imported by both seeders. `tests/test_permission_keys_are_real.py` fails the build if a checked key is not
seeded.

### 2.5 Lifecycle / audit pattern

**FACT.** Two precedents exist and agree: `student_lifecycle_events` (migration 098) and
`staff_lifecycle_events` (migration 100). Both: append-only, event names taken from
`docs/architecture/business-events.md`, **a correction is a new event, rows are never edited**.

**RECOMMENDATION.** Examination history (Jira's "History" tab, NXS-68) is this pattern. Do not invent a
third shape.

---

## 3. Existing Examination-related implementation

### 3.1 `exam_windows` — production, calendar-owned

| Aspect | Finding |
|---|---|
| Model | `modules/academics/calendar/models.py:172` — `ExamWindow(TenantBaseModel)` |
| Table | `exam_windows`; index `idx_exam_windows_tenant_year` |
| Columns | `academic_year_id` (FK CASCADE), `name`, `exam_type`, `status`, `start_date`, `end_date`, `applicable_class_ids` (JSONB, null/empty ⇒ all classes), `description` |
| Docstring | *"A reserved examination date range; timetable/events should avoid it."* |
| Service | `calendar/services.py:211` list · `:300` create · `:329` update · `:359` delete · `:275` **overlap detection** |
| REST | `calendar/routes.py:331/352/367` — create/update/delete |
| GraphQL | `calendar/resolvers.py:265` `examWindows(academicYearId)` — read only |
| GraphQL type | `calendar/graphql/types.py:247` `ExamWindow`, mapper `:392` |
| Import/export | `import_services.py` (CSV template, `IMPORT_TYPES`), `export_services.py` (PDF/CSV/HTML sections) |
| Activity log | `exam_window_created` / `_updated` / `_deleted` |
| admin-web | `academics/calendar/page.tsx`, `ExamWindowFormDialog.tsx`, `calendarEntries.ts:146`, `CalendarActivityDialog.tsx`, `useExamWindows` |
| Expo | none |
| Production-ready? | **Yes** — complete vertical, in use |
| Reuse? | **Yes — as a calendar reservation. It is NOT an Examination.** |

### 3.2 `grades` — the grade-level master (a false friend)

**FACT.** `modules/grades/models.py:25`. Flat, tenant-wide: `name` unique per tenant among active rows,
`sequence` for order. Two FKs into it: `classes.grade_id`, `subject_contexts.grade_id`. **This is "Grade 9",
not "Grade A+".** GraphQL-only since 2026-08-10; **zero Expo files** reference it.

**FACT (from `2026-08-09-stabilization-audit.md` §6, still open):** a programme's grade span cannot be
expressed; graduation-as-highest-grade-of-programme cannot be derived; division hangs off the Class, not the
Grade; and one spelling wins per tenant, so "Std 10" (GSEB) and "Grade 10" (CBSE) are either one row or two
rows at the same level.

**Consequence for Examination:** grading *schemes* are commonly board-specific and grade-band-specific. A
tenant-wide flat grade catalogue means an Examination cannot say "this scheme applies to CBSE Grade 10"
without resolving §22-D3 first.

### 3.3 Everything else — confirmed absent

**FACT.** Zero hits across `modules/`, `core/`, `scripts/`, `migrations/` for: `obtained_marks`, `max_marks`,
`passing_marks`, `question_paper`, `answer_sheet`, `report_card`, `ReportCard`, `Assessment`, `GradingScale`,
`grade_boundary`, `class Mark`. No `/examinations` route in admin-web; no `exam` module in `client/modules/`.

**FACT.** `modules/subjects/models.py:47`:
```python
default_grading_scale_id = db.Column(db.String(36), nullable=True)  # future FK to grading_scales
```
Added by migration 023. **No `grading_scales` table exists, no FK constraint, and nothing in server,
admin-web, panel or client ever reads it.** A ghost column.

### 3.4 Reusable infrastructure — in good shape

| Need | What exists | Verdict |
|---|---|---|
| Document storage | `person_documents` + `document_types` (`modules/people/documents.py`, **ADR-015**): S3 object key, mime, size, `uploaded_by_user_id`, `view_url` indirection that **never exposes an S3 URL**; type vocabulary is seeded data, not an enum | **Reuse the mechanics; do not reuse the table** — see §11 |
| Older document table | `student_documents` (`modules/students/models.py:42`) — same shape, `DocumentType` **Python enum**, retains a dead `file_url` column | Pre-ADR-015. Do not extend |
| PDF | `weasyprint==68.1`; `modules/finance/services/pdf_service.py`, `modules/fees/services/pdf_service.py`, `calendar/export_services.py` (Jinja→HTML→PDF) | **Reuse the pattern.** Note: two fee PDF services already duplicate |
| Notifications | `NotificationType` enum + `NotificationChannel` (IN_APP/EMAIL/SMS/PUSH), `notification_dispatcher.dispatch(...)`, `Notification` + `NotificationRecipient` (per-user `status`, `read_at`), templates, Celery dispatch | **Reuse wholesale** |
| Audience targeting | `notification_targeting_service` — derives from **business relationships**, not role strings | **Reuse** |
| Calendar | `holidays`, `school_events` (`event_type`, `applies_to`, `academic_year_id`), `exam_windows`, `calendar_days`, terms; GraphQL reads; import/export/print | **Reuse — do not add a fourth event table** |
| Lifecycle history | `student_lifecycle_events`, `staff_lifecycle_events` | **Copy the pattern** |
| Correction/approval/lock | `attendance_corrections` + `correction_service` + `AcademicSettings.attendance_corrections_require_approval` / `attendance_lock_after_hours` | **Copy the pattern — this is the marks-lock precedent** |
| Bulk import | `bulk_student_import_service`, `bulk_teacher_import_service`, `parse_workbook` | **Reuse for bulk marks** |
| Feature gating | `requires_feature(key)` + `OPTIONAL_FEATURES` | **Use it** — examination is optional |
| Branch scope | `core/branch_scope.py` | **Mandatory** — multi-campus |

**FACT — one gap in reusable infra.** There is **no room/venue entity** anywhere outside
`hostel_rooms`. Jira asks for "Room 101" in NXS-67, NXS-68 and NXS-75.

**FACT.** `NotificationRecipient` has per-user `status` and `read_at` but **no per-user soft-delete
column**, so NXS-74's "Delete Notification (removes it only for the current user)" needs one.

---

## 4. Jira epic summary

**FACT.** Epic NXS-65 "Examinations Management Module" — 12 stories, all `To Do`. Scope: dashboard, upcoming
exams, exam details, question papers, answer sheets, marks entry, results, report cards, notifications, exam
calendar, student documents, permissions. Four roles named (Administrator, Teacher, Student, Parent), plus
Exam Coordinator, Principal and Custom Roles in NXS-77.

Stated user flow: Create Exam → Upload Question Paper → Exam Conducted → Upload Answer Sheets → Marks Entry
→ Publish Results → Generate Report Cards → Student & Parent Access → Notifications → Calendar Updated.

The epic is **screen-driven**: twelve stories map one-to-one onto twelve screens. **INFERENCE:** it was
written from a UI mockup set (each story links a design image). There is no story for the domain model, the
lifecycle, grading configuration, or the exam-to-academic-structure relationship — the four things that must
be decided first.

---

## 5. Story-by-story reconciliation

Requirement facets are labelled per the requested taxonomy: **A** functional, **B** UI, **C** data,
**D** workflow, **E** permission, **F** integration, **G** reporting, **H** notification, **I** assumption.

---

### NXS-66 — Examinations Dashboard

**1. Jira requirement.** Landing page: 5 stat cards (Upcoming, Previous, Results Published, Pending Marks
Entry, Unread Notifications), Upcoming Exams widget (5 rows), Recent Results widget (5 rows), 6 quick
actions. Refresh on academic-year change. *(A, B, G, I)*

**2. Existing implementation.** `modules/dashboard/service.py` and
`modules/academics/services/dashboards.py` exist for other domains. admin-web has a dashboard shell,
`useAcademicYears` global year selector, and `ROUTE_PERMISSIONS`. Nothing examination-specific.

**3. Current capability.** **COMPLETELY NEW** (the pattern exists; the content does not).

**4. Reusable.** Dashboard aggregate pattern; the `/api/transport/dashboard` lesson (104 queries → 15) is
the cautionary precedent — compute from data read once, never per-row.

**5. Missing.** Every counter, because every underlying entity is missing.

**6. Architectural concerns.** "Pending Marks Entry = count exams where one or more assigned teachers have
not completed marks entry" requires a **per-paper marks-entry completion state**. That is a domain
requirement smuggled into a dashboard story. If the model has no such state, this card cannot be computed.

**7. Product concerns.** "Upcoming Exams" subtitle says **"Next 30 Days"** but the calculation says
**"exam date ≥ today"** — unbounded. Contradiction inside one card. Two cards ("Previous Exams" = end date
passed) imply an Examination has an **end date**, which NXS-67's single-date model does not provide.

**8. Recommendation.** **Build last, not first.** A dashboard is a projection of a settled model. Defer to
Phase 2.

**9. Dependencies.** Every other story.

**10. Grooming.** **Move to Phase 2 and rewrite** once the model is fixed.

---

### NXS-67 — Upcoming Exams

**1. Jira requirement.** List + search + filters (class, exam type, status, date) + create + edit +
pagination. Create form fields: Academic Year, Exam Name, **Exam Type, Class, Subject**, Date, Start Time,
End Time, Duration, **Total Marks, Passing Marks**, Room/Venue, Instructions, Status. On create: appears in
list, **auto-added to Academic Calendar**, notifications to assigned students and teachers. *(A, B, C, D, E, F, H)*

**2. Existing implementation.** Nothing. Adjacent: `exam_windows` create/update (calendar), `classes` and
`subjects` GraphQL reads, `academic_years`, the students list as the paging/filtering precedent
(`_student_list_query`, keyset + offset dual mode).

**3. Current capability.** **EXISTS BUT WRONG MODEL.**

**4. Reusable.** The list-with-filters pattern from `modules/students/` (one query builder shared by every
transport); `Class.display_name` for labels; `requires_feature`; `SetupComplete`.

**5. Missing.** The Examination entity itself, its scheduling children, its status machine.

**6. Architectural concerns — this is the critical one.**

- **`Class` + `Subject` as single-valued fields on the exam is the wrong grain.** In this codebase a
  **Class *is* a Section** (ADR-012). So "Class: Grade 10" is already ambiguous — is that 10-A, or 10-A and
  10-B, or Grade 10 across two programmes and two mediums? The demo tenant has **two classes both reading
  "1 A"** (GSEB English and GSEB Gujarati), which is exactly why `Class.display_name` carries a context line.
  A single `class_id` on an exam cannot express "the Grade 10 half-yearly", and a free-text "Grade 10"
  cannot be resolved to sections at all.
- **It contradicts NXS-68 and NXS-73** (many subjects, many classes, 600 total marks).
- **"Total Marks" and "Passing Marks" on the exam are per-paper facts**, not per-event facts. Different
  subjects routinely carry different maxima (theory 80 + practical 20). NXS-68's own validation — "Total
  Marks must equal the sum of configured subject marks" — concedes this.
- **"Auto-add to Academic Calendar"** without saying *which* table. Calendar already has three
  (`holidays`, `school_events`, `exam_windows`). Left unspecified, this becomes a fourth.
- **"Notifications to assigned students"** — audience must derive from enrollment via
  `notification_targeting_service`, not from a class string.

**7. Product concerns.** Status vocabulary `Upcoming | Completed | Cancelled | Postponed` mixes a **derived
time fact** (upcoming/completed are computable from dates) with a **decision** (cancelled/postponed). Only
the latter is state. This is precisely the `is_active`-vs-status lesson recorded in the canon. "Postponed"
also has no new date field — a postponed exam that cannot say *to when* is not a postponement.

**8. Recommendation.** Split into **Examination** (the event: name, type, academic year, programme scope,
status) and **ExamPaper** (the scheduled sitting: subject × class × date × time × max marks × pass marks ×
venue). This screen becomes "Examinations" (the event list); paper scheduling is its own screen. See §7.

**9. Dependencies.** §22-D1 (grain), D2 (exam vs window), D4 (status vs derived).

**10. Grooming.** **Split into three:** EX-02 Examination entity + lifecycle · EX-03 Paper scheduling ·
EX-04 Examination list UI. Remove "Total/Passing Marks" from the event form.

---

### NXS-68 — Exam Details

**1. Jira requirement.** Central hub: summary cards, Edit/Delete, six tabs (Overview, Question Papers,
Answer Sheets, Marks Entry, Notifications, History), schedule info, instructions, **Subjects & Marks table**,
**Assigned Classes table**, auto-generated unique **Exam Code**. Delete blocked if marks entered / results
published / exam completed. *(A, B, C, D, E)*

**2. Existing implementation.** Nothing. Adjacent: `class_detail` GraphQL (`modules/classes/resolvers.py`)
as the detail-page precedent; lifecycle-event tables for the History tab.

**3. Current capability.** **EXISTS BUT WRONG MODEL** — and **internally contradictory with NXS-67**.

**4. Reusable.** The detail-query precedent; `student_lifecycle_events` shape for History; branch-scope
asserts **in the service, not the route** (the register's explicit lesson: `assert_class_allowed` lived only
on a route and deleting it would have opened every class).

**5. Missing.** Everything.

**6. Architectural concerns.** The header reads *"Unit Test - 1 (Mathematics)"* — one subject — while §8
lists many subjects and §9 lists many classes. **The story contains both models simultaneously.** Its own
validation rule ("Total Marks must equal the sum of configured subject marks") only makes sense in the
multi-subject model, which means **NXS-67's form is wrong, not NXS-68's tables.** That asymmetry is the
clearest evidence for the recommended grain.

Delete-blocking rules are correct in spirit but should be **refusals from the service with codes**
(convention §5), not UI-only checks — a UI-only guard is bypassed by any other caller.

**7. Product concerns.** "Exam Code — unique and generated automatically" — no format, no uniqueness scope
(per tenant? per year?), and **UNKNOWN** whether schools need it at all. Real school exam codes usually come
from the board, not the software. Deleting an examination at all is questionable: the canon's pattern is
**cancel, don't delete** (cf. section merge keeping history, `person_merges` recoverability).

**8. Recommendation.** Rewrite as the Examination detail page for the **event**, with papers listed as
children. Replace Delete with **Cancel** (a lifecycle act that keeps history). Drop Exam Code from MVP
pending a real requirement.

**9. Dependencies.** D1, D4.

**10. Grooming.** **Modify + split** — the tabs are four separate stories, not one.

---

### NXS-69 — Question Papers

**1. Jira requirement.** Upload per examination, PDF/DOCX, max size configurable, **auto-versioning
(v1.0 → v1.1 → v2.0)**, version history retained, latest = active, view/download/replace/delete, search by
title and uploader. *(A, B, C, D, E)*

**2. Existing implementation.** `person_documents` (ADR-015) — S3 key, mime, size, uploader, `view_url`
indirection; `student_documents` (older); `announcement_attachments`. S3 helpers in
`modules/students/services.py`, `modules/announcements/services.py`. **No versioning exists in any of them.**

**3. Current capability.** **RELATED INFRASTRUCTURE EXISTS** (storage, access control, preview pattern);
versioning is **COMPLETELY NEW**.

**4. Reusable.** The whole storage vertical: S3 object key + `view_url` route + never returning a raw S3
URL. Tenant-embedded S3 key prefixes (already the practice).

**5. Missing.** An exam-document table, versioning, a release-to-students flag.

**6. Architectural concerns.**

- **A question paper is not a person's document.** `person_documents.person_id` is `NOT NULL` — a question
  paper belongs to a *paper*, not a human. Do **not** bend ADR-015 to fit; **reuse the mechanics in a new
  table** (§11).
- **Attaching papers to the Examination rather than the ExamPaper is wrong** under the multi-subject model:
  the Mathematics paper is not the Science paper. In NXS-67's single-subject model this bug is invisible,
  which is how a wrong grain propagates.
- **`v1.0 → v1.1 → v2.0` is unspecified** — nothing says what makes a bump minor or major. **RECOMMENDATION:**
  monotonic integers (v1, v2, v3). A version number nobody can predict is a support burden.

**7. Product concerns.** **A question paper is the single most confidentiality-sensitive object in this
module** and the story says nothing about pre-exam secrecy. "Students may view published question papers if
the school enables this feature" is the only control, and it is undefined. Missing entirely: who may
download *before* the exam, and whether an audit trail of pre-exam access is required. For a real school
this is the story's most important requirement and it is absent.

**8. Recommendation.** One `exam_documents` table (§11) covering papers, answer sheets and generated report
cards, with a `kind` discriminator, integer `version`, and an explicit `released_to_students_at`. Add
download audit for the question-paper kind.

**9. Dependencies.** D1, and §22-D5 (document abstraction).

**10. Grooming.** **Modify** — add confidentiality and release requirements; simplify versioning.

---

### NXS-70 — Answer Sheets

**1. Jira requirement.** Per-student scanned uploads (PDF/JPG/PNG), upload form takes **Student Name, Roll
Number, Class, Section, Subject**; search/filter; version history; students and parents see **only their
own**, and only after results published, if school enables. *(A, B, C, D, E)*

**2. Existing implementation.** Same storage infra as NXS-69. Self-access precedent exists and is correct:
`students/services.py::is_own_studentship(student, user)` resolves via `User.person_id → Student.person_id`,
**never** `students.user_id` (debt 27, closed).

**3. Current capability.** **RELATED INFRASTRUCTURE EXISTS**; the feature is **COMPLETELY NEW**.

**4. Reusable.** `is_own_studentship` — this is exactly the guard the story needs, and it already handles
account-less students. Storage vertical as above.

**5. Missing.** The table, the bulk-upload ergonomics, the release gate.

**6. Architectural concerns.**

- **The upload form is keyed on the wrong things.** "Student Name + Roll Number + Class + Section + Subject"
  is a *human* identifier tuple. The link must be to a `student_id` and an `exam_paper_id`. Roll numbers are
  nullable (`students.roll_number`), non-unique across sections, and (see §14) not per-year — keying uploads
  on them will mis-file answer sheets.
- **"Class" and "Section" as separate fields do not exist in this schema.** A Class *is* a section (ADR-012).
- **Scale.** 275 students × 6 subjects = 1,650 files per examination in a *small* demo tenant; a
  15,000-student trust is ~90,000 files per exam cycle. One-at-a-time upload with a manual student picker is
  not a workable interface, and the story specifies no bulk path. The list must paginate (register: a
  truncated list is indistinguishable from a complete one).

**7. Product concerns.** "Duplicate uploads should prompt to replace or create a new version" is a UI
decision standing in for a data rule. **Product decision needed:** is an answer sheet ever legitimately
re-uploaded, other than to correct a bad scan? If not, replacement should be an audited correction, not a
version.

**8. Recommendation.** Key on `(exam_paper_id, student_id)`. Provide bulk upload matched on **admission
number** (unique, permanent, org-wide) rather than roll number. Gate visibility on result publication +
`AcademicSettings`.

**9. Dependencies.** D1, D5, §14 roll-number decision.

**10. Grooming.** **Modify** — re-key the upload, add bulk, add pagination.

---

### NXS-71 — Marks Entry

**1. Jira requirement.** Per-student marks table (Roll No, Name, Obtained Marks, auto **Grade**, Remarks,
Save/Reset), filters (class, subject, **Assessment**), bulk import (Excel/CSV) with validation, tabs
(Enter Marks / Marks Status / Analytics), auto grade + pass/fail + percentage, edit until results published,
audit log. Validation: **"Required, numeric only, min 0, max Total Marks"**. *(A, B, C, D, E, G)*

**2. Existing implementation.** **Nothing.** No marks table anywhere. Adjacent and directly relevant:
`attendance_corrections` + `correction_service` (`request` / `approve` / `reject`, reason **required**,
rejected requests kept, `is_locked(session)` = finalized OR past the school's deadline), and
`AcademicSettings` as the per-school policy home.

**3. Current capability.** **COMPLETELY NEW.**

**4. Reusable.** The attendance correction/approval/lock vertical is a near-exact precedent and should be
copied rather than re-invented. Bulk import: `parse_workbook`. Teacher scoping: the ADR-014 Teaching
Assignment service, dated to the exam date.

**5. Missing.** Marks storage, grading computation, entry-completion state, locking.

**6. Architectural concerns.**

- **"Assessment Filter" introduces a fourth term** (Assessment) alongside Exam, Exam Type and Examination,
  never defined, with example values (`Unit Test`, `Half Yearly`, `Final Exam`) **identical to Exam Type**.
  Two names for one concept is what `naming-conventions.md` forbids. **This must be resolved before coding.**
- **Auto-grade requires a grading scale that does not exist** (§14). This story silently depends on an
  entire unbuilt subsystem.
- **`grades.create` / `grades.update` already exist as permission keys and are already granted to Teacher**
  — see §10. They have never been enforced.

**7. Product concerns — the most serious functional gap in the epic.** The validation rule *"Required,
numeric only, min 0, max Total Marks"* makes **absence inexpressible**. A student who did not sit the paper
is not a zero: zero fails them and drags the aggregate; blank is indistinguishable from not-yet-entered.
Every real school needs, at minimum: **Present-with-marks, Absent, Exempted, Malpractice**. Also missing:
grace marks, practical/theory split, optional subjects (a student who does not take Sanskrit must not appear
as missing), re-exam, and moderation. Without absence handling the module cannot be used for a real exam
cycle — this is not an edge case.

**8. Recommendation.** Model a mark as `(exam_paper_id, student_id)` with a **status** (`present`, `absent`,
`exempted`, `malpractice`) and a **nullable** `marks_obtained` that is required only when status is
`present`. Copy the attendance lock/correction machinery for post-publication edits.

**9. Dependencies.** D1, §22-D3 (grading), D6 (marks namespace rename).

**10. Grooming.** **Split into three** — marks storage + entry · grading computation · bulk import.
Add absence handling as an explicit acceptance criterion.

---

### NXS-72 — Results

**1. Jira requirement.** Result list with status (Draft / Published / Pending Verification), publish with
confirmation, **unpublish (admin)**, on publish: generate report cards, make results visible, notify, audit.
Validation: cannot publish until **all** students have marks. *(A, B, D, E, F, H)*

**2. Existing implementation.** Nothing. Publication precedent: none for results;
`announcements` has publish/revision semantics worth reading.

**3. Current capability.** **COMPLETELY NEW.**

**4. Reusable.** Lifecycle-event pattern for publish/unpublish audit; notification dispatcher.

**5. Missing.** Result computation, publication state, the aggregate entity.

**6. Architectural concerns.**

- **The results table is keyed by Exam + Class**, which again implies the event grain, contradicting NXS-67.
- **"Result Status" is being attached to the examination, but results are per-student.** Publication is an
  event-level act; a *result* is a student-level record. Conflating them means a single student's corrected
  result cannot be republished without republishing the cohort.
- **"Pending Verification" appears in the filter and the badge list but no workflow ever sets it.** A state
  with no transition into it is either dead or a missing requirement (compare `attendance_corrections`,
  where approval is an explicit configurable step).
- **"Cannot publish until all students have marks"** collides with the absent case — an absent student has
  no marks by definition. Without §NXS-71's status field, this rule blocks publication forever.

**7. Product concerns.** **Unpublish is specified with no consequence management.** Results and report cards
that students and parents have already seen and downloaded cannot be recalled. Real schools issue a
*corrected* result, they do not pretend the first never existed. This should be **revise-and-republish with
a visible version**, not a silent hide.

**8. Recommendation.** Publication is an act on the **Examination**; the artefact is a per-student
`exam_result` snapshot. Replace unpublish with **revise** (new version, audit trail, notification).

**9. Dependencies.** D1, D3, NXS-71 absence handling.

**10. Grooming.** **Modify** — split publish from result computation; replace unpublish with revise.

---

### NXS-73 — Report Card

**1. Jira requirement.** Per-student academic summary: student + exam info, performance cards (total,
obtained, percentage, overall grade), **subject-wise table**, overall summary, teacher remarks, Download PDF,
Print, signature/seal/approval block, generated timestamp. Auto-regenerates when results published, marks
modified, **grading rules change**, remarks updated, **student information updated**. *(A, B, C, G, E)*

**2. Existing implementation.** PDF: `weasyprint==68.1`, `finance/services/pdf_service.py`,
`fees/services/pdf_service.py`, `calendar/export_services.py` (Jinja → HTML → PDF, already produces
branded documents). Tenant branding exists (`/api/tenant-branding/*`). **No report card, no template
system, no signature storage.**

**3. Current capability.** **RELATED INFRASTRUCTURE EXISTS** (PDF, branding, storage); the feature is
**COMPLETELY NEW**.

**4. Reusable.** The Jinja→WeasyPrint pipeline; the calendar export service is the closest working model.

**5. Missing.** Report card entity, template, signature/seal assets, aggregate computation.

**6. Architectural concerns — this story proves the modelling error.** Its header says
*"Half Yearly Exam (Science)"* while its body shows **six subjects and 600 total marks**. Under NXS-67's
one-subject exam, this report card **cannot be produced at all**: there is no entity spanning six subjects.

**The regeneration rules are architecturally wrong.** "Regenerate when grading rules change" + "PDF and
printed versions must match the on-screen report card exactly" means **a report card a parent downloaded in
August silently says something different in December.** A published report card is a **statement the school
made on a date**. It must be an **immutable snapshot**; a change produces a *new version* that says so.
This is the same principle already applied in `attendance_corrections` (the previous value is kept) and
`person_merges` (a full snapshot for recoverability).

**7. Product concerns.** "Overall Grade" and "Percentage" across subjects with different maxima are
under-specified — is it a simple sum, weighted, best-of-N, or does a failed subject cap the aggregate? Boards
differ sharply here. Also: **a report card normally spans the year (all terms), not one examination.** This
story models a per-examination report card, which most Indian schools would call a *marksheet*. Real report
cards additionally carry attendance, co-scholastic grades and conduct. **UNKNOWN — needs a product decision.**

**8. Recommendation.** Immutable, versioned snapshot generated **on publication**, stored as a document,
with the computed figures frozen into the row. Never recompute a published card.

**9. Dependencies.** D1, D3, D7 (report card scope: exam vs term vs year).

**10. Grooming.** **Split** — aggregate computation · PDF template/branding · publication & versioning.
Add the marksheet-vs-report-card product decision as a blocker.

---

### NXS-74 — Notifications

**1. Jira requirement.** Examination notification centre: type filter, class filter, mark-all-read,
list with read/unread, per-user delete, deep links per type, ~20 auto-generated event types, delivery via
In-App/Email/SMS/Push, configurable templates. *(A, B, E, F, H)*

**2. Existing implementation.** **Substantially exists.** `NotificationType` (closed Python enum),
`NotificationChannel` (IN_APP/EMAIL/SMS/PUSH), `notification_dispatcher.dispatch(...)`, `Notification` +
`NotificationRecipient` (per-user `status`, `read_at`), `notification_templates`, Celery dispatch
(`tasks/notification_dispatch.py`, `tasks/push_notifications.py`), retention job, and
`notification_targeting_service` deriving audiences from **business relationships**.

**3. Current capability.** **FULLY EXISTS** as infrastructure; examination *event types* are new.

**4. Reusable.** All of it. This story should be ~90% configuration.

**5. Missing.** ~20 `NotificationType` enum members + templates; a per-user delete column on
`NotificationRecipient`; deep-link targets.

**6. Architectural concerns.**

- **This must not become an examination-specific notification centre.** The app already has
  `admin-web/.../notifications` and `client/modules/notifications`. A second inbox scoped to one module is a
  parallel system, and NXS-66's "Unread Notifications" card already reads the global count. **Filter the
  existing inbox by type; do not build a new one.**
- `NotificationType` is a **closed enum**, so ~20 additions are a code change plus template seeding, in the
  shape debt 6d warned about (two hand-synced catalogues). Add them to `modules/rbac/catalog.py`'s sibling
  pattern — one definition, both consumers.

**7. Product concerns.** Twenty notification types for one module is **notification fatigue by design**.
"Marks Entry Started" and "Question Paper Updated" are of no interest to a parent. Audiences per event type
are unspecified. **RECOMMENDATION:** MVP ships **four** — Exam Scheduled, Exam Rescheduled/Cancelled,
Results Published, Report Card Available — and adds more on evidence.

**8. Recommendation.** Reuse entirely; add event types and templates; extend the existing inbox with a
module filter.

**9. Dependencies.** The events only exist once the lifecycle (§8) is settled.

**10. Grooming.** **Reduce and merge** — this is not a screen story, it is a set of events attached to the
lifecycle stories. Delete the screen; keep an "examination notification events" story.

---

### NXS-75 — Exam Calendar

**1. Jira requirement.** Monthly calendar of examinations with colour indicators (exam/holiday/result day),
event schedule panel per date, legend, **export to Google Calendar / Outlook / ICS / print**, auto-sync on
create/update/postpone/cancel, role-filtered. *(A, B, F, E)*

**2. Existing implementation.** **Substantially exists.** `modules/academics/calendar/`: `holidays`,
`school_events`, `exam_windows`, `academic_calendar`, `calendar_days`, `calendar_summary`; GraphQL reads
(`CalendarQuery.*`); import/export services producing **PDF, CSV and HTML**; admin-web
`academics/calendar/page.tsx` with `buildCalendarEntries({ holidays, examWindows, events, terms })` and
`CalendarActivityDialog`.

**3. Current capability.** **PARTIALLY EXISTS** — the calendar is real and already renders exam windows.

**4. Reusable.** The whole calendar vertical, including the existing exam-window rendering path.

**5. Missing.** Per-paper scheduling entries on the calendar; ICS/Google/Outlook export (**not present** —
current exports are PDF/CSV/HTML); result-publication day as an event type.

**6. Architectural concerns.** **Calendar ownership must not fork.** The canon's rule is one owner per
concept. Examination must **publish into** the existing calendar (or expose its papers for the calendar to
read), not maintain a parallel event store. The cleanest boundary: **Examination owns the schedule;
Calendar owns display** — the calendar reads exam papers the way it already reads holidays and windows.

**7. Product concerns.** A separate "Exam Calendar" screen duplicates the existing academic calendar screen.
Users will ask why exams appear on two calendars that can disagree. **RECOMMENDATION:** add an exam layer to
the existing calendar rather than shipping a second calendar.

**8. Recommendation.** Extend `calendarEntries.ts` with an exam-paper layer; add ICS export to the existing
export service if genuinely wanted (it is the only real new capability here).

**9. Dependencies.** D2 (exam vs window), D1.

**10. Grooming.** **Merge into the existing calendar** + one small ICS-export story. Remove the separate
screen.

---

### NXS-76 — My Exam Documents

**1. Jira requirement.** Student/parent document portal: tabs (Question Papers, Answer Sheets, Results,
Report Cards), filters, view/download, availability rules gated on publication, strictly own-documents-only.
*(A, B, E)*

**2. Existing implementation.** Self-access precedent: `is_own_studentship`, `student_for_user`
(both resolve through Person, ADR-001/003 — works for account-less students). `person_documents` has a
`view_url` indirection pattern. Expo has `client/modules/students`.

**3. Current capability.** **RELATED INFRASTRUCTURE EXISTS**; the screen is **COMPLETELY NEW**.

**4. Reusable.** `is_own_studentship` is exactly the required guard. The `view_url` never-expose-S3 pattern.

**5. Missing.** The aggregated document view and its availability rules.

**6. Architectural concerns.** This is a **read projection over three other stories** — it cannot be
specified independently, and its availability rules restate NXS-69/70/72/73. If those rules live in two
places they will drift. **Availability must be computed once, in the service, and this screen must call it.**

**7. Product concerns.** "Parents" — see §10; not deliverable as specified. Also: **the story is largely
redundant with a well-built student result view.** A student who can see their result can reach its
documents from there.

**8. Recommendation.** Fold into the student-facing result view. Do not build a separate portal in MVP.

**9. Dependencies.** NXS-69, 70, 72, 73; ADR-011 decision.

**10. Grooming.** **Remove from MVP**; re-open if a real need survives the result view.

---

### NXS-77 — Examination Permissions (Role-Based Access)

**1. Jira requirement.** A permission-matrix **screen**: pick a role (Administrator, Teacher, Student,
Parent, Exam Coordinator, Principal, Custom), toggle View/Create/Edit/Delete/Upload/Publish across 12
examination features, save/reset, audit every change. *(A, B, E)*

**2. Existing implementation.** A complete authorization domain: `modules/rbac/` (`catalog.py` — 166
permissions + 4 default roles), `roles` / `role_permissions` / `permissions`, `staff_authorities`
(authority held by **employment**, ADR-013), `authority_delegations`, `core/branch_scope.py`,
`has_permission` with `<resource>.manage ⇒ <resource>.*`, `POST /api/rbac/roles` for school-defined
profiles, and the sub-admin catalog as a deliberate safety boundary.

**3. Current capability.** **JIRA REQUIREMENT CONFLICTS WITH ARCHITECTURE.**

**4. Reusable.** Everything. Examination needs **permission keys**, not a permission system.

**5. Missing.** ~8–10 new keys in `modules/rbac/catalog.py`, added to the appropriate default roles.

**6. Architectural concerns — this story should not be built.**

- `authorization-domain.md`: *"Authorization should remain centralized rather than allowing each module to
  create independent permission systems."* A per-module permission matrix is exactly that.
- **ADR-013 explicitly considered and rejected** building Capability/BusinessAction/AuthorityProfile
  structures — *"four tables duplicating four that exist and work… repeats precisely the error ADR-012
  records"*. The matrix in this story is that rejected model rendered as a screen.
- The **View/Create/Edit/Delete/Upload/Publish** grid is CRUD, which
  `authorization-domain.md` tells us to avoid in favour of business actions (*"Record Attendance",
  "Collect Fee", "Publish Report Card"*).
- **"Parent" and "Student" as configurable roles contradicts implemented behaviour**: a student's access is
  **relationship-implied** (`roles.implied_by_relationship`, migration 087), deliberately *not granted*, and
  there is no Parent role at all.
- **"At least one Administrator role must always retain full access"** and *"users should never assign
  permissions beyond their own authorization level"* are real invariants that the existing system already
  handles via the sub-admin catalog — reimplementing them per module invites a privilege-escalation bug.

**7. Product concerns.** The genuinely new roles — **Exam Coordinator** and **Principal** — are the useful
part, and they need no new screen: they are **Authority Profiles**, creatable today through
`POST /api/rbac/roles`.

**8. Recommendation.** **Delete this story.** Replace with: (a) add examination permission keys to
`catalog.py`; (b) seed Exam Coordinator as a system Authority Profile; (c) verify with
`tests/test_permission_keys_are_real.py` and `test_role_grants_are_honest.py`.

**9. Dependencies.** D6 (namespace naming).

**10. Grooming.** **Remove and replace** with a small "examination permission keys" story.

---

## 6. Existing domain model (as built)

```
Tenant (= Organization)
 └── SchoolUnit (Campus)              core/models.py, branch scope anchor
      └── Class  (= SECTION, ADR-012)  modules/classes/models.py
           ├── grade_id      → grades            (flat, tenant-wide catalogue)
           ├── programme_id  → academic_programmes (board)
           ├── medium_id     → mediums
           ├── academic_year_id → academic_years   (organizational, ADR-009)
           ├── teacher_id    → teachers   [CACHE ONLY, ADR-014]
           ├── merged_into_class_id → classes      (section merge, migration 102)
           │
           ├── ClassSubject          class_subjects   (is_mandatory, is_elective_bucket, term)
           │    └── ClassSubjectTeacher  = TEACHING ASSIGNMENT (effective-dated)
           │
           ├── ClassTeacherAssignment    (allow_attendance_marking)
           │
           ├── StudentClassEnrollment    = ACADEMIC ENROLLMENT
           │        (is_current partial-unique per student+year; NO roll_number)
           │
           └── AttendanceSession → AttendanceRecord → AttendanceCorrection

Person (People domain, ADR-001)
 ├── Account (users)         optional, max one   (ADR-003, migration 094)
 ├── Staff → StaffEmploymentPeriod → StaffAuthority → Role → Permission
 │        └── Teacher (academic participation, ADR-005)
 ├── Student  (admission number; students.roll_number ← LIFETIME, not per-year)
 │        └── student_lifecycle_events
 ├── FamilyMember (is_primary_contact)
 └── PersonDocument → DocumentType     (ADR-015)

AcademicYear
 ├── AcademicTerm
 ├── Holiday
 ├── SchoolEvent      (event_type, applies_to)
 ├── ExamWindow       ← the only examination-ish table today
 └── TimetableVersion → TimetableEntry → BellSchedule → BellPeriod
```

**Absent from this diagram, and that is the point:** Examination, ExamPaper, Mark, GradingScale, Result,
ReportCard, Room.

---

## 7. Proposed Examination domain model

**Derivation, not preference.** The grain is forced by three independent constraints:

1. **A report card needs an entity that spans subjects** (NXS-73: 6 subjects, 600 marks, one overall grade).
   NXS-67's one-subject exam provides none.
2. **A sitting needs its own schedule and maxima** — date, time, venue, max marks, pass marks all vary per
   subject, and NXS-68's own validation concedes it.
3. **The codebase's Class *is* a Section** (ADR-012), so "Grade 10's half-yearly" must fan out to several
   Class rows. A single `class_id` cannot express it; a free-text "Grade 10" cannot be resolved at all.

Therefore: **an Examination is an event; a Paper is a scheduled sitting of one subject for one section.**
This is also how schools speak — "the half-yearly" is one thing; "the Maths paper on Tuesday" is another.

```
AcademicYear
  └── Examination                        ← the EVENT ("Half Yearly 2026-27")
        · name, exam_type, status, programme scope
        · optional exam_window_id → exam_windows   (calendar reservation)
        · grading_scheme_id → grading_schemes
        │
        ├── ExamPaper                    ← the SITTING (subject × class)
        │     · class_id → classes (a section)
        │     · subject_id → subjects
        │     · exam_date, start_time, end_time, venue (text in MVP)
        │     · max_marks, pass_marks
        │     · status (scheduled / conducted / marks_locked)
        │     │
        │     ├── ExamMark               ← per student, per paper
        │     │     · student_id
        │     │     · status: present | absent | exempted | malpractice
        │     │     · marks_obtained (NULL unless present)
        │     │     · remarks, entered_by, entered_at
        │     │
        │     └── ExamDocument (kind = question_paper | answer_sheet)
        │
        ├── ExamResult                   ← per student, per EXAMINATION (snapshot)
        │     · totals, percentage, overall grade, pass/fail
        │     · published_at, version
        │     └── ExamDocument (kind = report_card)   immutable PDF snapshot
        │
        └── examination_lifecycle_events ← append-only history
```

### Why each new entity must exist

| Entity | Why it must exist |
|---|---|
| `examinations` | Nothing today can carry "the half-yearly" as one thing. Report cards, overall percentage, publication and notifications all attach here. Without it those are inexpressible. |
| `exam_papers` | Date, time, venue, max marks and pass marks all vary per subject and per section. Putting them on the examination forces one value where schools have many — the defect NXS-68 already trips over. |
| `exam_marks` | No marks storage exists anywhere (0 hits for `obtained_marks`/`max_marks`). The `status` column is what makes absence expressible, which NXS-71 cannot currently do. |
| `grading_schemes` + `grading_bands` | No grading exists; `subjects.default_grading_scale_id` is a ghost column pointing at a table nobody built. Auto-grade (NXS-71, 73) is impossible without it. |
| `exam_results` | A published result must be a **snapshot**, not a recomputation, or a downloaded report card silently changes (NXS-73). Also the only sane home for "overall grade". |
| `exam_documents` | Question papers and answer sheets are not person-owned, so `person_documents` (`person_id NOT NULL`, ADR-015) cannot hold them without breaking that ADR. |
| `examination_lifecycle_events` | NXS-68 asks for a History tab; the codebase already has this pattern twice. |

### Why each reused entity should be reused

| Reused | Why |
|---|---|
| `classes` (as section) | ADR-012. Creating `sections` is explicitly forbidden. |
| `student_class_enrollments` | Answers "who sits this paper" **as of the exam date**, including students who joined or transferred mid-year. `students.class_id` is a cache and must not be used. |
| `class_subjects` | Already knows which subjects a section takes, and carries `is_mandatory` / `is_elective_bucket` — the optional-subject edge case is already modelled. |
| `class_subject_teachers` via the ADR-014 service | The single owner of "who teaches this". Marks-entry authority must resolve through it, dated. |
| `exam_windows` | Already the calendar's reservation of examination time, with overlap detection and UI. |
| Notification stack | Complete and relationship-derived. |
| `weasyprint` + PDF services | Working branded-PDF pipeline. |
| RBAC | ADR-006/013. |
| `AcademicSettings` | Existing home for per-school policy (already holds attendance lock/approval policy). |

### Invariants

1. An `ExamPaper` belongs to exactly one Examination, one Class and one Subject.
2. `(examination_id, class_id, subject_id)` is unique among live papers.
3. `(exam_paper_id, student_id)` is unique among live marks.
4. `marks_obtained IS NOT NULL` **iff** `status = 'present'` (CHECK constraint).
5. `0 <= marks_obtained <= exam_papers.max_marks` (CHECK).
6. A published `ExamResult` is **never updated** — a revision inserts a new version.
7. An Examination's papers must all belong to the Examination's academic year.
8. Every table inherits `TenantBaseModel`; every FK pair stays within one tenant.
9. A student may only be marked on a paper for a class they were enrolled in **on the exam date**.

### Constraints & indexes

- Partial unique indexes in the house style (`postgresql_where=text("deleted_at IS NULL")`), matching
  `uq_attendance_session_class_day` and `uq_sce_current_per_student_year`.
- `idx_exam_papers_tenant_examination`, `idx_exam_papers_tenant_class_date`,
  `idx_exam_marks_paper_student`, `idx_exam_results_tenant_examination_student`.
- CHECK constraints on `status` vocabularies (closed business sets), following
  `staff.employment_status` — **not** on grading band labels, which are school data.
- **Scale check:** a 15,000-student trust × 6 subjects × 4 examinations ≈ **360,000 marks rows per year**.
  Marks entry must be paginated by paper (≈40 rows), never by examination, and result computation must be
  set-based SQL, not per-student Python.

### Tenant boundaries & audit

All new tables `TenantBaseModel`, registered in
`tests/test_tenant_isolation_invariants.py::SCOPED_MODELS`. Composite FKs where the parent carries
`UNIQUE (tenant_id, id)` (debt 7c). Audit via `examination_lifecycle_events` plus
`TenantAuditLog` for publish/unpublish/document-delete.

---

## 8. Examination lifecycle

**Not the ten states the brief offered.** Two independent things are being tracked and must not be
collapsed into one column: **the event's planning state** and **each paper's marking state**. Jira's
`Upcoming | Completed | Cancelled | Postponed` also mixes a derived time fact with a decision — the
`is_active`-vs-status lesson the canon already records.

**Examination (the event):**

```
DRAFT ──► SCHEDULED ──► IN_PROGRESS ──► MARKS_ENTRY ──► RESULTS_PUBLISHED
  │           │              │               │                  │
  └───────────┴──────────────┴───► CANCELLED │                  └─► REVISED
                                              └──► (back to MARKS_ENTRY on reopen)
```

`IN_PROGRESS` and `COMPLETED` are **derived from paper dates, not stored** — a stored "upcoming" flag goes
stale the moment a date passes and needs a cron to maintain. This mirrors ADR-013's delegation rule:
*expiry is a property of the query, not a cron*.

| State | Enter | Leave | Required data | Becomes immutable | Notification |
|---|---|---|---|---|---|
| DRAFT | `examination.create` | creator/admin | name, type, year | — | none |
| SCHEDULED | `examination.schedule` | admin/coordinator | ≥1 paper with date+maxima | papers' existence | ExamScheduled → affected students + teachers |
| MARKS_ENTRY | automatic once a paper's date passes | — | — | schedule (reschedule = explicit act) | MarksEntryOpened → assigned teachers |
| RESULTS_PUBLISHED | `examination.publish_results` | admin only | every paper locked; every enrolled student has a mark **or a non-present status** | **marks, results, report cards** | ResultsPublished → students; ReportCardAvailable |
| REVISED | `examination.revise_results` | admin only | reason **required** | previous version retained | ResultsRevised → affected students |
| CANCELLED | `examination.cancel` | terminal | reason required | everything | ExamCancelled → affected students + teachers |

**Per paper:** `SCHEDULED → CONDUCTED → MARKS_SUBMITTED → MARKS_LOCKED`, with corrections after lock going
through the attendance-correction pattern (request → approve → apply, reason required, rejected requests kept).

**Rescheduled** is not a state — it is an **act** that changes a paper's date and emits an event, exactly as
`transfer_section` is an act rather than a status. That keeps "postponed with no new date" impossible.

**Cancellation:** cancelling an Examination cancels its papers; marks already entered are **retained and
hidden**, never deleted (the section-merge precedent: history stays where it happened).

**Naming:** these must be added to `docs/architecture/business-events.md` in the same commit, not invented
in code — the rule `StudentTransferredOut` established.

---

## 9. Integration analysis

| Integration | Direction | Recommendation |
|---|---|---|
| **Academic Calendar** | Examination → Calendar | Calendar **reads** exam papers as a display layer (`calendarEntries.ts` already composes four sources). No new event table. Optionally link `Examination.exam_window_id` so a window and its papers agree. |
| **Timetable** | Examination ↔ Timetable | **UNKNOWN / product decision.** Exams displace normal periods. Timetable has clock-time conflict detection; exams currently would not participate. Out of MVP, but note the gap. |
| **Attendance** | Examination → Attendance | **Do not couple in MVP.** An exam-day absence is a fact about the paper (`ExamMark.status`), not an attendance session. Revisit later. |
| **Students** | Examination → Students | Cohort resolves through `student_class_enrollments` **as of the exam date**, never `students.class_id`. |
| **Teachers** | Examination → Academic | Marks-entry authority resolves through the ADR-014 Teaching Assignment service with `on=<exam_date>`. |
| **Notifications** | Examination → Notifications | Reuse the dispatcher; add ~4 types in MVP. |
| **Documents** | Examination → S3 | New `exam_documents` table reusing the storage vertical. |
| **Fees** | Fees → Examination | **Out of scope** — but note real schools gate hall tickets on fee clearance. Not in Jira; flagging it. |
| **`academic_result`** | Examination → Students | **Do not write to it** (§14). |

---

## 10. Authorization analysis

**FACT — a dead namespace already exists and is already granted.** `modules/rbac/catalog.py:83-88`:

```python
('grades.read.self',  'View own grades'),
('grades.read.class', 'View class grades'),
('grades.read.all',   'View all grades'),
('grades.create',     'Create grade entries'),
('grades.update',     'Update grade entries'),
('grades.manage',     'Full grades management access'),
```

Granted to **Admin** (`grades.manage`), **Teacher** (`grades.create`, `grades.update`, `grades.read.class`),
and **Student** (`grades.read.self`). **Never checked anywhere** — grepping the enforcement sites returns
nothing outside the catalogue and seeders. This is debt register item **6c**.

**This is a latent security hazard, not just dead weight.** The live grade-level master uses
`grade.read` / `grade.manage`; the dead marks namespace uses `grades.*`. **They differ by one letter, and
`has_permission` resolves `<resource>.manage ⇒ <resource>.*` on the *string* prefix** — so `grades.manage`
and `grade.manage` are entirely different authorities that look identical in review. A typo in either
direction is a silent grant or a silent 403, and `test_permission_keys_are_real.py` cannot catch it because
both keys exist.

**RECOMMENDATION.** Before Examination uses any of them, **rename the marks namespace** to something that
cannot be confused with the grade master — `assessment.*` (preferred: it also resolves NXS-71's undefined
"Assessment" term) or `marks.*`. Handle it exactly as migration 103 handled the teacher over-grant:
change `catalog.py`, then a migration that revokes the old keys from existing tenants, because
`seed_roles_for_tenant` **only ever adds**.

### Role mapping

| Jira role | Reality | Action |
|---|---|---|
| Administrator | `roles` "School Admin" | Grant new keys |
| Teacher | `roles` "Teacher", authority via `staff_authorities` | Grant entry keys; scope by Teaching Assignment |
| Student | **relationship-implied** (`roles.implied_by_relationship='student'`, migration 087) — deliberately not granted | Add read-own keys to the implied profile |
| **Parent** | **DOES NOT EXIST** — ADR-011: household shares the student's login; no Parent role, context or Account | **Blocker — see below** |
| Exam Coordinator | Not seeded, but creatable today via `POST /api/rbac/roles` | Seed as a system Authority Profile |
| Principal | Same | Seed |
| Custom Roles | Already supported | Nothing to build |

**The Parent problem (FACT).** ADR-011 records the decision: *"student and parent share ONE login by
default — no Parent role/context for now; the household uses the student's credentials."* The epic and six
stories specify parent-only views ("Parents should never have access to other students' documents"), which
under the current model are **the same session as the student's**. Every parent requirement in this epic is
either (a) already satisfied because the household shares the student view, or (b) unbuildable without
reversing ADR-011.

**RECOMMENDATION.** Treat "Parent" in Jira as meaning "the household, via the student login". Say so
explicitly in every story. Do not build parent-specific access; do not reverse ADR-011 for Examination.
Note the ADR's own stated cost applies here with force: **anything the account sees, the student sees** —
so a teacher remark intended for parents will be read by the child. That is a product decision worth
re-confirming before report cards ship.

### Proposed permission keys (MVP)

```
examination.read        examination.create      examination.update
examination.cancel      examination.publish     examination.revise
assessment.enter        assessment.read.class   assessment.read.self
exam_document.upload    exam_document.read.self
```

Defaults: Admin → `examination.manage` + `assessment.manage`; Teacher → `examination.read`,
`assessment.enter`, `assessment.read.class`, `exam_document.upload`; Student (implied) →
`examination.read`, `assessment.read.self`, `exam_document.read.self`.

Per convention **§7 (one field, one authority)**: reading an exam schedule and entering marks are different
authorities on different fields — **do not bundle**. And per the Phase-49 rule: **read the guard off the
route/field, never infer it from the module name.**

---

## 11. Document analysis

**FACT — three document stores already exist**: `person_documents` + `document_types` (ADR-015, current),
`student_documents` (older, Python-enum types, dead `file_url`), `announcement_attachments`.

**RECOMMENDATION — one `exam_documents` table, not three; and not `person_documents`.**

Reasoning: ADR-015's principle is that *a document about a human belongs to the human*. A question paper is
not about a human at all, and `person_documents.person_id` is `NOT NULL`. An answer sheet is about a
`(student, paper)` pair — the paper is essential context that `person_documents` cannot carry. Forcing exam
documents into it would either break the ADR or add nullable columns that only exams use.

So: **reuse the mechanics, not the table.**

```
exam_documents (TenantBaseModel)
  kind             question_paper | answer_sheet | report_card
  examination_id   nullable (report cards attach to the result)
  exam_paper_id    nullable (question papers, answer sheets)
  student_id       nullable (answer sheets, report cards)
  version          integer, monotonic
  is_current       boolean
  s3_object_key    unique          ← same pattern
  original_filename / mime_type / file_size_bytes
  uploaded_by_user_id
  released_at      nullable        ← the visibility gate
```

Carry over, unchanged: **never return a raw S3 URL** (serve through an authorised `view_url` route), tenant
prefix in the S3 key, `uploaded_by_user_id` nullable FK `ON DELETE SET NULL`.

**Open (UNKNOWN):** a retention/deletion policy. Answer sheets at trust scale are ~90,000 files per exam
cycle; nothing in Jira says how long they are kept. Storage cost and data-protection both need an answer.

---

## 12. Notification analysis

Covered in §5 (NXS-74). Summary: **reuse entirely**; add event types to the existing enum + templates in one
definition; extend the existing inbox with a module filter rather than building a second inbox; add a
per-user soft-delete column to `NotificationRecipient` if per-user delete is genuinely required.

**MVP events (4):** `ExamScheduled`, `ExamRescheduled`, `ResultsPublished`, `ReportCardAvailable`.
Add `ExamCancelled` and `MarksEntryOpened` (teachers only) in Phase 2. The remaining ~14 in Jira are
notification fatigue and should be justified individually.

Audience derives from `student_class_enrollments` and Teaching Assignments through
`notification_targeting_service` — **never** from a role-name string, which is the pattern that migration
089's audience work deliberately removed.

---

## 13. Calendar analysis

Covered in §5 (NXS-75). Summary: **the calendar exists and already renders exam windows.** Examination owns
the schedule; the calendar displays it. Add an exam-paper layer to `buildCalendarEntries`; do not create a
fourth event table and do not ship a second calendar screen. ICS/Google/Outlook export is the only genuinely
new capability in that story — current exports are PDF/CSV/HTML.

**§22-D2 must be decided first:** what `exam_windows` means once Examination exists.

---

## 14. Grading, marks and results analysis

### Grading — nothing exists

**FACT.** No grading scale, no bands, no boundaries, no pass rules. `subjects.default_grading_scale_id`
(migration 023) points at a `grading_scales` table that was never created and is read by nothing in any repo.

**RECOMMENDATION.** Build `grading_schemes` + `grading_bands` as **tenant data, not code**, per the canon's
"configuration, not forks" rule:

```
grading_schemes   (tenant, name, applies_to: percentage | marks, is_default)
grading_bands     (scheme, label "A+", min_value, max_value, grade_point, is_pass)
```

Attach a scheme at the **Examination** level in MVP (simple, and a school usually grades one exam one way),
with a later option to override per subject — `subjects.default_grading_scale_id` finally becomes real, or
is dropped. **Do not** hard-code A+/A/B+ (NXS-71 lists them as if fixed); boards differ, and a school
switching boards must not need a deploy.

**Blocked on §22-D3:** with the grade catalogue flat and tenant-wide (§3.2), a scheme cannot currently say
"CBSE Grade 10" without either programme-scoped grades or scheme-level programme scoping.

### Marks — nothing exists

Covered in §5 (NXS-71) and §7. The decisive gap is **absence**: Jira's "required, numeric, 0..max" makes
absent, exempted and malpractice inexpressible, and simultaneously makes NXS-72's "cannot publish until all
students have marks" unsatisfiable for any real cohort.

### `academic_result` — do not extend it

**FACT.** `modules/students/models.py:230` — `academic_result = db.Column(db.String(20), nullable=True)`.
Written by `students/services.py:1227`, validated max-length 20 (`student_schemas.py:163`), read by
`promotion_service.py:123` as `str(...).strip().lower() == "fail"`, and exposed in `to_dict` and
`routes.py:269` (`include_failed`).

So it is: a **single, free-text, overwritten** field with **no academic-year dimension**, used only to let
promotion skip failures. Registered as debt **14d** (*"no per-year record, so 'passed grade 5 in 2024-25'
cannot be answered"*), and promotion writes `enrollment_status="promoted"` even for students it classified
as repeating.

**RECOMMENDATION.** Examination must **not** write to `academic_result`. It should produce `ExamResult` rows
per examination, and the *annual* outcome should later be derived into `student_class_enrollments` (which
already has the year). `academic_result` should be **read-only legacy** until a follow-up migration
back-fills from `ExamResult` and drops it. Extending a 20-character free-text field to carry examination
outcomes is exactly the "casually extend a legacy field" trap this audit was asked to avoid.

### Roll number — a real defect that report cards will expose

**FACT.** `roll_number` is `modules/students/models.py:143` — a nullable integer on `students`. It is
**not** on `student_class_enrollments`. The canon states roll number is a property of the per-year placement
(*"Academic Enrollment (per-AY placement: division/grade/section + roll number)"*).

**Consequence.** A student's roll number changes when they change section or year, and the old value is
gone. A report card for last year's half-yearly, generated or regenerated today, prints **today's** roll
number. Answer sheets keyed on roll number (NXS-70) mis-file for the same reason, and roll numbers are not
unique across sections.

**RECOMMENDATION.** Add `roll_number` to `student_class_enrollments`, back-fill from `students.roll_number`
for current enrolments, keep the student column as a cache with a `test_caches_follow_their_owner`-style
guard, and **snapshot the roll number into `ExamResult`** so a published card never changes. **This is a
prerequisite, not a nice-to-have**, and it is not in Jira.

---

## 15. Report card analysis

**RECOMMENDATION: immutable snapshot, generated on publication, versioned.** Reasoning:

- **A report card is a statement the school made on a date.** Jira's "regenerate when grading rules change"
  plus "PDF must match the screen exactly" means a downloaded card and the on-screen card diverge the moment
  anything upstream changes — the school then has two different official documents with the same identity.
- The codebase already takes this position elsewhere: `attendance_corrections` keeps the previous value,
  `person_merges` stores a full snapshot for recoverability, `student_lifecycle_events` are never edited.
- Dynamic generation also re-runs aggregate computation on every view — at trust scale, per student, per
  view.

So: on publication, compute once, **freeze the numbers into `ExamResult`**, render the PDF, store it as an
`exam_documents` row with `kind='report_card'` and `version=N`. A correction publishes **version N+1** and
says so on the document. The screen renders the stored snapshot, never a recomputation.

**Infrastructure:** `weasyprint==68.1` is installed and working; `calendar/export_services.py` is the closest
working Jinja→HTML→PDF precedent; tenant branding exists.

**Missing and unbudgeted:** report-card **templates** (schools vary enormously and will demand their own
layout), signature/seal image storage, and — the bigger question — **§22-D7: is this a per-examination
marksheet or an annual report card?** NXS-73 describes the former while calling it the latter. Most Indian
schools mean the annual document, which aggregates several examinations plus attendance and co-scholastic
grades. Building the per-exam marksheet first is fine; **calling it the report card is what causes the
rework.**

---

## 16. Jira problems & ambiguities

Ordered by severity. Brutal by request.

### Blocking

1. **The Examination grain is contradictory across stories.** NXS-67 (1 class + 1 subject) vs NXS-68 §8/§9
   and NXS-73 (many subjects, many classes, 600 marks). Implementing either literally breaks the other.
2. **Absence is inexpressible.** NXS-71 permits only "required numeric 0..max". Absent, exempted and
   malpractice have no representation — and NXS-72 then requires all students to have marks before
   publishing, which such a cohort can never satisfy.
3. **The Parent portal contradicts ADR-011.** No Parent role, context or Account exists. Six stories assume
   one.
4. **NXS-77 rebuilds a rejected architecture.** ADR-013 explicitly declined this model;
   `authorization-domain.md` forbids per-module permission systems.
5. **Grading is assumed, not specified.** NXS-71 and NXS-73 both "auto-calculate grade" against a grading
   system that does not exist and that no story creates.
6. **Report cards are specified as mutable.** "Regenerate when grading rules change" destroys the integrity
   of an already-published document.

### Serious

7. **"Class" and "Section" treated as separate fields** (NXS-68 §9, NXS-70). In this schema a Class **is** a
   section. Every occurrence needs rewriting or it will produce a wrong data model.
8. **"Assessment" appears as a fourth undefined term** (NXS-71 filter) with values identical to Exam Type.
9. **Status vocabulary conflates derived facts with decisions** — `Upcoming`/`Completed` are computable;
   `Cancelled`/`Postponed` are decisions. And **"Postponed" has no new-date field.**
10. **"Pending Verification" (NXS-72) is a state nothing enters.** Either a missing approval workflow or dead.
11. **Unpublish (NXS-72) has no consequence management** for results and PDFs already downloaded.
12. **Roll number is used as an identifier** (NXS-70, 71, 73) but is nullable, non-unique across sections and
    not historical (§14).
13. **Question-paper confidentiality is unaddressed** in NXS-69 — the single most sensitive object here.
14. **Answer-sheet scale is unaddressed** — ~90,000 files per exam cycle at trust scale, with no bulk path.
15. **No story owns the domain model, lifecycle, or grading configuration.** Twelve screens, zero foundations.

### Moderate

16. **NXS-74 builds a second notification inbox**; one already exists and NXS-66 already reads its count.
17. **NXS-75 builds a second calendar**; the academic calendar already renders exam windows.
18. **NXS-76 is a read projection** whose rules restate four other stories — guaranteed drift.
19. **NXS-66's "Upcoming" card contradicts itself** ("Next 30 Days" vs "date ≥ today").
20. **Exam Code (NXS-68)** — no format, no uniqueness scope, no stated need.
21. **Room/venue has no entity anywhere** (only `hostel_rooms`). Free text or a new master — undecided.
22. **Version numbering `v1.0 → v1.1 → v2.0`** has no rule for major vs minor.
23. **"Delete Exam" contradicts the canon's cancel-don't-delete pattern**, and its own guard rules.
24. **Twenty notification types** with no audience mapping.
25. **ICS/Google/Outlook export** (NXS-75) is quietly a large third-party integration inside a UI story.

### Missing requirements (absent entirely)

Grace marks · practical/theory components · optional/elective subjects (though `class_subjects` already
models them) · supplementary and re-examination · moderation · re-evaluation requests · weighted aggregates
across terms · rank/position · hall tickets · seating · invigilation · exam-fee linkage · retention policy
for answer sheets · what happens to marks when a student transfers section mid-examination.

---

## 17. Edge cases

**MVP** = must work at first release. **P2** = next phase. **DECISION** = product must choose before either.

| Edge case | Verdict | Note |
|---|---|---|
| Student absent | **MVP** | `ExamMark.status='absent'`. Blocks publication otherwise |
| Student exempted | **MVP** | Distinct from absent for aggregates |
| Missing marks vs entered-zero | **MVP** | NULL + status, never 0 as a sentinel |
| Optional/elective subjects | **MVP** | `class_subjects.is_elective_bucket` exists; a non-taker must not read as missing |
| Different max marks per subject | **MVP** | On `exam_papers`, which is why the grain matters |
| Different pass marks per subject | **MVP** | Same |
| Student joins after examination created | **MVP** | Resolve cohort at **marks-entry time** from enrolment, not at creation |
| Student changes section mid-exam | **MVP** | Marks follow the **paper**; enrolment on the exam date decides |
| Student withdrawn/transferred out | **MVP** | Exclude from publication; keep marks already entered |
| Exam rescheduled | **MVP** | An act on the paper + notification |
| Exam cancelled | **MVP** | Lifecycle act; marks retained, hidden |
| Duplicate marks entry | **MVP** | Unique `(paper, student)` |
| Bulk marks upload | **MVP** | Match on **admission number**, not roll number |
| Marks edited after publication | **MVP** | Correction → approval → **revision**, never silent overwrite |
| Teacher changes mid-cycle | **MVP** | Teaching Assignment dated to exam date (ADR-014) |
| Class-level vs section-level exam | **MVP** | Papers per section; the UI may create them for a whole grade at once |
| Marks entry progress/completion | **MVP** | NXS-66 needs it |
| Practical + theory components | **P2** | Two papers with a combined rule, or components on one paper — **DECISION** |
| Grace marks | **P2** | Must be visible as grace, not folded into the mark |
| Supplementary / re-exam | **P2** | A linked Examination, not a second mark on the same paper |
| Multiple attempts | **P2** | Follows from re-exam |
| Failed subject → overall outcome | **DECISION** | Board-specific; also gates `academic_result` retirement |
| Result reopened after publication | **P2** | Revision versioning |
| Report card regeneration | **MVP (as versioning)** | Never in-place |
| Historical results across years | **P2** | Needs the roll-number and `academic_result` fixes |
| Academic year rollover | **P2** | Examinations do not roll over; results must remain readable |
| Rank / position in class | **DECISION** | Some boards forbid publishing it |
| Moderation / re-evaluation | **P2** | Real workflow, absent from Jira |
| Absent in one paper, present in others | **MVP** | Falls out of per-paper marks |
| Answer-sheet retention | **DECISION** | Cost and data protection |

---

## 18. MVP recommendation

**Principle: the smallest architecture that is still correct and extensible.** Everything below exists
because omitting it would force a schema change later, not because it is nice to have.

### MVP — in

- **Domain**: `examinations`, `exam_papers`, `exam_marks`, `grading_schemes`, `grading_bands`,
  `exam_results`, `exam_documents`, `examination_lifecycle_events`
- **Prerequisite fix**: `roll_number` on `student_class_enrollments`
- **Lifecycle**: draft → scheduled → marks entry → published, plus cancel and revise
- **Marks**: per-paper entry with present/absent/exempted/malpractice; bulk import by admission number;
  lock on publication; correction→approval for post-publication changes
- **Grading**: tenant-configurable schemes and bands; auto grade per subject and overall
- **Results**: computed snapshot per student per examination; publish; revise with version
- **Report card**: immutable versioned PDF snapshot on publication (one default template)
- **Documents**: question papers + answer sheets, integer versions, release gate
- **Calendar**: exam papers as a layer on the **existing** calendar
- **Notifications**: 4 event types on the **existing** stack
- **Authorization**: ~11 keys in `catalog.py`, Exam Coordinator seeded; **`grades.*` renamed first**
- **Transport**: GraphQL for all business ops; REST only for upload/download/PDF
- **Screens (admin-web)**: Examinations list · Examination detail with papers · Marks entry ·
  Results & publish · Report card view. Student result view in Expo.

### MVP — deliberately out

| Excluded | Why |
|---|---|
| Examinations **dashboard** (NXS-66) | A projection of a model that is not settled. Cheap once it is |
| Separate **exam calendar** screen (NXS-75) | Duplicates the academic calendar |
| Separate **notification centre** (NXS-74) | Duplicates the existing inbox |
| **My Exam Documents** portal (NXS-76) | Redundant with a good result view |
| **Permission matrix UI** (NXS-77) | Rejected architecture (ADR-013) |
| **Parent-specific access** | ADR-011 — no Parent identity exists |
| ICS / Google / Outlook export | Third-party integration hiding in a UI story |
| Exam Code | No stated need |
| Room/venue master | Free text in MVP; promote to an entity on evidence |
| Practical/theory split, grace marks, supplementary, moderation, rank | P2 — each needs a product decision |
| Timetable displacement, attendance coupling, fee gating | Not in Jira; genuine future scope |

### Phase 2

Dashboard · practical/theory components · grace marks · supplementary & re-exam · moderation and
re-evaluation · multiple report-card templates · historical results across years · rank · timetable
integration · richer notifications.

### Future

Question-paper authoring/banks · OMR/on-screen evaluation · analytics and predictive insight ·
board-result import · hall tickets, seating, invigilation.

---

## 19. Proposed re-groomed backlog

**Not the twelve screens.** Foundation first, then vertical slices that each ship something usable.

> Cross-cutting acceptance criteria for **every** story: new models inherit `TenantBaseModel` and are added
> to `SCOPED_MODELS`; every GraphQL field carries `IsAuthenticated` + `RequiresTenant` + its own authority
> (conventions §2, §7); guards read off existing routes, never inferred; refusals carry codes (§5); no N+1
> (guard test verified to fail without its fix); fresh-DB migration chain verified.

---

**EX-00 — Architecture decisions (spike, blocks everything)**
*Purpose:* close §22 D1–D7. *Scope:* three ADRs (grain; exam-window boundary; result & report-card
immutability) + written answers on grading scope, report-card scope, roll number, marks namespace.
*Acceptance:* ADRs merged to `docs/architecture/adr/`; `business-events.md` updated; debt register entries
opened. *Deps:* none. *API/DB/UI:* none. *Risk:* low; skipping it is the highest risk in the epic.

**EX-01 — Roll number becomes per-year** *(prerequisite fix)*
*Purpose:* a historical report card must print the roll number the student held then. *Scope:* add
`roll_number` to `student_class_enrollments`, back-fill, keep `students.roll_number` as a guarded cache.
*Acceptance:* cache-drift guard test; back-fill idempotent; fresh-DB chain verified. *DB:* migration.
*Risk:* medium — touches the student list sort and several screens.

**EX-02 — Grading schemes**
*Purpose:* auto-grade is impossible without it. *Scope:* `grading_schemes` + `grading_bands`, CRUD on
GraphQL, band-overlap and full-coverage validation, tenant default; decide the fate of
`subjects.default_grading_scale_id`. *Acceptance:* a school can define A+..F and a pass mark; overlapping
bands refused. *UI:* settings screen. *Risk:* medium — §22-D3 (board scoping) must be answered.

**EX-03 — Examination + ExamPaper model and lifecycle**
*Purpose:* the event/sitting grain. *Scope:* both tables, `examination_lifecycle_events`, status machine,
cancel and reschedule as acts, invariants as CHECK constraints. *Acceptance:* an examination with papers
across several sections and subjects; cancelling retains history; cross-year papers refused. *Risk:* high —
this is the decision everything else rests on.

**EX-04 — Examination scheduling UI**
*Purpose:* create an examination and its papers without one-by-one drudgery. *Scope:* list, detail, create
wizard that fans one subject-set across selected sections. *Acceptance:* Grade 10 half-yearly across 2
sections × 6 subjects in one pass. *UI:* admin-web. *Risk:* medium — UX carries the model's complexity.

**EX-05 — Marks entry**
*Purpose:* record what students scored. *Scope:* `exam_marks` with status; per-paper paginated entry; save;
teacher scope via ADR-014 dated service; cohort from enrolment on the exam date. *Acceptance:* absent
recorded without a mark; a teacher sees only their papers; ≤5 queries at 40 rows. *Risk:* medium.

**EX-06 — Bulk marks import**
*Purpose:* 40 rows × 6 subjects × 20 sections by hand is not viable. *Scope:* template download, match on
admission number, row-level errors, re-upload. *Deps:* EX-05. *Risk:* low — `parse_workbook` exists.

**EX-07 — Marks lock & corrections**
*Purpose:* a finalised mark must not change silently. *Scope:* copy the attendance correction vertical;
policy on `AcademicSettings`. *Acceptance:* post-lock edit refused with a code naming the correction path;
rejected requests retained. *Risk:* low — direct precedent.

**EX-08 — Result computation & publication**
*Purpose:* turn marks into an outcome. *Scope:* `exam_results` snapshot, aggregate + overall grade,
publish/revise with versioning, set-based SQL. *Acceptance:* absent students do not block publication;
revision creates v2 and retains v1. *Risk:* high — aggregation rules are board-specific.

**EX-09 — Report card generation**
*Purpose:* the document a parent keeps. *Scope:* Jinja→WeasyPrint from the **snapshot**, branding, stored as
`exam_documents`, versioned. *Acceptance:* republishing produces v2; v1 still retrievable and unchanged.
*Deps:* EX-08. *Risk:* medium — template variation is the usual scope sink.

**EX-10 — Exam documents (question papers & answer sheets)**
*Purpose:* the offline paper trail. *Scope:* `exam_documents`, upload/version/release, `view_url`
indirection, `is_own_studentship` for self-access, bulk answer-sheet upload by admission number.
*Acceptance:* a student reaches only their own; pre-release papers unreachable by students. *Risk:* medium —
confidentiality and volume.

**EX-11 — Examination permission keys**
*Purpose:* authority without a new permission system. *Scope:* **rename `grades.*` first** (catalogue +
revoke migration), add examination keys, seed Exam Coordinator. *Acceptance:*
`test_permission_keys_are_real` and `test_role_grants_are_honest` pass; no role loses access it needs.
*Risk:* medium — the rename touches seeded tenants.

**EX-12 — Calendar layer**
*Purpose:* exams appear where the school already looks. *Scope:* exam papers as a layer in
`buildCalendarEntries`; reconcile with `exam_windows` per EX-00. *Risk:* low.

**EX-13 — Examination notifications**
*Purpose:* tell people. *Scope:* 4 types + templates, audiences via `notification_targeting_service`.
*Risk:* low.

**EX-14 — Student result view (Expo + admin-web)**
*Purpose:* the household actually sees the result. *Scope:* published results, subject breakdown, report
card download; replaces NXS-76. *Deps:* EX-08, EX-09. *Risk:* low.

**EX-15 — Examinations dashboard** *(Phase 2)*
*Purpose:* overview. *Scope:* NXS-66 rewritten against the settled model, computed in ≤15 queries.
*Risk:* low once the model is fixed.

### Mapping from the current Jira

| Jira | Disposition |
|---|---|
| NXS-66 Dashboard | → **EX-15**, Phase 2, rewrite |
| NXS-67 Upcoming Exams | → **EX-03 + EX-04**; drop total/passing marks from the event |
| NXS-68 Exam Details | → **EX-03 + EX-04**; Delete → Cancel; drop Exam Code |
| NXS-69 Question Papers | → **EX-10**; add confidentiality; integer versions |
| NXS-70 Answer Sheets | → **EX-10**; re-key to `(paper, student)`; add bulk |
| NXS-71 Marks Entry | → **EX-05 + EX-06 + EX-07**; add absence handling |
| NXS-72 Results | → **EX-08**; unpublish → revise |
| NXS-73 Report Card | → **EX-09**; immutable snapshot; settle marksheet vs report card |
| NXS-74 Notifications | → **EX-13**; screen deleted |
| NXS-75 Exam Calendar | → **EX-12**; screen deleted |
| NXS-76 My Exam Documents | → **EX-14** |
| NXS-77 Permissions | → **EX-11**; matrix UI deleted |
| — | **EX-00, EX-01, EX-02** are new and block the rest |

---

## 20. Architecture decisions required before coding

| # | Decision | Options | My recommendation |
|---|---|---|---|
| **D1** | **Examination grain** | (a) 1 class + 1 subject (NXS-67) · (b) event + papers (NXS-68/73) · (c) event + papers + component | **(b)**. Forced by report cards; (a) cannot express them. (c) is P2 |
| **D2** | **Examination vs `exam_window`** | (a) replace window · (b) window = calendar reservation, Examination = academic event, optional FK · (c) Examination owns both | **(b)**. The window is a *time reservation* with overlap detection and live UI; the Examination is the academic event. Deleting the window breaks a shipped calendar feature |
| **D3** | **Grading scope** | (a) tenant-wide · (b) per programme/board · (c) per subject | **(a) in MVP, structured for (b)**. True (b) is blocked by the flat grade catalogue (stabilization audit §6) |
| **D4** | **Status: stored vs derived** | (a) store `upcoming/completed` · (b) store decisions, derive time facts | **(b)**. A stored time flag needs a cron and goes stale — the delegation-expiry precedent |
| **D5** | **Document abstraction** | (a) reuse `person_documents` · (b) new `exam_documents` reusing mechanics · (c) three tables | **(b)**. (a) breaks ADR-015 (`person_id NOT NULL`); (c) is what the brief forbids |
| **D6** | **Marks permission namespace** | (a) reuse dead `grades.*` · (b) rename to `assessment.*` | **(b)**, with a revoke migration. One letter from `grade.*` is a security defect waiting to happen |
| **D7** | **Report card scope** | (a) per examination (marksheet) · (b) annual, aggregating terms | **Product must answer.** Build (a) first but **name it a marksheet**; calling it a report card is what causes rework |
| **D8** | **Parent access** | (a) honour ADR-011 (household shares student login) · (b) reverse ADR-011 | **(a)**. Re-confirm the ADR's known cost: the child sees everything the parent does |
| **D9** | **`academic_result`** | (a) Examination writes it · (b) leave legacy, derive later | **(b)**. Debt 14d; a 20-char overwritten field cannot hold result history |

---

## 21. Top 10 risks

1. **Building NXS-67's grain.** Report cards then become impossible and the model must be rewritten after
   marks exist — the most expensive possible time. *Mitigate: D1 before any code.*
2. **Shipping without absence handling.** The module cannot run one real exam cycle; publication is blocked
   by its own validation rule. *Mitigate: status column in EX-05.*
3. **The `grades.*` / `grade.*` collision.** A one-letter typo silently grants or denies. Both keys exist,
   so the key-existence test cannot catch it. *Mitigate: rename in EX-11 before use.*
4. **Mutable report cards.** A document a parent downloaded changes later; the school has two official
   versions of one record. *Mitigate: snapshot + versioning in EX-09.*
5. **Roll-number drift.** Historical marksheets print today's roll number; answer sheets mis-file.
   *Mitigate: EX-01 before EX-09.*
6. **Answer-sheet volume.** ~90,000 files per cycle at trust scale with no bulk path and no retention
   policy. *Mitigate: bulk upload + a retention decision in EX-10.*
7. **Calendar/notification duplication.** Two calendars and two inboxes that can disagree — the exact
   one-concept-two-owners disease v2 just finished curing. *Mitigate: EX-12/EX-13 extend, never fork.*
8. **Scope creep through report-card templates.** Every school wants its own layout; this reliably consumes
   more than the rest of the module. *Mitigate: one template in MVP, D7 answered first.*
9. **Parent expectations.** Stakeholders have been promised a parent portal that the identity model cannot
   deliver. *Mitigate: D8 stated explicitly in every story now, not discovered at demo.*
10. **Grading scope reopening the grade catalogue.** Board-specific grading pulls in the unresolved flat
    grade-catalogue questions (programme span, graduation derivation). *Mitigate: D3 keeps MVP tenant-wide.*

---

## 22. Final recommendation

**1. How much exists?** Almost none of the domain — 2 of 107 tables, and one of those (`grades`) is a false
friend. But the *infrastructure* is strong: documents, PDF, notifications, calendar, RBAC, tenancy, lifecycle
events, bulk import, correction/approval/lock are all built and reusable.

**2. Reuse:** `exam_windows` (as a calendar reservation), the whole notification stack, the calendar,
WeasyPrint pipeline, `person_documents` *mechanics*, RBAC, `is_own_studentship`, the ADR-014 Teaching
Assignment service, `student_class_enrollments`, `class_subjects`, `AcademicSettings`, `parse_workbook`, and
the attendance correction pattern.

**3. Refactor first:** roll number per-year (EX-01) and the `grades.*` rename (EX-11). Both are small, both
become expensive after marks exist.

**4. Genuinely new:** Examination, ExamPaper, ExamMark, GradingScheme/Bands, ExamResult, ExamDocument,
examination lifecycle events.

**5. Wrong or incomplete in Jira:** the grain (NXS-67 vs 68/73), absence handling, parent access, the
permission matrix, grading-as-assumed, mutable report cards, plus ~19 further issues in §16.

**6. Decisions first:** D1–D9 (§20). D1, D2 and D5 warrant ADRs (ADR-016/017/018).

**7. Model:** §7 — `Examination → ExamPaper → ExamMark`, with `ExamResult` as a published snapshot and
`ExamDocument` for all three file kinds.

**8. MVP:** §18 — schedule, mark (with absence), grade, publish, report card, documents, on the existing
calendar/notification/RBAC stacks, GraphQL-only.

**9. Not in MVP:** dashboard, second calendar, second inbox, documents portal, permission matrix, parent
access, ICS export, exam code, room master, practicals/grace/supplementary/moderation/rank.

**10. Backlog:** §19 — 15 stories, foundation-first, replacing the 12 screen stories.

**11. Implement first:** **EX-00** (decisions/ADRs) → **EX-01** (roll number) → **EX-02** (grading) →
**EX-03** (model + lifecycle). Nothing user-visible until EX-04, and that is correct: this epic's risk is
concentrated entirely in the model.

**12. Risks:** §21.

---

*Prepared 2026-08-12. No code, migrations, branches or Jira changes were made. Evidence is repository state
at commit `70ab3a4`.*
