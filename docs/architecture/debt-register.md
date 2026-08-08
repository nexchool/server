# Migration Debt Register — living document

> One rule: every temporary mechanism, dual-write, or known architecture
> violation is listed here with why it exists and what removes it. Reviews
> under `reviews/` are point-in-time; **this file is current**. When an item
> closes, move it to Closed with the migration or commit that closed it. When
> a new shortcut is taken, register it here in the same commit that takes it.

**Last updated:** 2026-08-08 (items 1–4, 6, 7 and 13 closed — migrations 094–097; residuals registered as 2b, 4b, 6b–6d, 7b–7d, 13b)

**Sequencing (locked 2026-08-08):** Phase 0 canon cleanup → Phase 1
architectural debt → Phase 2 finish existing domain workflows → Phase 3
GraphQL pattern (Students pilot) → Phase 4 GraphQL expansion → Phase 5 new
modules (Examination first). New modules wait until Phases 0–3 are under
control.

---

## Open

| # | Debt | Why it exists | Exit |
|---|------|---------------|------|
| 15 | **Nested display names still read the login** — guarded `x.user.name` sites degrade to `null` / "A teacher" for account-less rows instead of reading `person.full_name`: serializers (`teachers/models.py` TeacherLeave, `attendance/models.py`, `student_leaves/models.py`, `timetable/models.py`, `schedule/models.py`), services (`attendance/services.py` marker names, `session_services.py`, `schedule/services.py`, `timetable_v2.py` teacher label, `transport/services.py` incl. two CSV exports, `finance/pdf_service.py` receipt, `student_fee_service.py`, notification fallbacks in `constraint_services.py` / `student_leaves/services.py`). Each swap must also swap its eager load (N+1). *(2026-08-08: the CTA/CST serializers and class/attendance class-teacher names now read Staff/Person.)* | display copies predate the Person read cutover | sweep with Phase 2 attendance workflows |
| 2b | **Mobile client sends the login id when naming a class teacher** (`client CreateClassModal`), and seeds its edit form from `class.teacher_id` expecting one. The server maps legacy login ids, so assignment works — but the modal's preselect no longer matches since the cache re-key. Fix = send/compare `teacher.id`, like admin-web already does. | two frontends disagreed on the id long before the re-key | with the next Expo release |
| 4b | **The Expo client is the only reader of `/api/timetable/*`** — two endpoints (`teachers/me/weekly`, `students/me/weekly`) kept alive for it after the timetable consolidation. They belong with the rest of the academics API; the prefix survives only because moving it breaks a shipped app. | client release cadence | fold into `/api/academics` with the next Expo release |
| 5 | **Student family columns dual-written**: `father_*` / `mother_*` / `guardian_*` still read v1 columns while households exist | like-for-like switch shows some children a wrong parent name; Expo still reads the flat keys | M2 client work: Expo + admin-web speak household roles, then a migration drops the columns |
| 6b | **~1043 `subadmin:<uuid>` roles accumulate and are never reaped.** Each sub-admin owns a private `Role` (`is_subadmin=True`) holding their permissions — per-user permission sets implemented as roles, the shape ADR-006 argues against. `delete_sub_admin` now withdraws the authority, but the Role and its `role_permissions` rows still remain, and `GET /api/rbac/roles` returns them intermixed with the school's real Authority Profiles (no `is_subadmin` filter). Also `_get_private_role` uses `.first()` with no ordering. | grew from a v1 shortcut | reap on delete + filter the roles list; revisit the shape when sub-admin UX is next touched |
| 6c | **31 seeded permission keys are never checked anywhere**, including a dead `grades.*` namespace (7 keys, granted to Teacher and Student) shadowing the live `grade.read`/`grade.manage`. Dead keys are harmless but they make the catalogue lie about what the product enforces. | accreted with the seed list | prune with the next RBAC touch; the new key test makes pruning safe |
| 6d | **`DEFAULT_ROLES` (`role_seeder.py`) and `ROLES` (`scripts/seed_rbac.py`) are duplicate definitions kept in step by hand.** Byte-identical today and now both covered by the key test, but nothing forces them to agree with each other. | two seeders, one truth | one should import the other |
| 7b | **Bulk `UPDATE`/`DELETE` are outside the ORM tenant scope entirely** (`core/database.py` returns before adding criteria for non-SELECT). Most call sites filter `tenant_id` explicitly; five key only on a parent id and are one refactor from a leak: `devices/device_service.py`, `people/service.py` (primary-contact stand-down), `sub_admins/services.py` (role permissions), `announcements/services.py` (revision prune), `academics/services/timetable_v2.py` (entry delete by version). | the scope only covers reads | add explicit `tenant_id` to each; consider a lint |
| 7c | **187 FK pairs can still legally cross tenants** — only `roles` and (since 097) `staff` carry `UNIQUE (tenant_id, id)`, so no composite guard can be declared against the other 40 parent tables. Verified 0 actual violations in live data. | needs a unique per parent table | opportunistic: add the unique + composite FK when touching a domain |
| 7d | **The identity map defeats `.get()` scoping after an unscoped load.** `core/authentication.py::load_without_tenant_scope` nulls the tenant to load `User`/`Session`; once cached, a later scoped `.get()` returns the row with no SQL. Guarded today by `_acts_outside_own_tenant`, and only those two models use it — a real bypass the moment a third does. | sign-in must find the account before the tenant is known | keep the helper limited to User/Session; assert it in review |
| 8 | **`suggest_duplicates` is quadratic** — loads every person, ~65 s on a migrated 15k-student trust | correctness first | before People is called performance-complete (M5) |
| 9 | **`_bus_operational_warning`** issues ~1 query per bus (84 on the test trust) | bounded by fleet size | M5 leftover |
| 10 | **People merge and household management have no API surface** — CLI only | no consumer existed when built | with the admin screen / GraphQL work (Phase 3) |
| 11 | **Transport list pagination is opt-in**; clients still read whole arrays | a truncated array is indistinguishable from a complete one | M5: admin-web + Expo adopt the page, then the array goes |
| 12 | **`trial_ends_at` is never enforced**; no tenant invoice / receipt / dunning (`plans`, `tenant_usage` are scaffolding only) | commercial layer not built | Commercial module (Phase 5) — do not build billing on the current tenant lifecycle |
| 13b | **Delegation expiry is felt within the cache TTL, not on the day.** Expiry is a property of the query (nothing reads a delegation outside its window), but the cached key list is a snapshot taken before it lapsed — so a delegate keeps the lent keys for up to ~120 s past the rollover. | the cache materializes a date-dependent answer | acceptable at 120 s; revisit if the TTL grows |
| 14 | **`bulk_update_status` mutates student status directly** while the canon requires status change only through business workflows | the workflows (withdrawal, graduation, …) do not exist yet | Phase 2 student lifecycle — workflows replace the direct path |

---

## Closed (recent)

| Debt | Closed by |
|------|-----------|
| `students.user_id` / `teachers.user_id` NOT NULL — a student or teacher could not exist without a login (ADR-003/ADR-010's named v1 defect). Placeholder accounts (@student.placeholder, @teacher.school) no longer minted; create paths record the Person directly; lists/search/import/deletion handle the missing login. Also found and fixed in passing: create_student with an email had been broken since migration 089 (Student role granted instead of relationship-implied). | migration 094 + commits 9237928, 08a51b0 (2026-08-08) |
| Attendance resolved teaching outside the ADR-014 service (legacy `classes.teacher_id == login` branches; hand-rolled dated CTA lookup; write-only `class_teacher_assignment_id` on sessions; unvalidated cross-tenant session markers). All attendance decisions now ask the Teaching Assignment service, dated with the session day; announcements, search, student-leaves and the timetable generator moved off the cache with it. | commit be63ce9 (2026-08-08) |
| Authorization vocabulary (register item 6) — **closed as not-work, then the real defects fixed.** ADR-013 had already rejected both halves of the request: building Capability/BusinessAction/AuthorityProfile tables (duplicating four working ones on the request path — ADR-012's error) and renaming the live tables (churn for vocabulary, not behaviour). Verified: of 446 decision sites passing 134 distinct keys, every argument is already a static literal or constant — callers never construct a key, so there is no leak to migrate. `authorization-domain.md` now opens with the ADR-013 mapping, so future audits stop reporting four missing models. What the survey did find, and what was fixed: employment-status change never invalidated the permission cache (ADR-013's own named trade-off); `delete_permission`, `suspend_sub_admin`, `restore_sub_admin` and `delete_sub_admin` all left cached or granted authority standing; and no test ensured a checked permission key exists, so a typo denied everyone silently and inconsistently. | commits 290eea6, ffbf12a (2026-08-08) |
| Tenant-scoping audit (register item 7). `notification_recipients` / `hostel_gatepass_audit` confirmed safe — every reader keys on a tenant-verified parent, and both are empty. The real findings were elsewhere: `__tenant_scoped__` was a flag nothing read, leaving `TenantAuditLog`, `SetupModuleEvent` and `DataPurgeLog` unscoped (now `TenantBaseModel`, flag deleted, return blocked by test); `authority_delegations` and the `staff` side of authority had no composite FK (migration 097); the announcement fan-out accepted foreign class ids and resolved them in a task where no scope applies (fixed at validation and at the query); GraphQL's tenant check moved from inside `me` to a `RequiresTenant` permission class. No confirmed live leak was found — the read path, including the paginated/column-only shape of the earlier incident, is covered. | migration 097 + commit 4767fd0 (2026-08-08) |
| Two live timetable implementations — `timetable_slots` + its own REST API, generator, conflict rules and config table, in parallel with the `timetable_versions`/`timetable_entries` backbone that migration 023 had already declared the source of truth. The backbone won (versioning, bell schedules, rollover, clock-time conflict detection; admin-web already used it exclusively). The one thing only the old surface had — a person's own weekly timetable — was rebuilt on the backbone at the same URLs. Also fixed: `seed_demo_data` wrote an `entry_status` no reader recognises, hiding 90% of the demo timetable. | migration 096 + commit cfe2fad (2026-08-08) |
| `classes.teacher_id` FK'd `users.id` — the class-teacher cache keyed on a login. Now keys on `teachers.id` (owner rows backfilled for cache-only class teachers first), FK `ON DELETE SET NULL` (repairing migration 018), CTA writers refresh the cache, `create_class` records the responsibility. Found in passing: both CTA/CST serializers crashed reading `teachers.employee_id` (dropped in 090) — now read Staff/Person. | migration 095 + commit be63ce9 (2026-08-08) |
| Dual-written identity + employment columns | migration 090 |
| Authority held on the account (`user_roles`) | migration 089 |
| `class_teachers` triple ownership / `is_class_teacher` | migration 092 (ADR-014) |
| No school timezone; naive timestamps | migration 093 + `core/school_time.py` |
| Identity reading Academic to derive contexts (I1) | `people/relationships.py` + import-level test |

Full history and reasoning: `reviews/2026-08-05-foundation.md` (original
register), `reviews/2026-08-07-architecture-compliance.md` (current review).
