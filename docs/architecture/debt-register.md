# Migration Debt Register — living document

> One rule: every temporary mechanism, dual-write, or known architecture
> violation is listed here with why it exists and what removes it. Reviews
> under `reviews/` are point-in-time; **this file is current**. When an item
> closes, move it to Closed with the migration or commit that closed it. When
> a new shortcut is taken, register it here in the same commit that takes it.

**Last updated:** 2026-08-08 (item 1 closed by migration 094; item 15 added)

**Sequencing (locked 2026-08-08):** Phase 0 canon cleanup → Phase 1
architectural debt → Phase 2 finish existing domain workflows → Phase 3
GraphQL pattern (Students pilot) → Phase 4 GraphQL expansion → Phase 5 new
modules (Examination first). New modules wait until Phases 0–3 are under
control.

---

## Open

| # | Debt | Why it exists | Exit |
|---|------|---------------|------|
| 15 | **Nested display names still read the login** — ~20 guarded `x.user.name` sites degrade to `null` / "A teacher" for account-less rows instead of reading `person.full_name`: serializers (`teachers/models.py` TeacherLeave, `attendance/models.py`, `student_leaves/models.py`, `timetable/models.py`, `schedule/models.py`), services (`attendance/services.py` ×5, `session_services.py`, `schedule/services.py`, `timetable_v2.py`, `class_teacher_assignments.py`, `class_subject_teachers.py`, `transport/services.py` incl. two CSV exports, `finance/pdf_service.py` receipt, `student_fee_service.py`, notification fallbacks in `constraint_services.py` / `student_leaves/services.py`). Each swap must also swap its eager load (N+1). | display copies predate the Person read cutover | with the attendance/timetable ADR-014 refactor (debt 2), which rewrites most of these sites anyway |
| 2 | **Attendance resolves teaching outside the ADR-014 service**: keys on `class_id` + `marked_by → users.id`; sessions carry `class_teacher_assignment_id` (class-teacher responsibility, not subject teaching) | attendance predates ADR-014 | Phase 1 attendance refactor — **before Examination exists**, or exams copy the wrong shape |
| 3 | **`classes.teacher_id` is an FK to `users.id`** — the class-teacher cache keys on a login, not the teacher (against ADR-001/ADR-013) | v1 column retained as cache | Phase 1, together with the attendance / teaching-assignment cleanup |
| 4 | **Two live timetable implementations**: `modules/timetable/` (mounted at `/api/timetable`) and `modules/academics/services/timetable_v2.py` | parallel build never reconciled | Phase 1: pick the canonical one, migrate consumers, delete the other |
| 5 | **Student family columns dual-written**: `father_*` / `mother_*` / `guardian_*` still read v1 columns while households exist | like-for-like switch shows some children a wrong parent name; Expo still reads the flat keys | M2 client work: Expo + admin-web speak household roles, then a migration drops the columns |
| 6 | **Authorization vocabulary still v1**: `has_permission` strings in 16 non-test files; no Capability / Business Action / Authority Profile models. (The *holder* migration is done — migrations 085–089. Do not redo it.) | vocabulary deferred when the holder moved | Phase 1 vocabulary migration |
| 7 | **`notification_recipients` and `hostel_gatepass_audit` carry no `tenant_id`** — scoped only through parent-row joins | built before the scoping rule hardened | Phase 1 tenant-scoping audit (tables, queries, jobs, resolvers, exports) |
| 8 | **`suggest_duplicates` is quadratic** — loads every person, ~65 s on a migrated 15k-student trust | correctness first | before People is called performance-complete (M5) |
| 9 | **`_bus_operational_warning`** issues ~1 query per bus (84 on the test trust) | bounded by fleet size | M5 leftover |
| 10 | **People merge and household management have no API surface** — CLI only | no consumer existed when built | with the admin screen / GraphQL work (Phase 3) |
| 11 | **Transport list pagination is opt-in**; clients still read whole arrays | a truncated array is indistinguishable from a complete one | M5: admin-web + Expo adopt the page, then the array goes |
| 12 | **`trial_ends_at` is never enforced**; no tenant invoice / receipt / dunning (`plans`, `tenant_usage` are scaffolding only) | commercial layer not built | Commercial module (Phase 5) — do not build billing on the current tenant lifecycle |
| 13 | **Employment-status change does not invalidate the permission cache** — a departure takes effect within the TTL (~120 s), not instantly | invalidation hooks only cover authority edits | Phase 1 authorization work |
| 14 | **`bulk_update_status` mutates student status directly** while the canon requires status change only through business workflows | the workflows (withdrawal, graduation, …) do not exist yet | Phase 2 student lifecycle — workflows replace the direct path |

---

## Closed (recent)

| Debt | Closed by |
|------|-----------|
| `students.user_id` / `teachers.user_id` NOT NULL — a student or teacher could not exist without a login (ADR-003/ADR-010's named v1 defect). Placeholder accounts (@student.placeholder, @teacher.school) no longer minted; create paths record the Person directly; lists/search/import/deletion handle the missing login. Also found and fixed in passing: create_student with an email had been broken since migration 089 (Student role granted instead of relationship-implied). | migration 094 + commits 9237928, 08a51b0 (2026-08-08) |
| Dual-written identity + employment columns | migration 090 |
| Authority held on the account (`user_roles`) | migration 089 |
| `class_teachers` triple ownership / `is_class_teacher` | migration 092 (ADR-014) |
| No school timezone; naive timestamps | migration 093 + `core/school_time.py` |
| Identity reading Academic to derive contexts (I1) | `people/relationships.py` + import-level test |

Full history and reasoning: `reviews/2026-08-05-foundation.md` (original
register), `reviews/2026-08-07-architecture-compliance.md` (current review).
