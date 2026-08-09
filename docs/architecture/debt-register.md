# Migration Debt Register — living document

> One rule: every temporary mechanism, dual-write, or known architecture
> violation is listed here with why it exists and what removes it. Reviews
> under `reviews/` are point-in-time; **this file is current**. When an item
> closes, move it to Closed with the migration or commit that closed it. When
> a new shortcut is taken, register it here in the same commit that takes it.

**Last updated:** 2026-08-09 — the Phase A stabilization audit
(`reviews/2026-08-09-stabilization-audit.md`) is worked through: 18, 33, 34, 37, 38,
39, 40 and 6d closed; 36 withdrawn as mis-diagnosed. "Phase 2 covered … section merge" below meant *built*, not *reachable* —
it is reachable now (see Closed).

2026-08-08 — Phase 1 complete; Phase 2 complete; **Phase 3 COMPLETE**; **Phase 4 started** (Attendance: corrections surfaced, feature gate built). Phase 2 covered (student lifecycle, admissions, transfers, staff lifecycle, attendance corrections, section merge). Closed: 1–4, 6–8, 10, 13, 14, 14b, 14c, staff lifecycle (migrations 094–102). Residuals: 2b, 4b, 6b–6d, 7b–7d, 10b, 13b, 14d, 14e, 15. Phase 3: Students queries + lifecycle mutations built; conventions in `graphql-conventions.md`.

**Sequencing (locked 2026-08-08):** Phase 0 canon cleanup → Phase 1
architectural debt → Phase 2 finish existing domain workflows → Phase 3
GraphQL pattern (Students pilot) → Phase 4 GraphQL expansion → Phase 5 new
modules (Examination first). New modules wait until Phases 0–3 are under
control.

---

## Open

| # | Debt | Why it exists | Exit |
|---|------|---------------|------|
| 41 | **A class is labelled two ways, and one of them is parsed by the shipped app.** `Class.display_name` joins grade and section with a space ("3 A") and is what every screen now uses; `Student._class_display_name` joins with a hyphen ("3-A") and feeds `class_name` on the student payloads. The same student sees both — "3 A" on their dashboard, "3-A" on their record. It cannot simply be unified: `splitClassName` in the Expo student list (`client/modules/students/components/StudentListItem.tsx`) reads up to the last hyphen as the grade and the rest as the section, so a space makes the section vanish from every row. | the label was composed independently in two places before `display_name` existed, and a client started parsing one of them | have Expo read `grade_name` and `section` as fields instead of taking a caption apart, then delete the hyphen form — the same gate as 25, 31 and 2b |
| 25 | **Most of Attendance is still REST, and the Expo client is why.** Migrated: corrections, and the student attendance read admin-web uses. Still REST: marking, sessions, `my-classes`, the class register, `/list`, `calendar-holidays`, and `/me` — the teacher's daily marking flow and the student's own view, all consumed by the shipped mobile app. Moving them means an Expo release, the same constraint as 4b. | mobile release cadence, not server work | migrate with the next Expo release, then delete each replaced route |
| 26 | **The v1/v2 split on student attendance survives.** `/student/<id>` reads the legacy attendance table, `/student/<id>/v2` reads register sessions; `/me` and `/me/v2` likewise. GraphQL exposes only the session shape, so the two REST versions now exist purely for Expo. Two answers to "was this child here" is one too many. | both shipped before the sessions model settled | delete the v1 pair when Expo moves to GraphQL |
| 22 | **A cursor is refused for orders whose key can be empty** — class, programme, roll number. Over a nullable, mutable key a cursor silently skips or repeats students, so the field raises instead and the client uses `offset`. Fine for a page-number UI; a future infinite-scroll client sorting by class would have no constant-cost path. | correctness beats a uniform API | if a client needs it: page those orders by `(key, admission_number)` with an explicit NULLS-LAST predicate |
| 31 | **The class, subject, student, holiday and timetable reads are on two transports at once, which the strategy forbids.** `GET /api/classes/`, `GET /api/classes/<id>`, the flat `GET /api/subjects/`, `GET /api/students/`, the three holiday reads, the two timetable reads, the teacher list, detail, subjects, availability, workload and leave queue, and the class-subject, subject-teacher and bell-schedule reads answer the Expo client while admin-web reads `classes` / `class` / `subjects` on GraphQL. Each REST route shares the GraphQL reader (`get_all_classes`, `class_detail`, `list_subjects_filtered`) and only reshapes it, so they cannot drift — but there are two shapes for one operation, and `legacy_detail_payload` exists solely to keep the mobile keys. | a shipped app calls them; deleting them broke it twice already | delete all of them with the Expo release that moves the mobile app to GraphQL — the same gate as 25, 2b and 4b |
| 32 | **`setupStatus` is a query that writes.** `get_status_payload` recomputes readiness and, when a school that had confirmed setup no longer qualifies, clears `is_setup_complete` and commits. GraphQL queries are meant to be side-effect free. The alternative is worse — a stored answer that goes stale, telling a school it is ready after it deleted its last class — so the behaviour is kept rather than changed underneath the screens. | the REST route always did this; the recompute is what keeps the flag honest | move the correction to a mutation or a job when setup is next touched, and let the query only read |
| 29 | **`GET /api/classes/export` is the last REST reader of the class query**, the same shape as 23. It keeps `_list_filters_from_request` alive to parse a query string by hand, and it is the only caller left of `get_all_classes` — every screen reads `classes_page`. | downloads stay REST by the canon | leave until exports are revisited as a whole; retire `get_all_classes` with it |
| 30 | **The class list offers no cursor at all** — every order it has is nullable (a class may have no grade), mutable (grade order, a label) or a count. Offset is honest here and cheap at a school's real size (hundreds of sections, not fifteen thousand children), but the structured pickers now make one request per hundred classes to read the whole structure. | no key is both unique and unchanging | if a trust ever makes this hurt, give the pickers a field shaped like what they actually want — the school's structure — rather than a cursor over a list |
| 23 | **`GET /api/students/export` is the last REST reader of the student query.** It stays because a file download is infrastructure, not a business operation — but it means `_student_list_query` still has two callers with different shapes, and the export's filters are parsed from a query string by hand. | downloads stay REST by the canon | leave until the export itself is revisited |
| 16 | **Staff attendance is not built.** The canon marks it "a future capability", so nothing was invented for it — the student attendance session/record shape may or may not fit staff, and guessing now would be the wrong kind of head start. | deliberately deferred by the canon | when a school actually needs it; decide then whether it reuses AttendanceSession or is its own thing |
| 15 | **Nested display names still read the login** — guarded `x.user.name` sites degrade to `null` / "A teacher" for account-less rows instead of reading `person.full_name`: serializers (`teachers/models.py` TeacherLeave, `attendance/models.py`, `student_leaves/models.py`, `timetable/models.py`, `schedule/models.py`), services (`attendance/services.py` marker names, `session_services.py`, `schedule/services.py`, `timetable_v2.py` teacher label, `transport/services.py` incl. two CSV exports, `finance/pdf_service.py` receipt, `student_fee_service.py`, notification fallbacks in `constraint_services.py` / `student_leaves/services.py`). Each swap must also swap its eager load (N+1). *(2026-08-08: the CTA/CST serializers and class/attendance class-teacher names now read Staff/Person. 2026-08-09: `teachers/models.py` TeacherLeave now reads Staff → Person, with the eager loads swapped to match — an account-less teacher was showing nameless in the leave queue, which migration 094 made possible.)* | display copies predate the Person read cutover | sweep with Phase 2 attendance workflows |
| 2b | **Mobile client sends the login id when naming a class teacher** (`client CreateClassModal`), and seeds its edit form from `class.teacher_id` expecting one. The server maps legacy login ids, so assignment works — but the modal's preselect no longer matches since the cache re-key. Fix = send/compare `teacher.id`, like admin-web already does. | two frontends disagreed on the id long before the re-key | with the next Expo release |
| 4b | **The Expo client is the only reader of `/api/timetable/*`** — two endpoints (`teachers/me/weekly`, `students/me/weekly`) kept alive for it after the timetable consolidation. They belong with the rest of the academics API; the prefix survives only because moving it breaks a shipped app. | client release cadence | fold into `/api/academics` with the next Expo release |
| 5 | **Student family columns dual-written**: `father_*` / `mother_*` / `guardian_*` still read v1 columns while households exist | like-for-like switch shows some children a wrong parent name; Expo still reads the flat keys | M2 client work: Expo + admin-web speak household roles, then a migration drops the columns |
| 6b | **~1043 `subadmin:<uuid>` roles accumulate and are never reaped.** Each sub-admin owns a private `Role` (`is_subadmin=True`) holding their permissions — per-user permission sets implemented as roles, the shape ADR-006 argues against. `delete_sub_admin` now withdraws the authority, but the Role and its `role_permissions` rows still remain, and `GET /api/rbac/roles` returns them intermixed with the school's real Authority Profiles (no `is_subadmin` filter). Also `_get_private_role` uses `.first()` with no ordering. | grew from a v1 shortcut | reap on delete + filter the roles list; revisit the shape when sub-admin UX is next touched |
| 6c | **31 seeded permission keys are never checked anywhere**, including a dead `grades.*` namespace (7 keys, granted to Teacher and Student) shadowing the live `grade.read`/`grade.manage`. Dead keys are harmless but they make the catalogue lie about what the product enforces. | accreted with the seed list | prune with the next RBAC touch; the new key test makes pruning safe |
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

**Links that pointed at pages which no longer exist (2026-08-09).** Debt 34, and
four more it did not know about. `TransitionComplete.tsx` linked to
`/dashboard/transport/enrollments`, where the screen is called `students`; four
"Back to academics" breadcrumbs pointed at `/academics`, the standalone hub
replaced by a collapsible sidebar group. Next reports none of this — a link to a
deleted page is not a build error, not a type error and not a lint error — so
`admin-web/src/lib/internalLinks.test.ts` now resolves every literal internal
href against the filesystem route tree, and fails any that points at a retired
redirect stub.

**The "80 uncalled service functions" were 10 (2026-08-09).** Debt 39, re-derived
before anything was touched, because closing 37 showed the original method was
wrong: it counted call sites (`name(` outside the defining file), which reports a
function imported under an alias as dead. `logout_user` scores zero that way and
is very much alive.

Re-derived by searching the raw identifier across 1,596 files in all four repos
plus infra. Of 541 public functions defined in module service files:

- **529** are referenced outside their own file — alive.
- **12** are referenced only by tests: built, tested, never routed. Left alone,
  and they are the honest form of debt 18's shape — a capability with no door.
  `delegate_authority`, `end_delegation`, `duplicate_unit_to_unit`,
  `apply_subject_contexts_to_classes`, `can_user_mark_session`, `parse_workbook`
  and six others.
- **47** are used only inside their own file. Not dead — module-private helpers
  that happen to lack a leading underscore. Renaming 47 functions across nine
  modules is churn with no behaviour change, so they stay; they are recorded here
  so the next audit does not count them as rot again.
- **10** were referenced nowhere at all, including their own file. Deleted.

Two of the ten announced themselves — `render_email_template` and
`send_email_old_signature` both open with "DEPRECATED". The rest:
`generate_token_pair`, `revoke_session`, `get_route_with_stops`, `update_stop`,
`get_student_document_by_id`, `list_active_tokens_for_user`,
`send_expo_push_batch` (the single-send sibling is what is wired).

**The eleventh was worth more than the other ten.** `cleanup_expired_sessions`
was dead, and its docstring said it "should be run periodically (e.g., via cron
job)". Nothing ever ran it, and nothing else pruned the table: notification logs
and audit logs each have a retention job, while `sessions` — a row per sign-in
per device, the table guaranteed to grow fastest — had none. Rather than delete
it, its body moved to `retention.purge_expired_sessions` on the nightly beat
schedule, as a bulk delete instead of loading every expired row into memory to
delete them one at a time.

**A school can open a section again (2026-08-09).** Debt 40. Adding a section
mid-year is school work, not operator work (user decision), so it lives in
admin-web.

The audit found the affordance was the smaller half. Two server rules stopped a
structured section being created at all:

- **The duplicate check read `name`.** Identity is
  `(tenant, campus, programme, grade, section, academic year)`, but the check was
  `(name, section, academic year)` — and `name` is empty for everything the
  structured builder makes, so it collapsed to `(section, year)` and refused the
  second Grade 1 A a school opens on another programme or campus. The demo school
  already has three such rows; the seeder made them, because `create_class` would
  have refused them.
- **The route demanded a name unless `grade_level` was set.** That is the older
  integer form; the structured form sends `grade_id`, so every section it tried
  to create came back "name is required". The rule is narrowed, not removed —
  with no grade at all there is nothing to compose a label from, so a name is
  still required.

`CreateSectionModal` asks for the identity a section actually has — campus,
programme, grade, section letter, medium, year — with campus and year defaulted
from the header, a preview of the label it will be listed under, and no `name`
field, since writing one is what produced the rows titled "— A".

Verified in the browser end to end: opening Grade 1 B on GSEB English, the exact
case the old check refused, created a section listed as "1 B".

**One permission catalogue, and seeding that works (2026-08-09).** Debts 38 and
6d, which turned out to be the same defect seen from two sides.

`modules/rbac/catalog.py` now holds the 166 permissions and the four default
roles. `scripts/seed_rbac.py` and `modules/rbac/role_seeder.py` both import it;
before, each carried its own copy of the roles, kept in step by a comment asking
whoever edited one to remember the other, so a tenant's authority depended on
which seeder had made it.

**The root cause was worse than the duplication.** `seed_rbac`'s role phase
called `create_role` and `assign_permission_to_role_by_name`, both of which
resolve the tenant off the request — so run as a CLI it failed on all four roles
with "Tenant context is required", printed four crosses, and exited 0. It has
therefore only ever created permission *rows*; every role grant came from
`seed_roles_for_tenant` on login. That silent half-failure is why each module
wrote its own backfill: the canonical seeder did not do the job it was named
for. It now seeds every active tenant from the catalogue, verified by revoking
`hostel.manage` from Admin and watching a reseed put it back.

Deleted, all redundant: `backfill_academic_calendar_permissions`,
`backfill_admin_finance_permissions`, `backfill_teacher_leave_permissions`,
`backfill_timetable_subject_permissions`, `grant_hostel_permissions`,
`seed_holiday_permissions`. Two of them were already generic — "create the
missing permission rows, then reseed" — under module-specific names. The last two
ran from `startup.sh` and the infra Makefile, so both were repointed rather than
just deleted. `fix_teacher_permissions` is **kept**: it repairs a teacher's
`StaffAuthority` link, which is a user→role problem, not a permission backfill.

`scripts/reseed_rbac.py` adds what seeding never had: `--dry-run` to report, and
`--reconcile` to revoke what the catalogue no longer grants. Without it, removing
a key changed nothing anywhere and taking one away needed a hand-written
migration (103). Reconciling is off by default and off on login — an operator's
hand-made grant should not vanish because somebody signed in — and it leaves
roles a school created itself alone.

One caveat found by running the dry run: it reported surplus `profile.*` grants
and a missing `person.merge`, which turned out to be the *pytest* database, not
the app's. Homebrew postgres owns `127.0.0.1:5432` and Docker binds `*:5432`, so
`localhost` reaches the test DB while the app uses the container's. Against the
app's own database the catalogue was already exactly in line, which is the best
evidence the extraction was faithful.

**The second login implementation is gone (2026-08-09).** Debt 37.
`modules/auth/services.py` defined `login_user()` — authenticate, stamp
`last_login_at`, mint a token, open a session — while `modules/auth/routes.py`
does all of that inline against `authenticate_user` and
`authenticate_platform_admin`. Two authentication paths, one unused and free to
drift, in the module where drift matters most.

Confirmed dead by searching the raw string across all four repos plus infra:
three occurrences, being the definition and two mentions in these docs. No
`__all__`, no wildcard re-export, no dynamic lookup. Deleting it orphaned
nothing — `authenticate_user` and `create_session` keep the callers the routes
import directly.

**Method note, because the obvious check was wrong.** Counting call sites for
`logout_user` returned zero, and it is very much alive: `routes.py` imports it as
`logout_user as logout_user_service`, so every call reads under a different name.
Searching for the raw identifier finds aliased imports; counting `name(` does
not. The same wrong method would have deleted a live function.

Verified against the running API afterwards: login returns tokens, logout
answers 200, and the refresh token is refused once revoked.

Pre-existing and deliberately left: `from datetime import datetime, timedelta`
in the same file imports `datetime` unused. It was unused before this change,
and sweeping unrelated imports inside a deletion commit hides what the commit
did.

**Debt 36 was not a defect — withdrawn (2026-08-09).** It claimed two live
finance screen trees reached by different paths, with Invoices unreachable from
the menu. Neither half was true, and both came from reading a directory listing
instead of the files.

`src/app/(dashboard)/finance/*` is seven files of five to seven lines each: pure
`redirect()` stubs kept so links and bookmarks from before the routes moved still
land somewhere sensible. There is one implementation, under `dashboard/finance`.
And `/finance/invoices` is not a hidden invoices screen — it carries a comment
saying invoices were unified into Student Fees (`StudentFee` *is* the invoice)
and redirects there. Nothing in the app calls itself Invoices, and no invoices
service survives. Verified live: `/finance/student-fees` lands on
`/dashboard/finance/student-fees`.

What was real, and is fixed: the student detail page cross-linked to
`/finance/student-fees`, so "Open fees" bounced through the compatibility layer
instead of going where the page lives. `internalLinks.test.ts` now recognises a
redirect stub and fails any internal link pointing at one — those routes exist
for the outside world, not for this app to link to.

**Section merge is reachable, and merged sections have left the pickers
(2026-08-09).** Debt 18. `merge_sections` was complete, tested and unrouted;
nothing filtered `merged_into_class_id`, so a retired section stayed on every
list offering a choice the placement primitive refuses.

Now `mergeSections` on GraphQL, guarded by `class.manage` **and**
`student.update` — two keys, because a merge retires a section *and* moves every
child in it, and someone who may reorganise rooms should not move a section of
children by naming the operation after the room. The service's refusals map to
`NOT_FOUND` / `CONFLICT` / `VALIDATION_ERROR` on a stable fragment of the
message, so rewording it for a human cannot silently reclassify it.

`_class_list_query` drops merged sections unless `includeMerged` asks for them,
which covers both transports and every picker built on them; the attendance
class picker got the same filter directly. Migration 104 adds
`merged_by_user_id` and `merge_reason`, so the section records who decided and
why rather than only when — `person_merges` has done both since it was built.
The class detail page carries the action, a confirmation naming the number of
children and both sections, and a banner on a retired section explaining where
its future went.

Verified against the running stack: 14 sections became 13 after a merge, the
retired one reporting its survivor, date, reason and actor (read from the
Person, not the login copy); `includeMerged` brought it back to 14; a second
merge was refused as `CONFLICT`; and the merge picker listed all 12 live
sections while excluding both the merged one and itself.

**A teacher stops holding the school's onboarding permission (2026-08-09).**
Debt 33, resolved the other way round from how it was written. The School Admin
lacking `school_setup.*` is *correct*: standing a school up is operator work done
in the panel, and admin-web's `isPlatformAdmin` gate is the control-plane split
rather than a workaround. Nothing an administrator does was ever refused —
mediums and subject contexts also accept `class_subject.manage`, which Admin
holds.

The real defect was the Teacher grant. Reading the mediums and subject contexts
required `school_setup.read`, `school_setup.manage` or `class_subject.manage`;
a teacher holds `class_subject.read` and no manage key, so the only way to let
them see those lists was to hand them the school's onboarding readiness. Those
reads now accept `class_subject.read` (REST and GraphQL), the grant is gone from
both role definitions, and migration 103 revokes it from existing tenants —
`seed_roles_for_tenant` only ever adds, so removing it from the seed alone would
have changed nothing. `tests/test_role_grants_are_honest.py` pins both halves and
asserts the two seeders agree.

**Classes and the subject catalogue read on GraphQL (2026-08-08).** admin-web
reads `classes` / `classStats` / `class` and `subjectCatalogue`, each guarded
on the key its route decorator carried rather than an inferred one. Deleted
because nothing else called them: `GET /api/classes/stats`, and the paginated
branch of `GET /api/subjects/`. Every reader goes through one builder —
`_class_list_query`, `_subject_catalogue_query` — and a test compares the
screen against the export.

⚠️ **Corrected within the day: `GET /api/classes/`, `GET /api/classes/<id>`
and the flat `GET /api/subjects/` were deleted and had to be restored.** The
Expo client calls all three (`client/modules/{classes,finance,subjects}/
services/`). The check that cleared the deletion grepped `client/src` — a
directory this repo does not have, since the Expo app keeps its code in
`client/modules/` — and an empty result was read as "no consumer" instead of
"wrong path". **A grep that finds nothing is a result to verify, not a
result.** The routes are back, each carrying a comment saying whose they are,
and tests now fail if they go again. See open item 31.

**An audit of all 205 Expo and panel API calls against the route table then
found a fifth break, older than mine: `GET /api/students/`,** deleted in
92ed1cf under the same false claim ("nothing calls it any more") and asserted
by a test that pinned the resulting 405. The mobile student list had been
broken since. Restored on `list_students`, which the export already reads, and
the filter parsing plus the read.all/read.class ceiling are now extracted so
the list and the export share one of each.

**A payload-shape audit followed, and found a sixth break, also older than
mine: the Expo Classes screen crashed on load.** `GET /api/classes/` has
answered with `{items, total, page, ...}` since the paginated list landed, but
`classService.getClasses` typed it `ClassItem[]` and handed the object
straight to `groupByGrade`, which iterates it — an object is not iterable, so
the screen threw the moment the fetch resolved. The finance class picker made
the same assumption more quietly, falling back to `[]`, so it was merely
always empty. Both now unwrap the envelope, the way `studentService` already
did. `scripts/audit_client_shapes.py` keeps the check; it reports only the
case that breaks a screen — a bare `X[]` meeting an object — because an
earlier version flagged all seven collection reads and the five harmless ones
buried the two real ones.

**Writes were the last gap, and are only partly closed.**
`scripts/audit_client_write_payloads.py` runs real create/update/delete cycles
against demo data and checks each response against the type the client
declared — six responses across subjects, classes and holidays, all matching,
each probe verifying its own cleanup and the script refusing to run against a
non-local host. That is 6 of 104 non-GET calls. Another 60 declare a type some
GET already verified, which is an inference about the write rather than a
check of it, and ~20 return `void` or a bare message. The two that matter most
here — `POST /api/students` and `POST /api/teachers`, whose serializers this
migration changed — were read by hand: both answer with the same entity dict
their detail GET returns, wrapped as the clients declare. Widening the audit
means adding a probe with its own payloads; it must not be widened by skipping
the delete.

**A type assertion is a claim about the server that nothing verifies.** `tsc`
was perfectly happy with all of this.

The audit script itself needed two rounds before it could be trusted: its
first version missed two of three *known* breaks, because a URL assigned to a
variable never appears inside `apiGet(...)`, and because truncating a path at
an interpolation invented a shorter path that matched a real route. **Run a
coverage check against known-broken input before believing a clean audit.**

Three things the migration turned up, none of them the migration's own:

- **Branch scope lived in the route.** `assert_class_allowed` on the detail
  route was the *only* check on it — the service never filtered — so deleting
  the route without moving the assert would have opened every class to every
  branch-restricted sub-admin. Both asserts now sit in the service, where they
  hold however the workflow is reached.
- **Two sweeps had stopped sweeping.** `test_disabled_module_does_not_break_others`
  swept class URLs and only failed on ≥500, so a route that moved to GraphQL
  went on "passing" as a 404; `_stamp_of` read a header off one. A page that
  leaves REST leaves the URL sweep silently — GraphQL reads are now swept by
  asking, and the stamp test asserts the status it reads from.
- **`classes.name` is empty for every class the structured form creates**, and
  five screens composed their own label from it: the detail page titled itself
  "— A", the fee filter offered twelve options all reading "-A", the audience
  picker's checkboxes were blank. The rule now lives on the server as
  `Class.displayName`, the same way `StudentClass.displayName` already did.

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
