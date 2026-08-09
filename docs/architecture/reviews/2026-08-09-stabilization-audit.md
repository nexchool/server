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

### [BLOCKER] A School Admin cannot read their own school's setup

`scripts/seed_rbac.py` defines 166 permissions across 4 roles. Resolving `.manage`
implication, an Admin can satisfy every enforced key **except two**:

```
school_setup.read
school_setup.manage
```

`school_setup.read` is held by exactly one seeded role — **Teacher**. Admin holds
neither key, so `setupStatus` and every `school_setup`-guarded surface returns 403
to the person the module exists for. admin-web hides this behind an `isPlatformAdmin`
gate, which the roadmap explicitly rules out as a fix.

This is not a drifted local tenant: it is what `seed_rbac.py` gives every new tenant.
Confirms and sharpens debt 33. → **Phase E1.**

### [BLOCKER] A navigation link 404s

`admin-web/src/components/academics/year-transition/TransitionComplete.tsx:212` links
to `/dashboard/transport/enrollments`. No such page exists. A user completing year
transition — the moment transport enrolment matters most — clicks through to a 404.

### [PRODUCT GAP] Section merge is implemented and unreachable

`modules/classes/section_merge.py:34` implements `merge_sections`, with model support
already in place (`Class.merged_into_class_id`, `Class.merged_on`,
`Class.is_merged_away`). It has **zero callers**: no route, no resolver, no script,
no task. The capability exists in full and no user can invoke it. → **Phase B1.**

### [PRODUCT GAP] Merged sections are not excluded from active class queries

`modules/classes/services.py` never references `merged_into_class_id` or
`is_merged_away`. Once merge becomes reachable, merged-away sections will keep
appearing in every class picker and list. Latent today only because no row can
have the column set. Fix belongs in the same change as B1.

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

## 5. Proposed ordering change

Phase A's evidence suggests one adjustment. The roadmap runs B → C → D → E, putting
authorization at E. But the `school_setup` blocker makes an entire module inaccessible
to its intended user *today*, and the eight-script seeding problem is what will
generate the next such blocker. **E1 should move ahead of B.** It is small, it is
contained, and every later phase inherits a trustworthy authorization baseline
instead of building on top of one known-false grant.

Phase E2 shrinks to a spot-check, since the isolation suspects came back clean.
