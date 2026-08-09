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

### [UI GAP] The Invoices screen is unreachable from navigation

Two finance screen trees exist and both are live:

- `src/app/(dashboard)/finance/*` — 7 pages, including the **only** invoices screens
- `src/app/(dashboard)/dashboard/finance/*` — 5 pages, the ones the sidebar links

Navigation links only `/dashboard/finance/*`. `/finance/*` is reached solely by a
cross-link from the student detail page (`students/[id]/page.tsx:687` → "Open fees")
and is protected in `middleware.ts:13`, so it is neither dead nor reachable by
browsing. Net effect: **invoicing has no path from the menu**, and a user who arrives
via a student sees a different implementation of fees than one who uses the sidebar.

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

### [ARCHITECTURE DEBT] A second, dead login implementation

`modules/auth/services.py:366` defines `login_user()`. It has no callers.
`modules/auth/routes.py:196` implements login directly against `authenticate_user`
and `authenticate_platform_admin`. Two authentication code paths, one unused and
free to drift, in the module where drift matters most.

### [ARCHITECTURE DEBT] Permission seeding is spread across eight scripts

Besides `seed_rbac.py`: `backfill_academic_calendar_permissions.py`,
`backfill_admin_finance_permissions.py`, `backfill_teacher_leave_permissions.py`,
`backfill_timetable_subject_permissions.py`, `fix_teacher_permissions.py`,
`grant_hostel_permissions.py`, `seed_holiday_permissions.py`.

A tenant's authorization state therefore depends on which one-off backfills were run
against it. This is the mechanism that produced the `school_setup` blocker above, and
it will produce the next one. → fold into **Phase E1**.

### [ARCHITECTURE DEBT] 80 public service functions with no caller

Public functions in `modules/**/*service*.py` that nothing outside their own file
calls. Seven were spot-checked by hand and all seven were genuinely uncalled, so the
list is not a matcher artifact — but it has not been triaged item by item.

| module | count | module | count |
|---|---|---|---|
| transport | 17 | auth | 7 |
| notifications | 11 | students | 7 |
| rbac | 8 | attendance | 4 |
| school_setup | 7 | mailer | 4 |

Some are genuinely dead; others are unreachable *capabilities* like `merge_sections`
— e.g. `students.analyze_promotion`, `students.import_students_from_rows`,
`rbac.delegate_authority`, `school_setup.duplicate_unit_to_unit`,
`attendance.lock_after_hours`. Distinguishing "delete this" from "this is a feature
with no door" is Phase B/C work and must be done per item, not in bulk.

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
- Performance claims from the roadmap (`suggest_duplicates` ~65s,
  `_bus_operational_warning`, N+1s) — **unverified**, no measurement taken
- panel and Expo client screen inventories

---

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
