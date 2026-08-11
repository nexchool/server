# Stabilization audit — Phase A

**Date:** 2026-08-09 · **Scope:** whole repository (server, admin-web, panel, client)
**Purpose:** establish the real backlog before Phase B. Nothing here is fixed yet.

Every claim below was derived by inspecting the repository in this session. Prior
audit claims and session memory were not used as evidence. Where a suspicion from
the roadmap turned out to be wrong, it is recorded as **not confirmed** rather than
quietly dropped — three of them were.

Two of my own measurements were wrong on the first pass and are noted inline, because
the corrected number is the finding.

---

## 1. Transport inventory — where the product actually is

| Surface | Count |
|---|---|
| GraphQL queries | **40** |
| GraphQL mutations | **9** |
| REST business operations | **413** (160 read / 253 write) |
| REST infrastructure operations (auth, health, uploads, exports, platform) | 85 |
| Backend modules | 38 |
| admin-web screens | ~70 |

**The headline: reads have migrated, writes have not.** Nine mutations against 253
REST business writes. Every migration slice so far moved a read surface; the write
path for those same modules is still REST. That is the single largest input to
Phase G, and it means "module X is on GraphQL" is currently only ever half true.

REST business operations by module (top 10):

| module | GET | WRITE | | module | GET | WRITE |
|---|---|---|---|---|---|---|
| transport | 21 | 30 | | students | 10 | 16 |
| academics | 13 | 33 | | rbac | 7 | 14 |
| classes | 12 | 33 | | finance | 10 | 8 |
| teachers | 13 | 24 | | attendance | 11 | 4 |
| hostel | 14 | 18 | | announcements | 5 | 6 |

---

## 2. Findings

### ~~[BLOCKER] A School Admin cannot read their own school's setup~~ — WRONG, see below

**Retracted 2026-08-09, same day.** The measurement was right and the conclusion
was backwards.

It is true that, resolving `.manage` implication, an Admin satisfies every enforced
key except `school_setup.read` and `school_setup.manage`, and that `school_setup.read`
is held only by the Teacher role. What I did not check was whether anything an
administrator actually does needs those keys. Nothing does:

- The `school_setup` module's own routes are onboarding — operator work done from
  the panel, not the tenant app. admin-web only asks for `setupStatus` when
  `isPlatformAdmin`, which is the control-plane split working as designed, not a
  workaround.
- Mediums and subject contexts are guarded with `require_any_permission(...)` that
  **also accepts `class_subject.manage`**, which Admin holds. No refusal.

So the Admin role lacking the setup keys is correct, and the `isPlatformAdmin` gate
should stay.

### [ARCHITECTURE DEBT] A teacher holds the school's onboarding permission — fixed

What the same evidence actually showed, once read the right way round. A teacher
holds `class_subject.read` and no manage key, while the mediums and subject-context
*reads* accepted only `school_setup.read`, `school_setup.manage` or
`class_subject.manage`. So the only way to let a teacher see those lists was to grant
them `school_setup.read` — the school's onboarding readiness — as a side door.

Fixed in this pass: those reads now accept `class_subject.read` (REST and GraphQL),
the grant is removed from both role definitions, and migration 103 revokes it from
existing tenants. `seed_roles_for_tenant` only ever adds, so removing it from the
seed alone would have changed nothing anywhere. Debt 33 closed.

### [BLOCKER] Navigation links that 404 — fixed

`TransitionComplete.tsx:212` linked to `/dashboard/transport/enrollments`, which does
not exist; the screen is `/dashboard/transport/students`. Checking the rest of the app
found four more, all pointing at `/academics` — the standalone hub that was replaced by
a collapsible sidebar group, still the target of every "Back to academics" breadcrumb
in bell-schedules and year-transition.

A third, `/school-setup`, was reached from five places but sat behind a hard-coded
`false` shim, so it never rendered. That shim and its dead CTAs are now deleted; one of
them turned out to be hiding a real gap (debt 40).

All fixed, and `admin-web/src/lib/internalLinks.test.ts` now resolves every literal
internal `href` against the filesystem route tree. Next.js reports none of this — a
link to a deleted page is not a build error, not a type error and not a lint error.

### [PRODUCT GAP] Section merge is implemented and unreachable — already debt 18

`modules/classes/section_merge.py:34` implements `merge_sections`, with model support
already in place (`Class.merged_into_class_id`, `Class.merged_on`,
`Class.is_merged_away`). It has **zero callers**: no route, no resolver, no script,
no task. `modules/classes/services.py` never filters on those columns either, so a
merged-away section would keep appearing in every picker.

Both halves were already registered as **debt 18**, which this audit re-derived
independently without noticing. Recording that rather than opening a second item —
the register is the authority, and a duplicate entry is how one item becomes two
half-done ones. → **Phase B1.**

### [UI GAP] admin-web cannot create a class

Found while sweeping the dead `/school-setup` links. The classes page's only create
affordance was `canCreate && isSchoolSetupEnabled()`, linking to the removed setup
wizard, behind a flag hard-coded to `false` — so `class.create` was read and never
used, and the zero-class empty state pointed at the same dead route.

A school opening a new section mid-year has no way to add it from the tenant app.
Dead markup removed; the gap is registered as **debt 40** rather than fixed here,
because whether creating a section is operator work or school work is a product
decision.

### ~~[UI GAP] The Invoices screen is unreachable from navigation~~ — WRONG, withdrawn

I claimed two live finance screen trees reached by different paths, with Invoices
unreachable from the menu. Neither half was true. Both came from reading a
directory listing instead of the files — the same mistake as the retracted
blocker above, and the third time in this audit.

`src/app/(dashboard)/finance/*` is seven files of five to seven lines: pure
`redirect()` stubs, kept so links and bookmarks from before the routes moved
still land somewhere sensible. There is one implementation, under
`dashboard/finance`. And `/finance/invoices` is not a hidden invoices screen —
it carries a comment saying invoices were unified into Student Fees (`StudentFee`
*is* the invoice) and redirects there. Nothing in the app calls itself Invoices
and no invoices service survives. Verified live: `/finance/student-fees` lands on
`/dashboard/finance/student-fees`.

What was real: the student detail page cross-linked to `/finance/student-fees`,
so "Open fees" bounced through the compatibility layer instead of going where the
page lives. Fixed, and `internalLinks.test.ts` now recognises a redirect stub and
fails any internal link pointing at one.

**A directory listing is not evidence about what a file does.** Every wrong
finding in this audit came from inferring behaviour from a name or a path. The
cost of opening the file is seconds; the cost of not opening it, three times
here, was a finding that sent work in the wrong direction.

### [ARCHITECTURE DEBT] Six confirmed dual transports

Both a REST GET and a GraphQL field currently serve the same operation:

```
/api/classes/        /api/classes/<id>    /api/subjects/
/api/students/       /api/teachers/       /api/holidays/
```

Some of these are deliberate — restored because the shipped Expo build calls them —
but "deliberate" was never written down as a contract, and the roadmap forbids
permanent accidental dual transports. Each needs an explicit verdict: REST retained
for the mobile client until it migrates, or deleted. The four calendar/setup
deletions (`/api/academics/calendar`, `/calendar/*`, `/api/academics/terms`,
`/api/school-setup/status`) held — those are GraphQL-only.

> Correction: my first pass reported all twelve of these as "REST deleted". The
> checker built a dict keyed by rule and a later same-path rule overwrote the GET
> entry with an empty method list. The routes were always there.

### [ARCHITECTURE DEBT] A second, dead login implementation — deleted

`modules/auth/services.py` defined `login_user()` with no callers, while
`modules/auth/routes.py:196` implements login inline against `authenticate_user`
and `authenticate_platform_admin`. Two authentication code paths, one unused and
free to drift, in the module where drift matters most. Deleted; login and logout
verified against the running API afterwards.

**This is the one finding here whose method held up, and it is worth knowing
why.** It was found by searching the raw identifier across all four repos, not by
counting call sites. Counting call sites reports `logout_user` — sitting directly
below it, and very much alive — as having zero callers, because `routes.py`
imports it as `logout_user as logout_user_service` and every call reads under a
different name. Searching the string finds aliased imports; counting `name(` does
not, and here it would have deleted a live function in the auth module.

The same caveat applies to the 80 uncalled service functions below: **that list
was built by counting call sites, so some entries will be aliased imports rather
than dead code.** Triage each by searching the identifier, never by the count.

### [ARCHITECTURE DEBT] Permission seeding is spread across eight scripts — fixed

Besides `seed_rbac.py`: seven backfill / grant / fix scripts, so a tenant's
authorization state depended on which of them had been run against it.

**The cause was not sprawl; it was that the canonical seeder silently did not
work.** `seed_rbac`'s role phase called `create_role` and
`assign_permission_to_role_by_name`, both of which resolve the tenant off the
request. Run as a CLI there is none, so all four roles failed with "Tenant context
is required", the script printed four crosses and exited 0, and `startup.sh` logged
a warning and carried on. It has only ever created permission *rows*; every grant
came from `seed_roles_for_tenant` at login. Each module then wrote its own script
to do the per-tenant work the canonical seeder was named for.

Fixed: one catalogue in `modules/rbac/catalog.py` that both seeders import (this
also closes debt 6d), `seed_rbac` seeding every active tenant from it, six of the
seven scripts deleted, and `scripts/reseed_rbac.py` adding the `--dry-run` and
`--reconcile` that seeding never had. `fix_teacher_permissions` is kept — it
repairs a `StaffAuthority` link, a user→role problem, not a permission backfill.

### ~~[ARCHITECTURE DEBT] 80 public service functions with no caller~~ — it was 10

The number was wrong, and so was the method that produced it. It counted call
sites (`name(` outside the defining file), which reports a function imported
under an alias as dead — `logout_user` scores zero that way and is very much
alive. Re-derived by searching the raw identifier across 1,596 files in all four
repos plus infra, of 541 public functions in module service files:

| | |
|---|---|
| referenced outside their own file — alive | **529** |
| referenced only by tests — built, never routed | **12** |
| used only inside their own file — private, just not underscored | **47** |
| referenced nowhere at all — deleted | **10** |

The 47 were the bulk of the original 80 and were never rot: module-private
helpers that happen to lack a leading underscore. Renaming them across nine
modules is churn with no behaviour change, so they stay — recorded so the next
audit does not count them again.

The 12 test-only ones are the honest form of debt 18's shape: a capability with
no door. Left alone deliberately, not deleted — `delegate_authority`,
`duplicate_unit_to_unit`, `can_user_mark_session` and nine others are features
awaiting a transport, not mistakes.

**The eleventh deletion turned into the real finding.**
`cleanup_expired_sessions` was dead, with a docstring saying it "should be run
periodically (e.g., via cron job)". Nothing ever ran it — and nothing else
pruned the table. Notification logs and audit logs each have a retention job;
`sessions`, a row per sign-in per device and the table guaranteed to grow
fastest, had none. Its body is now `retention.purge_expired_sessions` on the
nightly schedule, as a bulk delete rather than loading every expired row into
memory to delete one at a time.

---

## 3. Suspicions from the roadmap that did NOT hold

### Tenant isolation — no leak found

93 models are auto-scoped via `TenantBaseModel` + `with_loader_criteria`. The
exceptions were checked individually:

- **`notification_recipients`** (no `tenant_id`) — every query filters on
  `user_id == <authenticated user>`, or joins `Notification` with an explicit
  `tenant_id` filter. A user belongs to one tenant, so these are tenant-safe by
  construction. **Not a leak.**
- **`hostel_gatepass_audit`** (no `tenant_id`) — its one query
  (`modules/hostel/routes.py:765`) filters by a gatepass already loaded under tenant
  scope. **Not a leak.**
- **`audit_logs`, `notification_templates`, `tenant_usage`, `tenant_onboarding_drafts`**
  carry `tenant_id` but bypass auto-scope; their queries filter manually. The
  unfiltered `NotificationTemplate.query.get()` calls are all in `modules/platform/`,
  where operating across tenants is the job. Worth confirming the platform route
  guard, not a tenant defect.
- `permissions`, `plans`, `platform_settings`, `tenants`, `subject_template_*` are
  platform-global by design.

**Phase E2 should be scoped down accordingly** — the named suspects are clean.

### Identity/account coupling — the structural part is already done

`students.user_id` and `teachers.user_id` are both **nullable**. Phase F's central
ask (Person → optional Account) is satisfied at the schema level. What remains is
the narrower question of `users.id` used where a Person/Staff/Teaching Assignment
reference belongs, which this pass did not enumerate.

### Permission keys — no orphan enforcement

Every one of the 91 enforced keys exists in `seed_rbac.py`. There are no keys that
can only ever refuse.

> Correction: an earlier pass reported 9 enforced-but-unseeded and 59
> seeded-but-unenforced keys. Both lists were artifacts of a matcher that read only
> string literals inside the guard call and missed the `PERM_*` constants every
> resolver actually uses. With constants resolved, both lists are empty except the
> `school_setup` blocker above.

---

## 4. Not yet inventoried

Stated plainly so the backlog is not mistaken for complete:

- Per-item triage of the 80 uncalled service functions
- The full REST-route table classified business vs infrastructure line by line
  (counted, not enumerated)
- UI screens whose backing endpoints are missing, beyond the two found
- Backend functionality with no UI, beyond `merge_sections`
- Remaining `users.id` references that should be Person/Staff
- Performance claims from the roadmap are now all measured: `suggest_duplicates`
  and `_bus_operational_warning` were real and are fixed; the duplicate
  REST+GraphQL call claim **did not hold** (below)
- panel and Expo client screen inventories

---

### [PERFORMANCE DEBT] `suggest_duplicates` — measured, and it was real

The roadmap carried "~65s" for this. That figure was stale — a `perf(people)`
commit had already rewritten the scan to read columns rather than ORM instances.
On the demo school's 866 people it answers in **4.5ms**, and on 15,000 people
with ordinary name spread, **55ms**.

But measuring the shape rather than the average found a genuine cliff. Buckets
were keyed on name alone, then each pair tested for a matching date of birth —
so a common name cost the square of how common it is. Worse, the `limit` could
only be reached through a match, so a large name bucket with distinct birthdays
ran the whole quadratic and returned *nothing*. Measured on the real database:

| people sharing one name | before | after |
|---|---|---|
| 500 | 111 ms | 6 ms |
| 1,000 | 492 ms | 6 ms |
| 2,000 | 1.74 s | 9 ms |
| 4,000 | 6.86 s | 19 ms |

Each doubling cost about four times as much — extrapolating, 15,000 people
sharing a name is over a minute, which is plausibly where the original figure
came from.

Fixed by keying the bucket on name **and** date of birth together, so every pair
in a bucket is a match by construction and the limit ends the work. Behaviour is
unchanged, checked case by case: the real duplicate is still found (including
through whitespace and case normalisation), same-name-different-birthday is
still not offered, the household phone is still raised, and a missing birthday
still cannot confirm a match.

The regression guard counts comparisons rather than watching a clock — 600
people who share only a name went from **179,700** pair comparisons to **0**,
and a timing threshold loose enough to be stable was too loose to catch it.

### [PERFORMANCE DEBT] `_bus_operational_warning` — measured, and it was an N+1

Called once per bus inside two loops: the fleet list and the transport
dashboard. Each call asked for that bus's assignments and then counted its
schedules — two queries a bus, on top of the row itself. Counted on the real
database:

| fleet | `list_buses(page 1, 20)` | `dashboard_stats()` |
|---|---|---|
| 29 buses | 62 queries, 36 ms | 64 queries, 34 ms |
| 104 buses | 212 queries, 114 ms | 214 queries, 123 ms |
| 254 buses | 512 queries, 349 ms | 514 queries, 270 ms |

Exactly 2N + constant, and **asking for a page of twenty still paid for the
whole fleet** — the rows are built before the page is cut. 349ms on a local
database with no network between the app and Postgres; against RDS at ~1ms a
round trip, 512 queries is half a second of latency alone, growing linearly and
without bound.

The surrounding code had already learned this lesson — `list_buses` batches
enrollments and crew assignments into dicts, with a comment explaining why. The
warning was the one thing still asked per bus, and it re-queried assignments the
loop already held. Split into `scheduled_bus_routes` (one query for the fleet)
and `operational_warning_for` (no queries, decides from what the caller has);
`_bus_operational_warning` stays as the single-bus wrapper for the detail view.

| fleet | after |
|---|---|
| 29 buses | 5 queries, 3.8 ms |
| 104 buses | 5 queries, 6.1 ms |
| 254 buses | 5 queries, 9.7 ms |

Constant, not linear. Verified equivalent bus by bus against the single-bus path
across a fleet with a spread of states — no assignment, inactive route, active
schedules — with zero disagreements.

### ~~[PERFORMANCE DEBT] Duplicate REST + GraphQL calls~~ — not confirmed

Measured from the browser's network log on cold loads of `/classes`,
`/students` and `/teachers`. Every one makes the same shape: **2 GraphQL POSTs
plus 5 ambient REST calls** — `auth/profile`, the notification list, the unread
count, `subscription/state` and the SSE stream. None of them fetches the same
data twice, and no screen reads over both transports.

Checked statically as well: seven services import both `gql` and `apiGet`, but
the REST reads that survive beside a GraphQL query are sub-resources
(`/classes/<id>/subjects`, `unassigned-students`), exports, or records with no
GraphQL equivalent. The one genuine overlap is student detail — `student(id)`
exists on GraphQL and admin-web's detail page still reads
`GET /api/students/<id>` — but only one of them is ever called, so it is a dual
*transport* (debt 31) rather than a duplicate *call*.

Worth recording for the next person: a soft navigation to `/classes` made
**zero** network calls, served entirely from the TanStack cache. Any measurement
of this kind has to force a cold load or it measures the cache.

### [BLOCKER] Rate limits were counted per worker, and intermittently 500'd

Found while measuring the above: `GET /api/subscription/state` returned 500 on
one screen load and 200 on the next. The traceback is inside Flask-Limiter —
`RuntimeError: threads can only be started once`, from the in-memory storage's
expiry thread.

`Limiter(key_func=get_remote_address)` was constructed with no storage URI, so
every environment kept its counters in process memory while `REDIS_URL` sat
unused. Two consequences, both measured:

- **Intermittent 500s on any rate-limited route**, including login.
- **The login limit was not the limit.** `@limiter.limit("5 per minute")` is
  per process, and the API runs four gunicorn workers by default. Measured
  against the running stack: **9 failed login attempts got through before the
  first 429**, where `security-guardrails.md` requires five. Counters also reset
  on every deploy.

Fixed by pointing the limiter at `REDIS_URL` with in-memory fallback enabled, so
a Redis outage degrades the limiter rather than taking the API down. Storage is
now `RedisStorage`, and the same measurement gives **5 attempts before the first
429**.

## 5. What this pass changed, and what it means for the ordering

Implemented here (bucket 1, authorization + dead links): the teacher over-grant with
migration 103 and `test_role_grants_are_honest.py`; five broken internal links with
`internalLinks.test.ts` guarding the class; the `/school-setup` dead-code sweep.

**Phase E1 shrinks to almost nothing.** The one authorization defect is closed and no
other role can fail to satisfy a key it needs. What remains under E1 is debt 38 — the
eight seeding scripts, and the fact that `seed_roles_for_tenant` can only ever add, so
every over-grant is permanent until someone writes a migration. That is a real risk but
not a blocker, and it belongs with the next authorization change rather than ahead of B.

**Phase E2 shrinks to a spot-check**, since the isolation suspects came back clean.

So the roadmap's B → C → D order stands. The correction worth carrying forward is
methodological: this pass produced two findings that were confidently wrong in
opposite directions (a "blocker" that refuses nobody, and a duplicate of debt 18).
Both came from measuring a mechanism without checking whether any real user path runs
through it. The audit half of each loop should end by naming the user and the screen,
not just the guard and the grant.

---

## 6. Grade — how it is modelled, and the entry point moved (2026-08-10)

*Audited on request before changing anything, then a business decision taken.*

### What a Grade is, as built

`grades` is a **flat, tenant-wide catalogue**: `name` unique per tenant among
active rows, `sequence` for order, and nothing else. No programme, no campus,
no academic year, no division. Two tables reference it — `classes.grade_id` and
`subject_contexts.grade_id`. In the demo tenant, grade "1" is one row shared by
two programmes across five sections.

So a grade is created **once for the whole organisation**, and a Class/Section
is the per-(campus × programme × grade × section × year × medium) thing.

### Where that sits against the canon

`modules/academic-management.md` and the v2 memory both describe
**Programme → Academic Year → Academic Division → Grade → Section**, with a
programme owning its academic structure. The table implements none of that
nesting. Four consequences, all real:

1. **A programme's grade span cannot be expressed.** Every programme is offered
   every grade, so a section can be opened on a year that programme does not run.
2. **Graduation cannot be derived.** The canon defines it as "the highest grade
   of a Programme"; with a shared catalogue there is no such value.
3. **One spelling wins per tenant.** `name` is unique tenant-wide, so "Std 1"
   under one board and "Grade 1" under another are either one row (one board's
   house style imposed on the other) or two rows at the same level.
4. **Division hangs off the Class, not the Grade.** Grade 1 is always Primary,
   but that is recorded per section. Live data is consistent — every grade maps
   to exactly one division — by the seeder's discipline, not by any constraint.

The flat model earns its keep in one way worth protecting: a single `sequence`
makes promotion order, grade-wise reporting and the class-list sort work across
the whole organisation.

### Decision (user, 2026-08-10)

**Grades are no longer created as their own step.** Creating a grade first and
a class second is backwards — the school is opening a section, and the grade is
a detail of it. So:

- The Grades screen **loses its create surface** (quick-add presets and the add
  form are gone). It remains for reading, renaming and removing.
- **Add a section** takes a grade by name — pick an existing one or type a new
  one, created on submit before the section.
- Deliberately **not** done: splitting grades per programme. That was offered
  and not chosen; the shared level and its single sequence stay.

### What this forced

`create_grade` defaulted an absent `sequence` to **0**, which put a
newly-created grade at the *front* of the ladder — harmless while the only
caller was a form that always sent one, wrong the moment a grade can be typed
while opening a section. It now infers: the number in the name is the level
("Std 6" → 6), and a name with no number goes to the end where it is visible
and correctable rather than silently mid-ladder.

The same rule lives on the client as `lib/gradeLevel.ts`, which is what lets the
form warn that "Std 6" would sit at the same level as an existing "6" — two
names for one year, both valid to the unique index, and a split in promotion
and every grade-wise report if it goes through.

### Still open

Consequences 1, 2 and 4 above are untouched by this change and remain
unregistered pending a decision on programme-scoped grades.

---

## 7. Grade and Class — where they are used, and how the relationships are held (2026-08-10)

*Full dependency audit, requested before planning any change.*

### Size of each

|  | Grade | Class |
|---|---|---|
| tables with an FK into it | **2** (`classes`, `subject_contexts`) | **12** |
| server modules touching its id | 7 | 17 |
| REST routes | 0 (GraphQL-only since 2026-08-10) | **46** across 4 files |
| admin-web files | 16 | 57 |
| **Expo files** | **0** | **44** |

The last row is the one that decides sequencing. **The mobile app never sees a
grade** — it reads classes and their composed labels. So grade work carries no
mobile-release gate, and class work carries a heavy one.

A class's identity is populated in practice, not just in theory: of 14 classes,
0 lack a grade, programme, campus or division; 2 lack a medium; 2 still carry
the legacy free-text `name`.

### How each relationship is actually held

Three of them are held **twice**, and the three are not in the same condition.

**1. Student → Class — a maintained mirror.**
`students.class_id` alongside `student_class_enrollments` (which carries the
year, status, and the `promoted_from_enrollment_id` chain).
*State: in agreement.* Of 278 students with a class, 0 have no current
enrollment and 0 point somewhere else. One owner writes both —
`students/class_enrollment_service.py`.
*Cost: the mirror is the dominant read path* — ~41 read sites against 10 files
that use the enrollment table.

**2. Teacher → Class — a maintained mirror.**
`classes.teacher_id` alongside `class_teacher_assignments` (role, effective
dating, `allow_attendance_marking`).
*State: in agreement.* 12 legacy values, 12 active primary assignments, 0
disagreements. Two writers — `classes/services.py` and
`academics/services/class_teacher_assignments.py` — and **both** maintain the
pair, which is why it holds.
*Cost: ~10 files read the column.*

**3. Subject → Class — a stale, unreachable duplicate.**
`class_subjects` (the real one: periods, mandatory/elective, term, context)
alongside `subject_load` (`class_id`, `subject_id`, `weekly_periods` — a strict
subset).
*State: already drifted.* Every `subject_load` row exists in `class_subjects`,
but **6 class-subject pairs have no load row**, and nothing keeps them in step.
*Cost: none — it is dead.* The 4 routes are called by a service in each client;
neither reaches a screen. `ClassSubjectLoadSection.tsx` is rendered by no page
(the class detail uses `ClassSubjectsSection`), and Expo's `useSubjectLoad` has
no consumer.

### A fourth duplication: the class label

Three places compose one independently, in two spellings:
`Class.display_name` (space — canonical), `classes/bulk_services.py:155`
(its own `f"{grade.name} {section}"`), and the student payloads
(`students/models.py` + `students/graphql/types.py`, hyphen — debt 41).

### Proposed order

Cheapest and safest first; each step stands alone.

1. **Delete `subject_load` and its whole vertical** — table, 4 routes, both
   clients' service/hook/types, and the orphan admin-web component. Nothing
   reads it, it is already stale, and it removes one of the three duplicate
   pairs outright. No Expo gate, because no Expo screen uses it.
2. **One label composer.** Point `bulk_services` at `Class.display_name`. The
   hyphen form stays until Expo stops parsing it (debt 41).
3. **Retire `classes.teacher_id`.** ~10 files read through to
   `class_teacher_assignments` instead, then drop the column. Expo reads the
   teacher out of payloads, not the column, so this is server-side.
4. **Decide `students.class_id` last.** 41 read sites, and unlike the other two
   it earns its keep — every student list joins on it. The honest choice is
   *keep it and make it explicitly a cache*: one writer (already true), plus a
   test asserting it agrees with the current enrollment. Removing it is a large
   change for a denormalisation that is working.

Grade needs no structural work: two FKs, no mobile gate, and its remaining
questions (programme span, graduation, division) are the modelling decision in
§6, not a dependency problem.
