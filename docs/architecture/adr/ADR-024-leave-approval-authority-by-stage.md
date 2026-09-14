# ADR-024 — Leave Approval Authority Belongs to the Stage, Not the Person

## Status

Accepted

---

## Date

2026-09-14

---

# Context

Schools disagree about who signs off a child's absence, and both answers are
right for the school that holds them. In a primary of two hundred children the
class teacher knows every family and their word is final. A secondary of four
thousand wants the principal to see every absence, because a pattern of Friday
leaves is something only someone looking across classes can notice.

The product had no way to express that difference. `student_leaves` carried a
`requires_admin_approval` column and `approve()` already routed
`pending_class_teacher → pending_admin → approved`, but the sequence had never
worked and could not be switched on by anybody outside a test.

The reason it had never worked is the subject of this decision.

A single predicate, `_actor_is_authorized_approver`, answered one question —
*may this person touch this leave?* — for two different jobs. Its rule was: the
class teacher always, or an administrator **while the class teacher is on
approved leave today**. That rule is correct for the first stage. Applied to
the second it is nonsense: a leave reaches `pending_admin` precisely because
the class teacher has just approved it, and a teacher who has just approved
something is plainly not away. So every escalated leave was frozen — no
administrator could decide it, and `admin_fallback_queue` filtered on the same
condition, so it appeared in no queue for anyone to notice.

The same predicate let the class teacher approve at `pending_admin`, which
defeats the point of a school asking for a second signature.

---

# Decision

**Approval authority is evaluated against the stage the request is at, not
against the person in general.**

Two predicates replace the one:

| Predicate | Admits |
|---|---|
| `can_act_as_class_teacher` | the snapshotted class teacher; or a head with authority over the child **while that teacher is away or the section has none** |
| `can_act_as_head` | anyone holding `student.leave.approve.all` **with authority over that child's campus** |

`_assert_may_decide` picks the predicate from `leave.status`. The class teacher
has no standing at `pending_admin`.

Three consequences follow, each a deliberate choice rather than a side effect.

**A head standing in for an absent class teacher completes both stages in one
action.** The head is senior to the teacher; a second signature from the same
person is theatre, and a child's leave must not wait a week for somebody to
come back from illness.

**A section with no class teacher falls to the head, permanently.** A class
teacher leaving mid-year is ordinary in a trust of any size. Before this, such
a request was accepted, entered `pending_class_teacher`, and could be decided
by nobody at all. The school has already agreed the head stands in while a
class teacher is away; no class teacher at all is that situation without an end
date. An unrelated teacher still cannot touch it — falling to the head is not
falling to anybody.

**Authority means authority over the child, not the permission string.** Both
predicates end in a branch-scope check, so the head of one campus cannot decide
for a child at a campus they do not run. This is ADR-013 applied to a second
domain: authority belongs to the relationship.

---

# The rule is a school policy, and it is snapshotted

Which of the two chains a school runs is stored on `academic_settings` and set
per client from the panel. It is **not** a feature flag: `tenants.feature_flags`
answers *does this school have a hostel*, and its double duty as a settings bag
is already recorded in-code as something to undo rather than extend.

`requires_admin_approval` is copied onto each leave at submit. A request is
judged by the rule in force when it was filed, so turning the policy on does
not reach back and re-route work a teacher is already holding — which would
otherwise mean a teacher approving a request and watching it vanish into a
queue that did not exist when the child applied.

---

# Both decisions are kept

`decided_by_id` holds whoever acted last, so the principal's decision used to
erase the class teacher's. A school that asks for two signatures wants to see
both, so migration 142 adds `class_teacher_decided_by_id` and
`class_teacher_decided_at`.

Two columns rather than a `student_leave_decisions` child table: the chain is
two steps by design, and a general table would be more machinery than the
decision warrants. If a third stage is ever asked for, that is the point to
reconsider — not before.

---

# Consequences

- The escalated stage is reachable, and visible: the head's queue is the union
  of both jobs, each row marked `awaiting_head`, `no_class_teacher` or
  `teacher_away` so a screen can say why it is there.
- Escalation alerts go only to administrators with authority over that child's
  campus. `core.branch_scope.user_may_act_on_student` was added for this — every
  other helper there answers for the request's own caller, which is the wrong
  question when choosing recipients.
- The class teacher is told what the head decided about a leave they endorsed.
  They own the register: a leave refused after they approved it means the child
  is expected in class, and they were previously the last to know.
- Cancellation authority is unchanged — the class teacher, or a head while that
  teacher is away. Widening it would have been a change to who may act, and the
  decision recorded here is about stages, not about cancellation.

---

# Related

- ADR-013 — Authority Belongs to the Relationship, Not the Account
- `docs/modules/student-leave.md`
- `docs/architecture/reviews/2026-09-14-leave-module-redesign.md`
