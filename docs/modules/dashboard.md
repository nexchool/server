# Dashboard

One endpoint, and everyone sees a different school on it.

---

# What it is

`GET /api/dashboard/` returns the admin landing aggregate: headcounts, today's
attendance, the alert list, the finance position, transport, and pending
actions. One request, because six requests to paint one screen is six
round-trips on a phone on school wifi.

That shape was written when one person opened it. A principal held
`dashboard.read` and a principal may see everything, so a single permission
over a single aggregate was the honest model.

Sub-admins ended that. A school can now create a fees desk, a hostel warden and
a transport manager, and each of them has business with one slice of the
payload and none of the rest.

---

# Two different absences

A section can be missing for two unrelated reasons, and the payload says which:

| Key | Means | The UI answers with |
|-----|-------|---------------------|
| `{"enabled": false}` | this **school** is not on that plan | an upsell placeholder |
| `{"visible": false}` | this **person** may not see it | nothing at all |

**These must never be merged.** Telling a finance officer that Transport is not
part of their school's plan would be a lie about the school in order to describe
a fact about them — and it invites them to go asking for a module the school
already pays for.

A section fails on either gate. Permission is checked first, so someone without
permission on an unlicensed module reads as `visible: false`, not `enabled:
false` — they learn nothing about the school's commercial arrangements.

---

# Who sees what

`SECTION_PERMISSIONS` and `ALERT_PERMISSIONS` in `modules/dashboard/service.py`
are the whole answer. Both are ANY-of, matching the nav.

| Section | Any one of |
|---------|-----------|
| `overview` | `student.read.all` · `teacher.read` · `class.read` |
| `today` | `attendance.read.all` |
| `finance` | `finance.read` |
| `transport` | `transport.dashboard.read` |
| `actions` | gated per key — see below |

**Alerts are gated per row**, not as a block, because "Attention Required" is a
list of other people's problems. A fees desk sees overdue fees and not a
timetable clash it cannot open. `total_issues` counts only the rows shown: a
badge reading 7 above a list of 2 is worse than no badge.

**`actions` carries two unrelated things and gates them apart** —
`pending_leave_requests` on `teacher.leave.manage`, `upcoming_holidays` on
`holiday.read`. Gating the pair on "either" handed the leave count to anyone
granted the school calendar, which is the same mistake this module exists to
fix, in miniature.

---

# Why the composition is server-side

Because the alternative is not a fix. Hiding a card in React leaves its data in
the response, one devtools tab away, and `.claude/rules/security-guardrails.md`
is explicit: never return more data than the client needs.

So the server composes and the clients render. `admin-web`'s `dashboard/page.tsx`
and the Expo `AdminHome.tsx` both gate their widgets too, but that is defence in
depth and a way to avoid drawing empty cards — it is not the defence.

An absent key renders **nothing**, never `?? 0`. A "Leave requests 0" row is a
claim about a figure the caller was never given, usually linking to a page they
cannot open.

---

# Two traps

**`_can()` mirrors `has_permission` and must mirror both halves of it.** It
exists so the endpoint costs one permission lookup instead of a dozen, and it
reimplements two rules: `<resource>.manage` implies the resource's actions, and
a platform admin passes everything. Copying only the first is not a visible
failure — the route's own `dashboard.read` check still passes on god mode, so a
platform admin gets `200` with every section withheld. `get_user_permissions`
has no god-mode branch; `_granted()` supplies a `GOD_MODE` token instead.

**Alert queries are guarded before they run, not filtered after.** Scoping that
computes everything and discards most of it still makes a fees desk pay for the
timetable-conflict join and both class/subject scans on every dashboard load.

---

# Sub-admins can open it at all

`dashboard.read` was granted to the `Admin` role and to nothing else, and no
module in the sub-admin catalog granted it. Every sub-admin ever created got a
403 on the screen the app opens on, while the sidebar showed them the link —
`/dashboard` is one of the few nav entries with no gate.

`BASELINE_PERMISSIONS` in `modules/sub_admins/catalog.py` now grants it to every
sub-admin regardless of module selection. **Migration 136 backfills**: a
sub-admin's authority is `RolePermission` rows written when the School Admin
last saved them, and nothing recomputes that on login, so a catalog change alone
reaches nobody who already exists.

---

# Code

`modules/dashboard/service.py` (composition) · `modules/dashboard/routes.py`
(`dashboard.read`) · `modules/sub_admins/catalog.py` (baseline grant) ·
`migrations/versions/136_every_sub_admin_may_open_the_dashboard.py` ·
`tests/test_dashboard_scoping.py`
