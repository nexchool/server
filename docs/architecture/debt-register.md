# Migration Debt Register — living document

> One rule: every temporary mechanism, dual-write, or known architecture
> violation is listed here with why it exists and what removes it. Reviews
> under `reviews/` are point-in-time; **this file is current**. When an item
> closes, move it to Closed with the migration or commit that closed it. When
> a new shortcut is taken, register it here in the same commit that takes it.

**Last updated:** 2026-08-08 — Phase 1 complete; Phase 2 complete; **Phase 3 COMPLETE**; **Phase 4 started** (Attendance: corrections surfaced, feature gate built). Phase 2 covered (student lifecycle, admissions, transfers, staff lifecycle, attendance corrections, section merge). Closed: 1–4, 6–8, 10, 13, 14, 14b, 14c, staff lifecycle (migrations 094–102). Residuals: 2b, 4b, 6b–6d, 7b–7d, 10b, 13b, 14d, 14e, 15. Phase 3: Students queries + lifecycle mutations built; conventions in `graphql-conventions.md`.

**Sequencing (locked 2026-08-08):** Phase 0 canon cleanup → Phase 1
architectural debt → Phase 2 finish existing domain workflows → Phase 3
GraphQL pattern (Students pilot) → Phase 4 GraphQL expansion → Phase 5 new
modules (Examination first). New modules wait until Phases 0–3 are under
control.

---

## Open

| # | Debt | Why it exists | Exit |
|---|------|---------------|------|
| 25 | **Most of Attendance is still REST, and the Expo client is why.** Migrated: corrections, and the student attendance read admin-web uses. Still REST: marking, sessions, `my-classes`, the class register, `/list`, `calendar-holidays`, and `/me` — the teacher's daily marking flow and the student's own view, all consumed by the shipped mobile app. Moving them means an Expo release, the same constraint as 4b. | mobile release cadence, not server work | migrate with the next Expo release, then delete each replaced route |
| 26 | **The v1/v2 split on student attendance survives.** `/student/<id>` reads the legacy attendance table, `/student/<id>/v2` reads register sessions; `/me` and `/me/v2` likewise. GraphQL exposes only the session shape, so the two REST versions now exist purely for Expo. Two answers to "was this child here" is one too many. | both shipped before the sessions model settled | delete the v1 pair when Expo moves to GraphQL |
| 22 | **A cursor is refused for orders whose key can be empty** — class, programme, roll number. Over a nullable, mutable key a cursor silently skips or repeats students, so the field raises instead and the client uses `offset`. Fine for a page-number UI; a future infinite-scroll client sorting by class would have no constant-cost path. | correctness beats a uniform API | if a client needs it: page those orders by `(key, admission_number)` with an explicit NULLS-LAST predicate |
| 23 | **`GET /api/students/export` is the last REST reader of the student query.** It stays because a file download is infrastructure, not a business operation — but it means `_student_list_query` still has two callers with different shapes, and the export's filters are parsed from a query string by hand. | downloads stay REST by the canon | leave until the export itself is revisited |
| 18 | **Section merge has no REST surface, and merged sections are still listed everywhere.** `merge_sections` is complete and guarded at the placement primitive, but unrouted; `get_all_classes` and the class pickers do not filter `merged_into_class_id`, so a retired section still appears as a choice even though placing into it is refused. | service built first | route it with the academics UI; filter pickers, keep merged sections visible in history views |
| 16 | **Staff attendance is not built.** The canon marks it "a future capability", so nothing was invented for it — the student attendance session/record shape may or may not fit staff, and guessing now would be the wrong kind of head start. | deliberately deferred by the canon | when a school actually needs it; decide then whether it reuses AttendanceSession or is its own thing |
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
| 9 | **`_bus_operational_warning`** issues ~1 query per bus (84 on the test trust) | bounded by fleet size | M5 leftover |
| 11 | **Transport list pagination is opt-in**; clients still read whole arrays | a truncated array is indistinguishable from a complete one | M5: admin-web + Expo adopt the page, then the array goes |
| 12 | **`trial_ends_at` is never enforced**; no tenant invoice / receipt / dunning (`plans`, `tenant_usage` are scaffolding only) | commercial layer not built | Commercial module (Phase 5) — do not build billing on the current tenant lifecycle |
| 13b | **Delegation expiry is felt within the cache TTL, not on the day.** Expiry is a property of the query (nothing reads a delegation outside its window), but the cached key list is a snapshot taken before it lapsed — so a delegate keeps the lent keys for up to ~120 s past the rollover. | the cache materializes a date-dependent answer | acceptable at 120 s; revisit if the TTL grows |
| 14e | **`POST /api/students` still admits directly, bypassing the application.** Both paths are legitimate — a school that walks a child in on day one should not have to file an application first — but nothing records which route a student arrived by, and admin-web only knows the direct one. | the direct path predates applications | decide whether direct admission stays a supported route or becomes "auto-approved application"; wire admin-web to applications either way |
| 14d | **`academic_result` is a single overwritten field** — there is no per-year record, so "passed grade 5 in 2024-25" cannot be answered. Promotion also records `enrollment_status="promoted"` even for students it classified as repeating. | added for a promotion filter, not as history | Phase 2 academic history, or with Examination (Phase 5) |

---

## Closed

**28 — the signed-in teacher is found through their employment (2026-08-08).**
`teachers.services.teacher_for_user` resolves account → Person → Staff →
Teacher (ADR-005). Used by `get_teacher_class_ids` (which the GraphQL
class-teacher scope reads), the attendance session helper, the schedule's
today view and the teacher profile. The sweep also found `subjects/
services.py` resolving BOTH a teacher and a student by account — the same
defect, missed by 27's narrower search. Neither `user_id` column is how the
app identifies anybody now; both survive as columns the creation flow
writes and a uniqueness check reads.

**27 — the signed-in child is found through their Person (2026-08-08).**
`students.services.student_for_user` / `is_own_studentship`, used by the
attendance `/me` and self-view checks (both versions), the student profile
`/me`, and the schedule's today view. `students.user_id` is no longer how
the app answers "who is signed in" — it survives as a column the creation
flow still writes and one uniqueness check still reads.

**24 and 10b — both review surfaces have screens (2026-08-08).**
`/attendance/corrections` and `/settings/duplicates`. Building them found
two things no test had: the types carried ids where a reviewer needs people,
and `mergePeople` reported success without committing — every merge through
the API had been a no-op since Phase 1.

**20 — optional modules are gated on GraphQL (2026-08-08).** `requires_feature`
reads the same per-tenant switch `@require_feature` does. Built with
Attendance, the first optional module to migrate, rather than speculatively
with Students — `student_management` is CORE, so a gate there would never
have fired. Reads are gated as well as writes: a module a school does not
have should not answer questions about itself.

**17 — attendance corrections have a surface (2026-08-08).** On GraphQL, not
REST: it is a business operation, and the canon puts those on one transport.
`requestAttendanceCorrection` / `approve` / `reject`, plus the pending queue
and one record's history. Asking needs `attendance.mark`; deciding needs
`attendance.manage` — no new permission key was invented for it.

**21 — the students list is on one transport (2026-08-08).** The GraphQL
list reached parity (five sort keys both ways, six search fields, campus /
programme / grade / gender / transport / admission-date filters, several
classes at once, page numbers via `offset`, the class-teacher scope) and
`GET /api/students/` is deleted. Both transports run one builder,
`_student_list_query`, so the CSV export and the list cannot drift; a test
compares them. `include_transport_summary` went with the route — no client
ever set it.

**19 — the lifecycle acts are on one transport (2026-08-08).** admin-web
performs all five over GraphQL; the REST routes `/withdraw`, `/graduate`,
`/re-enroll`, `/transfer-section` and `/transfer-out` are deleted (154 lines).
No test hit them — the workflow tests call the services. `GET /timeline`
stays until a screen reads a student's history over GraphQL. The student
**list** is a separate problem, registered as 21. (recent)

| Debt | Closed by |
|------|-----------|
| `students.user_id` / `teachers.user_id` NOT NULL — a student or teacher could not exist without a login (ADR-003/ADR-010's named v1 defect). Placeholder accounts (@student.placeholder, @teacher.school) no longer minted; create paths record the Person directly; lists/search/import/deletion handle the missing login. Also found and fixed in passing: create_student with an email had been broken since migration 089 (Student role granted instead of relationship-implied). | migration 094 + commits 9237928, 08a51b0 (2026-08-08) |
| Attendance resolved teaching outside the ADR-014 service (legacy `classes.teacher_id == login` branches; hand-rolled dated CTA lookup; write-only `class_teacher_assignment_id` on sessions; unvalidated cross-tenant session markers). All attendance decisions now ask the Teaching Assignment service, dated with the session day; announcements, search, student-leaves and the timetable generator moved off the cache with it. | commit be63ce9 (2026-08-08) |
| Admission had no application stage (item 14b) — `create_student` *was* admission, so a rejected or withdrawn applicant left no trace, which the canon forbids. `admission_applications` (migration 099) holds an applicant without presuming they will become a student: no Person, no admission number, no placement until approval. Approval is the only path to a student and goes through the ordinary admission path, links back, and records StudentAdmitted; rejection and withdrawal both keep the record and admit nobody. | migration 099 + commit 67a7b22 (2026-08-08) |
| Section merge did not exist and could not be expressed — `classes` had no status or deleted_at, so a section was live forever and deleting the absorbed one would have taken its attendance, marks and reports with it. `merged_into_class_id` + `merged_on` (migration 102) retire a section while keeping everything that happened in it; students move through the section-transfer workflow so each move is recorded on their timeline, and the placement primitive refuses anything new into a merged section. | migration 102 + commit 376188b (2026-08-08) |
| A finalised register could be silently overwritten by anyone holding `attendance.manage` — nothing kept what it said before, who changed it or why. `attendance_corrections` (migration 101) makes a change state itself, carry a reason, name its requester and, where configured, wait for approval; rejected requests are kept too. Locking gained its second half: a school can set how long after the day marks are still accepted, not just finalise by hand. Both policies default to existing behaviour. | migration 101 + commit 57be9b8 (2026-08-08) |
| Staff had no separation or return workflows — `end_reason` held one word and nothing recorded which of resignation, retirement or dismissal it was, on what date or why. resign / retire / terminate / give_notice / rejoin now exist; rejoining opens a second period against the same Staff per the canon. Also closed a canon requirement nothing implemented: **teaching now ends when employment ends**, so a class whose teacher left no longer reads as staffed. That rule lives in Academic — the People→Academic boundary test refused the first version, correctly. `staff_lifecycle_events` in migration 100. | migration 100 + commit 5776b77 (2026-08-08) |
| Section and school transfer were both `PUT /api/students/:id { class_id }` (item 14c). A section move now **modifies** the current enrollment per the canon instead of closing and reopening it — that had produced two placements for one academic year and stamped `promoted_from_enrollment_id` on a move that was not a promotion; the section left behind is kept by the SectionTransferred event. School transfer is its own workflow and keeps `transferred` distinct from `withdrawn`, with `StudentTransferredOut` added to business-events.md rather than invented in code. | commit 36c8e04 (2026-08-08) |
| Student status was a field anyone could set (item 14). Withdraw / graduate / re-enroll now exist as workflows that close the placement, set the status and record the event; both direct-mutation paths refuse lifecycle outcomes while still allowing markers like `leaving` in bulk. Found and fixed with it: graduates were never marked graduated by promotion and so were billed indefinitely; the billing exclusion list named a status nothing could write (`withdrawn`) while omitting one that could (`dropped_out`); and that list existed in two hand-synced copies, now one. `student_lifecycle_events` + a CHECK constraint on the status column arrived in migration 098. | migration 098 + commit f0b3b90 (2026-08-08) |
| People had no API surface (item 10) and its duplicate scan was unusable behind a request (item 8). The scan now reads columns instead of hydrating every person, honours `limit` while pairing, and skips values dozens of people share — 56.6 s → 0.40 s on 45,600 people, and it returns genuine matches instead of pairings of a placeholder phone. Merge and suggestions are exposed on GraphQL (`mergePeople`, `duplicateSuggestions`), which brought the schema's first Mutation root, a reusable `requires(<permission key>)` field guard, and a dedicated `person.merge` key. Household management needed nothing — it was already exposed through the student form. | commits 320e93b, d3bb715 (2026-08-08) |
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
