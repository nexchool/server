# Leave module redesign — mobile UI consistency + configurable principal approval

**Date:** 2026-09-14
**Status:** Design approved, implementation pending
**Surfaces:** `server/modules/student_leaves`, `server/modules/platform`, `server/modules/academics/backbone`, `panel`, `client/modules/teacher-leaves`, `client/modules/student-leaves`

---

## 1. Why this exists

Two problems, one module.

**The mobile leave screens do not look like the rest of the app.** The teacher
leave tracker is a single 1439-line screen that builds its own cards, its own
tabs-inside-tabs, and puts the Apply form in a `<Modal presentationStyle="formSheet">`
drawer. The product has since settled on a house pattern — list screens composed
from shared components, and every add/edit form as its own nested route. The
teacher module predates that settlement and never caught up.

**A school cannot choose who signs off a student's leave.** Schools differ: in a
small primary the class teacher's word is final; a larger secondary wants the
principal to see every absence. The product has no way to express that difference,
so it imposes one answer on every client.

The second problem turns out to be half-built rather than absent, and the half
that exists does not work. See §3.

---

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Mobile teacher-leaves is **rebuilt**, not patched | The bespoke layout is the inconsistency; converting only the drawers would leave the cards and tabs still wrong |
| D2 | The second approver is **any Admin holding `student.leave.approve.all`, scoped to the student's campus** | No new role, works day one for every tenant. Authority over the child, not merely the permission — same rule as ADR-013 |
| D3 | When the rule is ON and the class teacher is away, **one admin action completes both steps** | The head is senior to the teacher; a second signature from the same person is theatre, and a child's leave must not wait a week |
| D4 | The rule applies to **student leaves only** | Staff leave is a separate module with its own model, balances and routes; no business need was stated for it |
| D5 | The switch is stored in **`AcademicSettings`**, not `tenants.feature_flags` | `feature_flags` is the module on/off register. Its double duty as a settings bag is documented in-code as something to undo, not extend |
| D6 | The switch is configured in the **panel** (super-admin control plane) | Per-client configuration is company control-plane work, consistent with the panel/admin-web split |
| D7 | `requires_admin_approval` stays **snapshotted at submit** | A request is judged by the rule in force when it was filed. Flipping the switch never re-routes work already in flight |

---

## 3. Current state (verified 2026-09-14)

The sequential flow already exists in code and is unreachable in practice.

- `AcademicSettings.student_leave_admin_approval_required` exists
  (`modules/academics/backbone/models.py:57`).
- `services.approve()` already routes
  `pending_class_teacher → pending_admin → approved`
  (`modules/student_leaves/services.py:226`).

It does not work, for three reasons:

1. **`_actor_is_authorized_approver` blocks the principal.** An admin may act only
   when the class teacher is on approved leave *today*. The moment a present
   teacher approves and the request lands in `pending_admin`, nobody is authorised
   to finish it. The request is stuck permanently.
2. **`admin_fallback_queue` never surfaces it.** It filters on the same
   "class teacher away" condition, so a `pending_admin` row appears in no queue.
3. **The one test that covers this passes for the wrong reason.** Its fixture puts
   the class teacher on leave; the docstring says so outright
   (`tests/test_services_state_machine.py:107`).

And there is **no configuration surface anywhere** — not panel, not admin-web.
The column is only ever flipped by a test fixture.

Separately, `_actor_is_authorized_approver` answers one blurred question
("may this person touch this leave?") for two different jobs, which is why a
class teacher can today approve their own escalation to the principal.

---

## 4. Backend design

### 4.1 Authority, split by intent

Replace `_actor_is_authorized_approver` with two predicates:

```
can_act_as_class_teacher(leave, actor)
    actor is leave.class_teacher_id's user                       → True
    OR actor holds student.leave.approve.all
       AND class teacher is on approved leave today
       AND student_is_allowed(leave.student_id)                  → True

can_act_as_head(leave, actor)
    actor holds student.leave.approve.all
    AND student_is_allowed(leave.student_id)                     → True
```

`student_is_allowed` is the existing branch-scope gate; keeping it on both paths
means a campus head cannot decide for a child at a campus they do not run.

### 4.2 State machine

`approve()` and `reject()` dispatch on the leave's current status rather than
asking one question for both stages:

| Status | Flag | Who may act | Outcome |
|---|---|---|---|
| `pending_class_teacher` | OFF | `can_act_as_class_teacher` | `approved` |
| `pending_class_teacher` | ON | class teacher (not the away-fallback) | `pending_admin` |
| `pending_class_teacher` | ON | head, **teacher away** | `approved` — both steps, one action (D3) |
| `pending_admin` | — | `can_act_as_head` only | `approved` |

A class teacher may no longer approve at `pending_admin`. Rejection is available
to whoever may approve at that stage, and remains terminal with a mandatory reason.

### 4.3 Queues

`admin_fallback_queue` becomes the head queue — a union of:

- **(a)** `pending_admin` rows within the head's campuses — the new mandatory stage,
  invisible today;
- **(b)** the existing "class teacher is away" rows — unchanged.

The route `/api/student-leaves/queue/admin` and the response shape are unchanged,
so no client breaks. Rows carry a marker distinguishing (a) from (b) so the screen
can label them.

### 4.4 Notifications

`_admin_user_ids_for_tenant` notifies every Admin in the tenant. For a 20-campus
trust that pings heads of campuses the child does not attend. Scope recipients to
admins with authority over the student's campus.

### 4.5 Schema

Migration `142_student_leave_approval_trail.py`:

- `student_leaves.class_teacher_decided_by_id` — FK `users.id`, `ON DELETE SET NULL`, nullable
- `student_leaves.class_teacher_decided_at` — `TIMESTAMP WITH TIME ZONE`, nullable

`decided_by_id` today is a single column, so step 2 overwrites step 1 and the
school loses the record of who first approved. Two columns rather than a
`student_leave_decisions` child table: the chain is two steps by design, and a
general table would be more machinery than the decision warrants.

Reversible (`down` drops both columns). No backfill — existing rows have one
decision, already correctly recorded in `decided_by_id`.

### 4.6 Applicant context on the payload

An approver today sees leave type, dates and reason — **not even the student's name**.
`StudentLeave.to_dict()` gains an `applicant` block:

| Field | Source |
|---|---|
| `display_name` | `Student.display_name` |
| `admission_number`, `roll_number` | `Student` |
| `class_name` | `Student._class_display_name()` (grade + section) |
| `campus_name` | school unit via `Class` |
| `medium`, `programme` | via `Class` |
| `profile_picture` | presigned S3 URL via `profile_picture_public_url` |
| `guardian_name`, `guardian_phone` | father/mother fields — **approver-gated** |

Guardian phone is returned only to a caller who may approve the request; a list
endpoint never returns more contact data than the screen needs.

All of it is eager-loaded through the existing `eager_leaves` helper. At 15,000
students an approver queue must not issue a query per row.

Payload also gains `class_teacher_decided_by_name` / `class_teacher_decided_at`
for the approval trail.

---

## 5. Configuration surface

### 5.1 API

```
GET   /api/platform/tenants/<tenant_id>/school-policies
PATCH /api/platform/tenants/<tenant_id>/school-policies
      { "student_leave_requires_principal_approval": bool }
```

Reads and writes `AcademicSettings.student_leave_admin_approval_required` via the
existing `get_or_create_academic_settings(tenant_id)`. Audit-logged through
`log_platform_action` with action `tenant.school_policies.updated`, like every
other platform mutation. Platform-admin auth only; not tenant-scoped.

The DB column keeps its name. Renaming it would touch the service, the tests and a
migration for no behavioural gain — the project's rule is to rename only when a
refactor already makes it safe.

The endpoint is named `school-policies` (plural, generic) deliberately: it is the
obvious home for the next per-client school rule, and a single-key endpoint named
after one toggle would not be.

### 5.2 Panel

`panel/app/(dashboard)/dashboard/tenants/[id]/school-policies-section.tsx`,
following the `login-access-section.tsx` pattern — a card whose toggle calls a
TanStack mutation and surfaces failures with `toast.error(getErrorMessage(e))` —
mounted from `tenant-detail-view.tsx`.

Copy:

> **Principal approval for student leave**
> When on, a student's leave request goes to the class teacher first, and to the
> principal after the teacher approves. Both must approve before the leave is
> granted. When the class teacher is on leave, the principal's approval alone
> completes the request.

---

## 6. Mobile design

House pattern is defined by what the app already does elsewhere; both modules are
brought to it rather than given a new one.

### 6.1 `client/modules/teacher-leaves` — rebuilt

| New | Replaces |
|---|---|
| `screens/MyTeacherLeavesScreen.tsx` — `PageHeader` → `SummaryRow` → balance strip → `FilterChips` → `FlatList` of `LeaveRequestCard` → FAB 56pt `radius.full` | the 1439-line screen. **The nested second tab row is removed** — Summary and Balance become sections in one scroll; My Data / Holidays stays as the single `DetailTabs` level |
| `screens/TeacherLeaveFormScreen.tsx` + route `app/(protected)/teacher-leaves/new.tsx` — `react-hook-form` + `zodResolver`, `FormSection`, `FormSelect`, `FormDatePicker`, `FormTextArea`, `PageHeader` with back chevron + Cancel `Link`, pinned full-width primary `Button`, dirty-check "Discard?" + Android `BackHandler` | the inline `ApplyModal` formSheet |
| `screens/TeacherLeaveBalanceScreen.tsx` + route `.../teacher-leaves/balance/[type].tsx` | `LeaveBalanceModal.tsx` and the transparent bottom-sheet `Modal` |
| `screens/TeacherLeavePolicyScreen.tsx` + route `.../teacher-leaves/policy.tsx` | `LeavePolicyModal.tsx` |
| `components/LeaveRequestCard.tsx` — column card, `radius.xl`, `padding lg`, `gap sm`, 4px flat left accent, `elevation.card`, **no hairline border**, `StatusPill` for status | hand-rolled bordered rows in the mega-screen |

Deleted: `LeaveBalanceModal.tsx`, `LeavePolicyModal.tsx`, and every `StyleSheet`
block in the screen that restates a theme token.

`hooks/useTeacherLeaves.ts` is hand-rolled `useState`/`useCallback` while the rest
of the app uses TanStack Query. It is converted, so cache invalidation after apply
and cancel behaves like every other module.

### 6.2 `client/modules/student-leaves` — finished

Already close to the house pattern. Remaining gaps:

- `StudentLeavesScreen` — add `PageHeader`; `Skeleton` on first load.
- Status labels are hardcoded English in two files (`StudentLeaveRow`,
  `StudentLeaveDetailScreen`) — move to one i18n-backed helper in `constants.ts`.
- Dates render as raw `YYYY-MM-DD` — format through `common/utils/datetime.ts`
  (pinned Asia/Kolkata; calendar dates never shifted).
- `CancelRequestSheet.tsx` → route `app/(protected)/student-leaves/[id]/cancel.tsx`,
  a form screen like every other form.
- `StudentLeaveDetailScreen` — replace the bare back chevron with `PageHeader`;
  use `StatusPill`.

### 6.3 The approver's view

`components/ApplicantCard.tsx`, rendered on the leave detail screen **only when
the viewer may approve**: `ProfileAvatar` + name, class and section, campus,
admission and roll number, and a tap-to-call guardian row.

`ApproveStudentLeavesScreen` gains `SearchFilterBar` (a trust's head can face a
long queue), `Skeleton` on first load, and splits "Needs your approval" from
"Waiting on the class teacher" using the queue marker from §4.3.

The detail screen shows the approval trail as a `DetailCard`:
*Approved by Ms. Shah (class teacher), 14 Sep · Awaiting principal.*

---

## 7. Testing

**Server** — `modules/student_leaves/tests/test_services_state_machine.py`:

- rewrite `test_approve_admin_required_routes_through_pending_admin`, which
  currently passes only because its fixture puts the teacher on leave;
- head approves at `pending_admin` with the class teacher **present** → `approved`;
- class teacher cannot approve at `pending_admin`;
- head of another campus cannot approve (branch scope);
- `pending_admin` rows appear in the head queue;
- flag ON + teacher away → one head action yields `approved` (D3);
- flipping the tenant flag does not re-route an in-flight request (D7);
- notification recipients are campus-scoped (§4.4).

**Panel** — `school-policies-section.test.tsx`, following
`login-access-section.test.tsx`: renders the current value, PATCHes on toggle,
and surfaces an error toast on failure.

**Mobile** — no simulator or Android SDK on the build machine, so the mobile
screens cannot be run or screenshotted here. Verification is `tsc --noEmit`,
`expo lint --no-cache` (scope covers `modules/`), and a screenshot pass by the
user.

---

## 8. Build order

Schema → service → API → clients, each step leaving the tree buildable.

1. Migration 142 (approval trail columns)
2. Authority split + state machine + queues + campus-scoped notifications
3. `applicant` block on the payload, eager-loaded
4. Platform `school-policies` endpoints
5. Panel policies section
6. `student-leaves` mobile finish + `ApplicantCard` + approval trail
7. `teacher-leaves` mobile rebuild
8. Tests throughout; ADR-024 recording D2/D3; module doc `docs/modules/student-leave.md`

---

## 9. Out of scope

- Two-step approval for staff/teacher leave (D4)
- admin-web leave screens (`TeacherLeavesTab.tsx`)
- Parent-initiated leave on behalf of a child
- Report cards (unrelated; tracked as debt 49)

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Tenants already holding `pending_admin` rows stuck by the current bug | The authority fix releases them on deploy; no data repair needed. Verify count before/after in prod |
| `teacher-leaves` rebuild is a large diff in one module | Rebuild is confined to `client/modules/teacher-leaves` + its routes; server contract untouched |
| Mobile cannot be run on this machine | Stated upfront; user screenshot pass before the work is called done |
| Payload grows with the `applicant` block | Eager-loaded, and guardian contact is approver-gated so list responses stay lean |
