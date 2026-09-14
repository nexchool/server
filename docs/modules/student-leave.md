# Student Leave

A child asks to be away from school, and the school decides. This module owns
the request, the chain of approval behind it, and the attendance rows that
follow from a granted one.

Staff leave is a separate module (`teacher_leaves`) with its own model,
balances and routes. Nothing here applies to it.

---

## The states

```
                    ┌────────────────────────┐
  submitted  ──▶    │ pending_class_teacher  │
                    └───────────┬────────────┘
                                │
              rule off  ────────┼────────  rule on
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
            ┌──────────┐              ┌────────────────┐
            │ approved │  ◀────────── │ pending_admin  │
            └──────────┘              └────────────────┘

  any pending state ──▶ rejected  (reason mandatory, terminal)
  any state ──▶ cancelled         (via a cancellation request)
```

Attendance rows are written **only** on the transition to `approved`, and
removed again if the leave is later cancelled.

---

## Who may decide

Authority is evaluated against the stage, not the person — see
[ADR-024](../architecture/adr/ADR-024-leave-approval-authority-by-stage.md).

| Stage | Who | Result |
|---|---|---|
| `pending_class_teacher`, rule off | the class teacher | `approved` |
| `pending_class_teacher`, rule on | the class teacher | `pending_admin` |
| `pending_class_teacher`, teacher away or none assigned | a head over that campus | `approved` — both stages, one action |
| `pending_admin` | a head over that campus | `approved` |

"A head" means a user holding `student.leave.approve.all` **and** branch
authority over the child. Not a role — a school may have several such people,
and narrowing it is done by taking the permission off roles that should not
have it.

The class teacher has no standing at `pending_admin`: they may not wave through
the escalation they created.

Cancellation of an already-filed leave stays the class teacher's call, or a
head's while that teacher is away.

---

## The policy, and where it is set

`academic_settings.student_leave_admin_approval_required` — one row per tenant.

Set from the **panel** (super-admin control plane), tenant detail →
*School policies* → *Principal approval for student leave*, via
`GET`/`PATCH /api/platform/tenants/<id>/school-policies`. Audit-logged as
`tenant.school_policies.updated`.

It is deliberately **not** a feature flag. Feature flags say which modules a
school has; this says how a module the school already runs behaves.

The value is snapshotted onto each leave as `requires_admin_approval` at submit
time, so changing it never re-routes requests already in flight.

---

## Queues

| Endpoint | Holds |
|---|---|
| `GET /api/student-leaves/queue/me` | requests waiting on the caller as class teacher |
| `GET /api/student-leaves/queue/admin` | requests waiting on the caller as a head |

The head's queue carries two different jobs, and every row says which via
`queue_reason`:

- `awaiting_head` — the school's rule sent it up after the class teacher approved
- `no_class_teacher` — the section has no primary class teacher at all
- `teacher_away` — the class teacher is on approved leave today

Both queues are branch-scoped.

A person can be in both queues at once — a principal who also holds a class is
ordinary in a small school — so the mobile screen fetches both and merges them.

---

## What an approver is shown

Every leave payload carries an `applicant` block: name, photo, class, campus,
medium, admission and roll number. The class comes from the **leave's own**
snapshot, not the student's current one, so a child moved sections in March
still shows the class the January request was filed against.

`guardian_name` and `guardian_phone` are added only when the viewer may decide
the request. A student reading their own leave is not handed a contact block
back, and neither is a list response.

All of it is eager-loaded (`eager_leaves`) — a head at a 15,000-student trust
opens this queue.

---

## Who is notified

| Event | Recipients |
|---|---|
| submitted | the class teacher — or, when the section has none, the heads who can act |
| escalated to `pending_admin` | heads **with authority over that child's campus** |
| approved / rejected | the student, and the class teacher who endorsed it |

The class teacher hears the outcome because they own the register: a leave
refused after they approved it means the child is expected in class.

---

## Surfaces

| Who | Where |
|---|---|
| Student | mobile — *My leaves*, apply, leave detail, request cancellation |
| Class teacher | mobile — *Leave approvals* → Student leaves |
| Head / principal | mobile — same screen, sectioned by why each row is theirs |
| Super admin | panel — the policy toggle |

There is no admin-web surface for student leave.

---

## Schema notes

- `class_teacher_id` is snapshotted at submit, so reassigning a child later does
  not move an in-flight request.
- `class_teacher_decided_by_id` / `class_teacher_decided_at` (migration 142)
  keep the first approval, which `decided_by_id` alone would overwrite.
- `queue_reason` and `viewer_may_decide` are transient attributes set by the
  service and the routes; they are never persisted.
