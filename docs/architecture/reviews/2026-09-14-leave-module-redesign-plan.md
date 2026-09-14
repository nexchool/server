# Leave Module Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the two-step student leave approval (class teacher → principal) actually work, switchable per client from the panel, and rebuild the mobile leave screens onto the app's house pattern.

**Architecture:** The sequential state machine already exists in `modules/student_leaves/services.py` but is unreachable — one blurred authorisation predicate blocks the principal and one queue filter hides the work. We split that predicate by intent, make the head queue show `pending_admin` rows, record both decisions, add the applicant context an approver needs, expose the switch through a new platform `school-policies` endpoint edited from the panel, and rebuild the mobile screens using the shared components the rest of the app already uses.

**Tech Stack:** Flask + SQLAlchemy 2 + Alembic (server) · Next.js 16 + TanStack Query v5 + vitest (panel) · Expo ~54 + expo-router + react-hook-form + zod + TanStack Query (client)

**Spec:** `server/docs/architecture/reviews/2026-09-14-leave-module-redesign.md`

**Branch:** all work on `develop` in each repo (v2 migration period — no feature branches).

---

## Commands

| What | Command |
|---|---|
| Server tests | `cd server && venv/bin/pytest modules/student_leaves/tests/ -v` |
| One server test | `cd server && venv/bin/pytest modules/student_leaves/tests/test_services_state_machine.py::test_name -v` |
| Migration | `cd server && venv/bin/flask db upgrade` / `venv/bin/flask db current` |
| Panel tests | `cd panel && npm test` |
| Panel types | `cd panel && npm run typecheck` |
| Client types | `cd client && npx tsc --noEmit` |
| Client lint | `cd client && npx expo lint app modules common --no-cache` |

⚠️ Two local databases exist. `pytest` hits the host Postgres (`localhost:5432`); the browser/app hits the Docker one. Run `flask db upgrade` against **both** before manual testing.

⚠️ This machine has no Xcode simulator runtime and no Android SDK — the Expo client cannot be run here. Client tasks are verified by `tsc --noEmit` + `expo lint`, then by a screenshot pass from the user.

---

## File Structure

**Server**

| File | Responsibility |
|---|---|
| `server/migrations/versions/142_student_leave_approval_trail.py` | new — two columns recording the class teacher's decision |
| `server/modules/student_leaves/models.py` | +2 columns, `to_dict` gains `applicant` + trail fields |
| `server/modules/student_leaves/services.py` | authority split, state machine, head queue, campus-scoped notify |
| `server/modules/student_leaves/applicant.py` | new — builds the `applicant` payload block, one responsibility, keeps `services.py` from growing |
| `server/modules/platform/services.py` | `get_tenant_school_policies` / `update_tenant_school_policies` |
| `server/modules/platform/routes.py` | `GET`/`PATCH /tenants/<id>/school-policies` |
| `server/modules/student_leaves/tests/test_services_state_machine.py` | state machine + authority tests |
| `server/modules/student_leaves/tests/test_head_queue.py` | new — queue visibility + branch scope |
| `server/modules/student_leaves/tests/test_applicant_payload.py` | new — applicant block + approver gating |
| `server/tests/test_platform_school_policies.py` | new — platform endpoint |

**Panel**

| File | Responsibility |
|---|---|
| `panel/types/index.ts` | `TenantSchoolPolicies` type |
| `panel/hooks/useApi.ts` | `useTenantSchoolPolicies`, `useUpdateSchoolPolicies` |
| `panel/app/(dashboard)/dashboard/tenants/[id]/school-policies-section.tsx` | new — the toggle card |
| `panel/app/(dashboard)/dashboard/tenants/[id]/school-policies-section.test.tsx` | new |
| `panel/app/(dashboard)/dashboard/tenants/[id]/tenant-detail-view.tsx` | mount the section |

**Client — student-leaves**

| File | Responsibility |
|---|---|
| `client/modules/student-leaves/constants.ts` | one i18n-backed `statusLabel()`; delete the two hardcoded maps |
| `client/modules/student-leaves/types.ts` | `applicant` + trail fields |
| `client/modules/student-leaves/components/ApplicantCard.tsx` | new — who is this child |
| `client/modules/student-leaves/components/ApprovalTrailCard.tsx` | new — step 1 / step 2 |
| `client/app/(protected)/student-leaves/[id]/cancel.tsx` + `screens/CancelLeaveScreen.tsx` | new — replaces `CancelRequestSheet.tsx` (deleted) |
| `client/modules/student-leaves/screens/StudentLeavesScreen.tsx` | `PageHeader`, `Skeleton`, formatted dates |
| `client/modules/student-leaves/screens/StudentLeaveDetailScreen.tsx` | `PageHeader`, `StatusPill`, applicant + trail |
| `client/modules/student-leaves/screens/ApproveStudentLeavesScreen.tsx` | `SearchFilterBar`, `Skeleton`, needs-you vs waiting split |

**Client — teacher-leaves (rebuild)**

| File | Responsibility |
|---|---|
| `client/common/components/StatTiles.tsx` | new — the 3-up count tiles both leave screens need |
| `client/modules/teacher-leaves/components/LeaveRequestCard.tsx` | new — house card |
| `client/modules/teacher-leaves/validation/schemas.ts` | new — zod schema for apply |
| `client/modules/teacher-leaves/screens/MyTeacherLeavesScreen.tsx` | rewritten, list only |
| `client/modules/teacher-leaves/screens/TeacherLeaveFormScreen.tsx` + `app/(protected)/teacher-leaves/new.tsx` | new — apply as a route |
| `client/modules/teacher-leaves/screens/TeacherLeaveBalanceScreen.tsx` + `app/(protected)/teacher-leaves/balance/[type].tsx` | new |
| `client/modules/teacher-leaves/screens/TeacherLeavePolicyScreen.tsx` + `app/(protected)/teacher-leaves/policy.tsx` | new |
| `client/modules/teacher-leaves/hooks/useTeacherLeaves.ts` | converted to TanStack Query |
| **Deleted** | `components/LeaveBalanceModal.tsx`, `components/LeavePolicyModal.tsx`, `components/CancelRequestSheet.tsx` (student) |

---

## Task 1: Migration — record both decisions

**Files:**
- Create: `server/migrations/versions/142_student_leave_approval_trail.py`
- Modify: `server/modules/student_leaves/models.py`

- [ ] **Step 1: Confirm the current migration head**

Run: `cd server && venv/bin/flask db current`
Expected: revision `141` (`141_hostel_master_record_details`). If it differs, use the reported head as `down_revision` below.

- [ ] **Step 2: Write the migration**

Create `server/migrations/versions/142_student_leave_approval_trail.py`:

```python
"""student_leaves: record the class teacher's decision separately

`decided_by_id` is a single column, so when a leave passes through the
principal the class teacher's approval is overwritten and the school loses
the record of who first agreed. Two nullable columns rather than a decisions
child table: the chain is two steps by design.

Revision ID: 142
Revises: 141
"""

import sqlalchemy as sa
from alembic import op

revision = "142"
down_revision = "141"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "student_leaves",
        sa.Column("class_teacher_decided_by_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "student_leaves",
        sa.Column("class_teacher_decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_student_leaves_class_teacher_decided_by",
        "student_leaves",
        "users",
        ["class_teacher_decided_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_student_leaves_class_teacher_decided_by",
        "student_leaves",
        type_="foreignkey",
    )
    op.drop_column("student_leaves", "class_teacher_decided_at")
    op.drop_column("student_leaves", "class_teacher_decided_by_id")
```

No backfill: existing rows have exactly one decision, already correct in `decided_by_id`.

- [ ] **Step 3: Add the columns to the model**

In `server/modules/student_leaves/models.py`, immediately after the `decided_at` column:

```python
    # The class teacher's approval, kept separately so the principal's
    # decision does not overwrite it. See migration 142.
    class_teacher_decided_by_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    class_teacher_decided_at = db.Column(db.DateTime(timezone=True), nullable=True)
```

And with the other relationships:

```python
    class_teacher_decided_by = db.relationship("User", foreign_keys=[class_teacher_decided_by_id])
```

And in `to_dict()`, after `"decided_at"`:

```python
            "class_teacher_decided_by_name": (
                self.class_teacher_decided_by.name if self.class_teacher_decided_by else None
            ),
            "class_teacher_decided_at": (
                self.class_teacher_decided_at.isoformat() if self.class_teacher_decided_at else None
            ),
```

- [ ] **Step 4: Apply and verify**

Run: `cd server && venv/bin/flask db upgrade && venv/bin/flask db current`
Expected: `142 (head)`

Run: `cd server && venv/bin/flask db downgrade && venv/bin/flask db upgrade`
Expected: both succeed — the migration is reversible.

- [ ] **Step 5: Commit**

```bash
cd server && git add migrations/versions/142_student_leave_approval_trail.py modules/student_leaves/models.py
git commit -m "feat(student-leaves): record the class teacher's decision separately"
```

---

## Task 2: Split approval authority by intent

The bug. `_actor_is_authorized_approver` asks one question for two jobs, so an admin can never finish a `pending_admin` leave while the class teacher is present — which is always, right after that teacher approved.

**Files:**
- Modify: `server/modules/student_leaves/services.py` (`_actor_is_authorized_approver` at ~482, `approve` at ~226, `reject` at ~288)
- Test: `server/modules/student_leaves/tests/test_services_state_machine.py`

- [ ] **Step 1: Write the failing tests**

Append to `server/modules/student_leaves/tests/test_services_state_machine.py`:

```python
def test_head_approves_pending_admin_with_class_teacher_present(
    tenant_ctx, student_user, class_with_teacher, admin_user, enable_admin_approval
):
    """The principal finishes the leave while the class teacher is at work.

    This is the ordinary case — the teacher just approved, so they are plainly
    not away — and it was impossible before the authority split.
    """
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    after_teacher = approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
    assert after_teacher.status == "pending_admin"
    assert after_teacher.class_teacher_decided_by_id == class_with_teacher.teacher_row.user_id
    assert after_teacher.class_teacher_decided_at is not None

    final = approve(leave.id, actor_user_id=admin_user.id)
    assert final.status == "approved"
    assert final.decided_by_id == admin_user.id
    # The class teacher's approval survives the principal's.
    assert final.class_teacher_decided_by_id == class_with_teacher.teacher_row.user_id


def test_class_teacher_cannot_approve_at_pending_admin(
    tenant_ctx, student_user, class_with_teacher, enable_admin_approval
):
    """A teacher may not wave through their own escalation to the principal."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    with pytest.raises(AuthorizationError):
        approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)


def test_head_approves_both_steps_when_class_teacher_away(
    tenant_ctx, student_user, class_with_teacher, admin_user,
    enable_admin_approval, teacher_on_leave_today,
):
    """Teacher away: one head action completes the request (spec D3).

    A child's leave must not wait a week for a teacher to come back.
    """
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    final = approve(leave.id, actor_user_id=admin_user.id)
    assert final.status == "approved"


def test_flag_flip_does_not_reroute_in_flight_request(
    tenant_ctx, student_user, class_with_teacher, db_session
):
    """A request is judged by the rule in force when it was filed (spec D7)."""
    from modules.academics.backbone.models import AcademicSettings

    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    assert leave.requires_admin_approval is False

    settings = (
        db_session.query(AcademicSettings)
        .filter(AcademicSettings.tenant_id == leave.tenant_id)
        .first()
    )
    settings.student_leave_admin_approval_required = True
    db_session.commit()

    result = approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
    assert result.status == "approved"
```

Ensure `AuthorizationError` is imported at the top of the file alongside the other service imports.

- [ ] **Step 2: Rewrite the test that passes for the wrong reason**

`test_approve_admin_required_routes_through_pending_admin` currently requests the
`teacher_on_leave_today` fixture and its docstring admits the flow only works
because of it. Replace that whole test with:

```python
def test_approve_admin_required_routes_through_pending_admin(
    tenant_ctx, student_user, class_with_teacher, enable_admin_approval
):
    """With the rule on, the class teacher's approval escalates rather than grants."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    assert leave.requires_admin_approval is True

    after_teacher = approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)
    assert after_teacher.status == "pending_admin"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd server && venv/bin/pytest modules/student_leaves/tests/test_services_state_machine.py -v`
Expected: `test_head_approves_pending_admin_with_class_teacher_present` FAILS with
`AuthorizationError: You are not authorized to approve this request`, and
`test_class_teacher_cannot_approve_at_pending_admin` FAILS because no error is raised.

- [ ] **Step 4: Replace the predicate with two**

In `server/modules/student_leaves/services.py`, replace `_actor_is_authorized_approver`
entirely with:

```python
def _holds_head_authority(leave: StudentLeave, actor_user_id: str) -> bool:
    """Holds the school-wide leave permission *and* authority over this child.

    Both halves matter. The permission alone would let the head of one campus
    decide for a child at a campus they do not run — approval is authority over
    the person, not a permission string (ADR-013).
    """
    try:
        from modules.rbac.services import has_permission

        if not has_permission(actor_user_id, "student.leave.approve.all"):
            return False
    except Exception:
        return False
    return student_is_allowed(leave.student_id)


def can_act_as_class_teacher(leave: StudentLeave, actor_user_id: str) -> bool:
    """The class teacher — or a head standing in while that teacher is away."""
    if not leave.class_teacher_id:
        return False

    teacher = (
        db.session.query(Teacher).filter(Teacher.id == leave.class_teacher_id).first()
    )
    if teacher and teacher.user_id == actor_user_id:
        return True

    if not _holds_head_authority(leave, actor_user_id):
        return False
    return _class_teacher_unavailable_today(leave.class_teacher_id, leave.tenant_id)


def can_act_as_head(leave: StudentLeave, actor_user_id: str) -> bool:
    """The principal's stage. The class teacher has no standing here — they may
    not wave through the escalation they just created."""
    return _holds_head_authority(leave, actor_user_id)


def _assert_may_decide(leave: StudentLeave, actor_user_id: str) -> bool:
    """Authorise the actor for the leave's *current* stage.

    Returns True when this action should finalise the leave outright — the head
    acting while the class teacher is away, who is senior to the teacher and
    need not sign twice (spec D3).
    """
    if leave.status == "pending_admin":
        if not can_act_as_head(leave, actor_user_id):
            raise AuthorizationError("You are not authorized to decide this request")
        return True

    if not can_act_as_class_teacher(leave, actor_user_id):
        raise AuthorizationError("You are not authorized to decide this request")

    acting_as_class_teacher = (
        db.session.query(Teacher)
        .filter(
            Teacher.id == leave.class_teacher_id,
            Teacher.user_id == actor_user_id,
        )
        .first()
        is not None
    )
    # A head standing in for an absent teacher completes both steps at once.
    return not acting_as_class_teacher
```

- [ ] **Step 5: Rewrite `approve()` to dispatch on stage**

Replace the body of `approve()` from the `leave = _get_or_404(leave_id)` line down
to `db.session.commit()` with:

```python
    leave = _get_or_404(leave_id)
    if leave.status not in ("pending_class_teacher", "pending_admin"):
        raise StateError("Leave is not pending approval")

    finalises = _assert_may_decide(leave, actor_user_id)
    now = utc_now()

    if leave.status == "pending_class_teacher":
        leave.class_teacher_decided_by_id = actor_user_id
        leave.class_teacher_decided_at = now
        if leave.requires_admin_approval and not finalises:
            leave.status = "pending_admin"
        else:
            leave.status = "approved"
            _sync_attendance_rows(leave, actor_user_id)
    else:  # pending_admin
        leave.status = "approved"
        _sync_attendance_rows(leave, actor_user_id)

    leave.decided_by_id = actor_user_id
    leave.decided_at = now
    db.session.commit()
```

The notification block below it is unchanged.

- [ ] **Step 6: Point `reject()` at the same gate**

In `reject()`, replace:

```python
    if not _actor_is_authorized_approver(leave, actor_user_id):
        raise AuthorizationError("You are not authorized to reject this request")
```

with:

```python
    _assert_may_decide(leave, actor_user_id)
```

- [ ] **Step 7: Update the remaining callers**

Run: `cd server && grep -rn "_actor_is_authorized_approver" modules/ --include="*.py"`
Expected: no results. If any remain (cancel-approval paths), replace each with
`_assert_may_decide(leave, actor_user_id)` and re-run.

- [ ] **Step 8: Run the full module suite**

Run: `cd server && venv/bin/pytest modules/student_leaves/tests/ -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
cd server && git add modules/student_leaves/services.py modules/student_leaves/tests/test_services_state_machine.py
git commit -m "fix(student-leaves): let the principal finish a pending_admin leave"
```

---

## Task 3: Make the principal's queue show the work

A `pending_admin` row appears in no queue today, because `admin_fallback_queue`
filters on the class teacher being away.

**Files:**
- Modify: `server/modules/student_leaves/services.py` (`admin_fallback_queue` at ~774)
- Create: `server/modules/student_leaves/tests/test_head_queue.py`

- [ ] **Step 1: Write the failing test**

Create `server/modules/student_leaves/tests/test_head_queue.py`:

```python
"""The principal's approval queue."""

import pytest

from modules.student_leaves.services import (
    admin_fallback_queue,
    approve,
    create_request,
)
from modules.student_leaves.tests.test_services_state_machine import _sample_payload


def test_pending_admin_rows_reach_the_head_queue(
    tenant_ctx, student_user, class_with_teacher, admin_user, enable_admin_approval
):
    """The stage exists to be acted on, so it has to be visible."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    queue = admin_fallback_queue(admin_user)
    ids = [row.id for row in queue]
    assert leave.id in ids


def test_head_queue_marks_why_each_row_is_there(
    tenant_ctx, student_user, class_with_teacher, admin_user, enable_admin_approval
):
    """'Needs your approval' and 'the teacher is away' are different jobs."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    approve(leave.id, actor_user_id=class_with_teacher.teacher_row.user_id)

    row = next(r for r in admin_fallback_queue(admin_user) if r.id == leave.id)
    assert row.to_dict()["queue_reason"] == "awaiting_head"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd server && venv/bin/pytest modules/student_leaves/tests/test_head_queue.py -v`
Expected: FAIL — `leave.id` is not in the queue (it is empty).

- [ ] **Step 3: Rewrite the queue as a union**

Replace `admin_fallback_queue` in `server/modules/student_leaves/services.py`:

```python
def admin_fallback_queue(user):
    """Everything a head is the right person to decide.

    Two different jobs share the screen, and the rows say which they are:
      - `awaiting_head`     — the class teacher approved and the school's rule
                              sends it on to the principal;
      - `teacher_away`      — the class teacher is on approved leave today, so
                              the head stands in for them.

    Both are branch-scoped: a head sees only children at campuses they run.
    """
    tenant_id = get_tenant_id()
    today = school_today()

    unavailable_teacher_ids = (
        db.session.query(TeacherLeave.teacher_id)
        .filter(
            TeacherLeave.tenant_id == tenant_id,
            TeacherLeave.status == "approved",
            TeacherLeave.start_date <= today,
            TeacherLeave.end_date >= today,
        )
        .subquery()
    )

    rows = eager_leaves(
        filter_by_student_ids(db.session.query(StudentLeave), StudentLeave.student_id)
        .filter(
            StudentLeave.tenant_id == tenant_id,
            db.or_(
                StudentLeave.status == "pending_admin",
                db.and_(
                    StudentLeave.class_teacher_id.in_(unavailable_teacher_ids),
                    db.or_(
                        StudentLeave.status.in_(
                            ("pending_class_teacher", "pending_admin")
                        ),
                        StudentLeave.cancel_requested_at.isnot(None),
                    ),
                ),
            ),
        )
        .order_by(StudentLeave.created_at.desc())
    ).all()

    for row in rows:
        row.queue_reason = (
            "awaiting_head" if row.status == "pending_admin" else "teacher_away"
        )
    return rows
```

- [ ] **Step 4: Surface the marker on the payload**

In `server/modules/student_leaves/models.py`, add a transient attribute default on
the class (so `to_dict` never raises for rows fetched outside a queue):

```python
    # Set by `admin_fallback_queue` to say why the row is in front of a head.
    # Transient — never persisted.
    queue_reason = None
```

and in `to_dict()`, before the closing brace:

```python
            "queue_reason": self.queue_reason,
```

- [ ] **Step 5: Run the tests**

Run: `cd server && venv/bin/pytest modules/student_leaves/tests/ -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd server && git add modules/student_leaves/services.py modules/student_leaves/models.py modules/student_leaves/tests/test_head_queue.py
git commit -m "fix(student-leaves): show pending_admin leaves in the head queue"
```

---

## Task 4: Notify only the heads who can act

`_admin_user_ids_for_tenant` pings every Admin in the tenant. In a 20-campus trust
that is 20 people told about a child 19 of them have no authority over.

**Files:**
- Modify: `server/modules/student_leaves/services.py` (`_admin_user_ids_for_tenant` at ~807, its call site in `approve`)
- Test: `server/modules/student_leaves/tests/test_head_queue.py`

- [ ] **Step 1: Write the failing test**

Append to `server/modules/student_leaves/tests/test_head_queue.py`:

```python
def test_escalation_notifies_only_heads_over_that_campus(
    tenant_ctx, student_user, class_with_teacher, admin_user,
    other_campus_admin_user, enable_admin_approval,
):
    """A head of another campus has no authority here and no reason to be told."""
    from modules.student_leaves.services import _admin_user_ids_for_leave

    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    recipients = _admin_user_ids_for_leave(leave)

    assert admin_user.id in recipients
    assert other_campus_admin_user.id not in recipients
```

Add the `other_campus_admin_user` fixture to
`server/modules/student_leaves/tests/conftest.py`, modelled on the existing
`admin_user` fixture but with its authority bound to a second school unit. Read
`admin_user` first and mirror its construction exactly — same role assignment
helper, different school unit.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd server && venv/bin/pytest modules/student_leaves/tests/test_head_queue.py::test_escalation_notifies_only_heads_over_that_campus -v`
Expected: FAIL — `ImportError: cannot import name '_admin_user_ids_for_leave'`.

- [ ] **Step 3: Add the scoped resolver**

In `server/modules/student_leaves/services.py`, add beside `_admin_user_ids_for_tenant`:

```python
def _admin_user_ids_for_leave(leave: StudentLeave) -> list:
    """Admins who could actually decide this leave.

    `_admin_user_ids_for_tenant` answers a different question — every admin in
    the trust — which for a multi-campus tenant means telling twenty people
    about a child nineteen of them have no authority over.
    """
    from core.branch_scope import user_has_access_to_student

    return [
        user_id
        for user_id in _admin_user_ids_for_tenant(leave.tenant_id)
        if user_has_access_to_student(user_id, leave.student_id)
    ]
```

`core/branch_scope.py` has **no** per-user variant today — every helper there reads
the *current* actor out of request context (`get_allowed_unit_ids()` off `g`), which
is the wrong question when you are choosing who to notify. So add one beside
`student_is_allowed` (line 242) that takes an explicit `user_id`, and have
`student_is_allowed` delegate to it with the context user — same logic, one copy:

```python
def user_has_access_to_student(user_id: str, student_id: str) -> bool:
    """Branch authority for a named user rather than the current actor.

    Every other helper here answers for whoever is making the request. Choosing
    notification recipients is the one case where the question is about somebody
    else, and borrowing the request-scoped answer would silently tell you about
    the wrong person.
    """
```

Implement it from `_compute_allowed_unit_ids`, parameterised by `user_id` instead of
reading `g`.

- [ ] **Step 4: Use it at the call site**

In `approve()`, replace:

```python
        admin_ids = _admin_user_ids_for_tenant(leave.tenant_id)
```

with:

```python
        admin_ids = _admin_user_ids_for_leave(leave)
```

- [ ] **Step 5: Run the tests**

Run: `cd server && venv/bin/pytest modules/student_leaves/tests/ -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd server && git add modules/student_leaves/services.py modules/student_leaves/tests/
git commit -m "fix(student-leaves): notify only heads with authority over the child"
```

---

## Task 5: Give the approver the child

An approver sees a leave type, dates and a reason — not even the student's name.

**Files:**
- Create: `server/modules/student_leaves/applicant.py`
- Create: `server/modules/student_leaves/tests/test_applicant_payload.py`
- Modify: `server/modules/student_leaves/models.py` (`to_dict`), `services.py` (`eager_leaves`)

- [ ] **Step 1: Write the failing test**

Create `server/modules/student_leaves/tests/test_applicant_payload.py`:

```python
"""The approver has to know which child this is."""

from modules.student_leaves.applicant import build_applicant
from modules.student_leaves.services import create_request
from modules.student_leaves.tests.test_services_state_machine import _sample_payload


def test_applicant_block_identifies_the_child(
    tenant_ctx, student_user, class_with_teacher
):
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    applicant = build_applicant(leave, include_contact=True)

    assert applicant["display_name"]
    assert applicant["admission_number"]
    assert applicant["class_name"]
    assert "campus_name" in applicant
    assert "profile_picture" in applicant


def test_guardian_contact_is_withheld_from_non_approvers(
    tenant_ctx, student_user, class_with_teacher
):
    """A list response never carries more contact data than the screen needs."""
    leave = create_request(_sample_payload(student_user), actor_user_id=student_user.id)
    applicant = build_applicant(leave, include_contact=False)

    assert "guardian_phone" not in applicant
    assert "guardian_name" not in applicant
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd server && venv/bin/pytest modules/student_leaves/tests/test_applicant_payload.py -v`
Expected: FAIL — `ModuleNotFoundError: modules.student_leaves.applicant`.

- [ ] **Step 3: Write the builder**

Create `server/modules/student_leaves/applicant.py`:

```python
"""Who applied — the block an approver needs to recognise the child.

Kept out of `services.py`, which is already long and is about the state
machine rather than about presenting a person.
"""

from __future__ import annotations

from typing import Any, Dict

from shared.s3_utils import profile_picture_public_url


def build_applicant(leave, *, include_contact: bool) -> Dict[str, Any]:
    """Identity fields for the student behind `leave`.

    `include_contact` carries the guardian's phone, which only somebody
    deciding the request has a reason to see.
    """
    student = leave.student
    if student is None:
        return {}

    cls = leave.class_ref
    school_unit = getattr(cls, "school_unit", None) if cls else None

    applicant: Dict[str, Any] = {
        "student_id": student.id,
        "display_name": student.display_name,
        "admission_number": student.admission_number,
        "roll_number": student.roll_number,
        "class_name": student._class_display_name(),
        "campus_name": getattr(school_unit, "name", None),
        "profile_picture": (
            profile_picture_public_url(student.user.profile_picture_url)
            if student.user
            else None
        ),
    }

    if include_contact:
        # Whichever parent the school has a number for — the approver is
        # ringing a house, not filling in a form.
        applicant["guardian_name"] = student.father_name or student.mother_name
        applicant["guardian_phone"] = student.father_phone or student.mother_phone

    return applicant
```

Verify the relationship name for the campus first:
`cd server && grep -n "school_unit" modules/classes/models.py | head`
and use the attribute that model actually exposes.

- [ ] **Step 4: Attach it to the payload**

In `server/modules/student_leaves/models.py`, add a transient flag beside `queue_reason`:

```python
    # Set by the route when the caller may decide this leave; controls whether
    # `to_dict` carries the guardian's phone number.
    viewer_may_decide = False
```

and in `to_dict()`:

```python
            "applicant": build_applicant(self, include_contact=self.viewer_may_decide),
```

with `from modules.student_leaves.applicant import build_applicant` imported inside
`to_dict` to avoid a circular import at module load.

- [ ] **Step 5: Set the flag where the caller is known**

In `server/modules/student_leaves/routes.py`, in `queue_for_me` and `queue_for_admin`,
set `row.viewer_may_decide = True` on each row before serialising — both queues
exist only for people who may decide. In `get_leave`, set it from the same predicates
the service uses:

```python
    from modules.student_leaves.services import can_act_as_class_teacher, can_act_as_head

    leave.viewer_may_decide = can_act_as_class_teacher(
        leave, g.current_user.id
    ) or can_act_as_head(leave, g.current_user.id)
```

- [ ] **Step 6: Eager-load what the block reads**

Replace `eager_leaves` in `services.py` — note the current version loads
`Student.person` twice, which is a copy-paste slip:

```python
def eager_leaves(query):
    """Load what `StudentLeave.to_dict` reads, instead of a query per row.

    The applicant block touches the student, their person record, their login
    (photo) and their class and campus. At 15,000 students an approver queue
    must not issue a query per row.
    """
    return query.options(
        selectinload(StudentLeave.student).selectinload(Student.person),
        selectinload(StudentLeave.student).selectinload(Student.user),
        selectinload(StudentLeave.class_ref),
        selectinload(StudentLeave.decided_by),
        selectinload(StudentLeave.class_teacher_decided_by),
    )
```

Add the campus relationship to that chain using the attribute confirmed in Step 3.

- [ ] **Step 7: Prove there is no N+1**

There is an existing scale test at `server/tests/test_student_leave_list_scale.py`.
Read it, and add a case asserting the query count for a 50-row approver queue is
constant. Follow the counting helper that file already uses — do not invent one.

Run: `cd server && venv/bin/pytest tests/test_student_leave_list_scale.py -v`
Expected: PASS.

- [ ] **Step 8: Run the suites**

Run: `cd server && venv/bin/pytest modules/student_leaves/tests/ tests/test_student_leave_list_scale.py tests/test_branch_enforce_student_leaves.py -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
cd server && git add modules/student_leaves/ tests/test_student_leave_list_scale.py
git commit -m "feat(student-leaves): carry the applicant's identity to the approver"
```

---

## Task 6: Platform endpoint for the school's policy

**Files:**
- Modify: `server/modules/platform/services.py`, `server/modules/platform/routes.py`
- Create: `server/tests/test_platform_school_policies.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_platform_school_policies.py`. Read
`server/tests/` for the platform-admin client fixture already in use and reuse it —
do not build a new auth path.

```python
"""Per-client school policies, edited from the panel."""


def test_get_returns_the_current_rule(platform_client, tenant):
    res = platform_client.get(f"/api/platform/tenants/{tenant.id}/school-policies")
    assert res.status_code == 200
    assert res.get_json()["data"]["student_leave_requires_principal_approval"] is False


def test_patch_turns_the_rule_on(platform_client, tenant, db_session):
    from modules.academics.backbone.models import AcademicSettings

    res = platform_client.patch(
        f"/api/platform/tenants/{tenant.id}/school-policies",
        json={"student_leave_requires_principal_approval": True},
    )
    assert res.status_code == 200
    assert res.get_json()["data"]["student_leave_requires_principal_approval"] is True

    row = (
        db_session.query(AcademicSettings)
        .filter(AcademicSettings.tenant_id == tenant.id)
        .first()
    )
    assert row.student_leave_admin_approval_required is True


def test_patch_rejects_a_non_boolean(platform_client, tenant):
    res = platform_client.patch(
        f"/api/platform/tenants/{tenant.id}/school-policies",
        json={"student_leave_requires_principal_approval": "yes"},
    )
    assert res.status_code == 400


def test_unknown_tenant_is_404(platform_client):
    res = platform_client.patch(
        "/api/platform/tenants/does-not-exist/school-policies",
        json={"student_leave_requires_principal_approval": True},
    )
    assert res.status_code == 404
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd server && venv/bin/pytest tests/test_platform_school_policies.py -v`
Expected: FAIL with 404 on every case — the route does not exist.

- [ ] **Step 3: Add the service functions**

Append to `server/modules/platform/services.py`:

```python
def get_tenant_school_policies(tenant_id: str) -> Dict[str, Any]:
    """The per-client rules a school chooses for itself.

    Not `feature_flags`: that column says which modules a school has, and its
    double duty as a settings bag is something to undo rather than extend.
    These are policies inside a module the school already runs.
    """
    from modules.academics.services.bell_schedules import get_or_create_academic_settings

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}

    settings = get_or_create_academic_settings(tenant_id)
    return {
        "success": True,
        "tenant_id": tenant_id,
        "policies": {
            "student_leave_requires_principal_approval": bool(
                settings.student_leave_admin_approval_required
            ),
        },
    }


def update_tenant_school_policies(
    tenant_id: str,
    platform_admin_id: str,
    policies: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply supplied policies. Unknown keys are ignored, as with feature flags.

    Requests already in flight keep the rule they were filed under — the
    snapshot lives on the leave row, so nothing here re-routes them.
    """
    from modules.academics.services.bell_schedules import get_or_create_academic_settings

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return {"success": False, "error": "Tenant not found"}
    if not isinstance(policies, dict):
        return {"success": False, "error": "policies must be an object"}

    key = "student_leave_requires_principal_approval"
    if key in policies:
        value = policies[key]
        if not isinstance(value, bool):
            return {"success": False, "error": f"{key} must be true or false"}
        settings = get_or_create_academic_settings(tenant_id)
        settings.student_leave_admin_approval_required = value
        settings.updated_at = utc_now()
        db.session.commit()

    log_platform_action(
        platform_admin_id=platform_admin_id,
        action="tenant.school_policies.updated",
        tenant_id=tenant_id,
        metadata={"policies": policies},
    )
    return get_tenant_school_policies(tenant_id)
```

- [ ] **Step 4: Add the routes**

Append to `server/modules/platform/routes.py`, copying the decorator stack from
`update_tenant_features` exactly:

```python
@platform_bp.route("/tenants/<tenant_id>/school-policies", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def get_tenant_school_policies(tenant_id):
    """GET /platform/tenants/<id>/school-policies"""
    result = services.get_tenant_school_policies(tenant_id)
    if not result["success"]:
        return not_found_response("Tenant")
    return success_response(data=result["policies"])


@platform_bp.route("/tenants/<tenant_id>/school-policies", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def update_tenant_school_policies(tenant_id):
    """PATCH /platform/tenants/<id>/school-policies
    Body: { student_leave_requires_principal_approval: bool }
    """
    data = request.get_json() or {}
    result = services.update_tenant_school_policies(
        tenant_id=tenant_id,
        platform_admin_id=g.current_user.id,
        policies=data,
    )
    if not result["success"]:
        if result["error"] == "Tenant not found":
            return not_found_response("Tenant")
        return error_response("BadRequest", result["error"], 400)
    return success_response(data=result["policies"], message="School policies updated")
```

- [ ] **Step 5: Run the tests**

Run: `cd server && venv/bin/pytest tests/test_platform_school_policies.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd server && git add modules/platform/ tests/test_platform_school_policies.py
git commit -m "feat(platform): per-tenant school policies endpoint"
```

---

## Task 7: The panel toggle

**Files:**
- Modify: `panel/types/index.ts`, `panel/hooks/useApi.ts`, `panel/app/(dashboard)/dashboard/tenants/[id]/tenant-detail-view.tsx`
- Create: `panel/app/(dashboard)/dashboard/tenants/[id]/school-policies-section.tsx` and its `.test.tsx`

- [ ] **Step 1: Write the failing test**

Read `panel/app/(dashboard)/dashboard/tenants/[id]/login-access-section.test.tsx`
first and mirror its mocking setup exactly. Create
`school-policies-section.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SchoolPoliciesSection } from "./school-policies-section";

const mutateAsync = vi.fn();

vi.mock("@/hooks/useApi", () => ({
  useTenantSchoolPolicies: () => ({
    data: { student_leave_requires_principal_approval: false },
    isLoading: false,
  }),
  useUpdateSchoolPolicies: () => ({ mutateAsync, isPending: false }),
}));

describe("SchoolPoliciesSection", () => {
  it("shows the rule as off when the school has not asked for it", () => {
    render(<SchoolPoliciesSection tenantId="t1" />);
    expect(screen.getByRole("switch")).not.toBeChecked();
  });

  it("turns the rule on", async () => {
    mutateAsync.mockResolvedValueOnce({});
    render(<SchoolPoliciesSection tenantId="t1" />);
    await userEvent.click(screen.getByRole("switch"));
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        student_leave_requires_principal_approval: true,
      }),
    );
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd panel && npm test -- school-policies-section`
Expected: FAIL — cannot resolve `./school-policies-section`.

- [ ] **Step 3: Add the type**

In `panel/types/index.ts`:

```ts
export type TenantSchoolPolicies = {
  student_leave_requires_principal_approval: boolean;
};
```

- [ ] **Step 4: Add the hooks**

In `panel/hooks/useApi.ts`, following `useTenantAuthPolicy` / `useUpdateAuthPolicy`:

```ts
export function useTenantSchoolPolicies(tenantId: string | null) {
  return useQuery({
    queryKey: ["tenant", tenantId, "school-policies"],
    queryFn: () =>
      apiRequest<TenantSchoolPolicies>(
        `/api/platform/tenants/${tenantId}/school-policies`,
      ),
    enabled: !!tenantId,
  });
}

export function useUpdateSchoolPolicies(tenantId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (policies: Partial<TenantSchoolPolicies>) =>
      apiRequest<TenantSchoolPolicies>(
        `/api/platform/tenants/${tenantId}/school-policies`,
        { method: "PATCH", body: JSON.stringify(policies) },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["tenant", tenantId, "school-policies"],
      });
    },
  });
}
```

Match `apiRequest`'s real signature — check `panel/lib/api.ts:126` and copy the
call shape an existing PATCH hook uses rather than the sketch above.

- [ ] **Step 5: Build the section**

Create `school-policies-section.tsx`, exporting `SchoolPoliciesSection` as a named
export taking `{ tenantId }: { tenantId: string }` — the shape the test imports. Copy the card chrome, heading level and
`Switch` usage from `login-access-section.tsx` so it sits flush with the sections
around it. Copy for the toggle:

- Label: **Principal approval for student leave**
- Help text: *When on, a student's leave request goes to the class teacher first, and to the principal after the teacher approves. Both must approve before the leave is granted. When the class teacher is on leave, the principal's approval alone completes the request.*
- On failure: `toast.error(getErrorMessage(e))`, exactly as the auth-policy handlers do.

- [ ] **Step 6: Mount it**

In `tenant-detail-view.tsx`, render `<SchoolPoliciesSection tenantId={tenant.id} />`
directly after the login-access section.

- [ ] **Step 7: Run tests and types**

Run: `cd panel && npm test && npm run typecheck`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
cd panel && git add .
git commit -m "feat(tenants): configure principal approval for student leave"
```

---

## Task 8: Finish the student-leaves mobile screens

**Files:**
- Modify: `client/modules/student-leaves/{constants.ts,types.ts}`, `screens/{StudentLeavesScreen,StudentLeaveDetailScreen,ApproveStudentLeavesScreen}.tsx`, `components/StudentLeaveRow.tsx`
- Create: `components/ApplicantCard.tsx`, `components/ApprovalTrailCard.tsx`, `screens/CancelLeaveScreen.tsx`, `app/(protected)/student-leaves/[id]/cancel.tsx`
- Delete: `components/CancelRequestSheet.tsx`
- Modify: `client/i18n/resources/{en,hi,gu}/studentLeaves.json`

- [ ] **Step 1: One status label, translated**

`STATUS_LABEL` is hardcoded English in both `StudentLeaveRow.tsx` and
`StudentLeaveDetailScreen.tsx`. Delete both maps. In `constants.ts`:

```ts
/** Status wording lives in one place, and in the school's language. */
export function statusLabelKey(status: LeaveStatus): string {
  return `status.${status}`;
}
```

Callers use `t(statusLabelKey(leave.status))`. Add the five keys to all three
`studentLeaves.json` files. Use school wording, not state names —
`pending_class_teacher` → "With class teacher", `pending_admin` → "With principal".

- [ ] **Step 2: Types for the new payload**

In `types.ts`, add to `StudentLeave`:

```ts
  class_teacher_decided_by_name: string | null;
  class_teacher_decided_at: string | null;
  queue_reason: 'awaiting_head' | 'teacher_away' | null;
  applicant?: {
    student_id: string;
    display_name: string | null;
    admission_number: string | null;
    roll_number: number | null;
    class_name: string | null;
    campus_name: string | null;
    profile_picture: string | null;
    guardian_name?: string | null;
    guardian_phone?: string | null;
  };
```

- [ ] **Step 3: Dates through the school clock**

`StudentLeaveRow` and `StudentLeaveDetailScreen` render `leave.start_date` raw.
Format every one through `client/common/utils/datetime.ts` — read that file and use
its calendar-date formatter, never `new Date(iso)`, which shifts the day.

- [ ] **Step 4: Cancellation becomes a screen**

Create `screens/CancelLeaveScreen.tsx` and route
`app/(protected)/student-leaves/[id]/cancel.tsx`. Copy the skeleton of
`StudentLeaveFormScreen.tsx` exactly — `PageHeader` with back chevron + Cancel
`Link`, `noHorizontalPadding divider={false}`, one `FormSection` with a
`FormTextArea` for the reason, pinned full-width primary `Button`, dirty-check
"Discard?" via `useDialog().confirm` plus the Android `BackHandler` effect.

In `StudentLeaveDetailScreen`, replace the sheet with
`router.push({ pathname: '/(protected)/student-leaves/[id]/cancel', params: { id } })`.

Delete `components/CancelRequestSheet.tsx` and its import.

- [ ] **Step 5: The applicant card**

Create `components/ApplicantCard.tsx`: `ProfileAvatar` (size 48) + name as
`titleMd`, then class · campus, admission and roll number, and a guardian row whose
phone opens the dialler via `Linking.openURL('tel:…')`. Card chrome copies
`StudentLeaveRow` — `radius.xl`, `padding lg`, `gap sm`, `elevation.card`, no
hairline border. Render nothing when `leave.applicant` is undefined.

- [ ] **Step 6: The approval trail**

Create `components/ApprovalTrailCard.tsx` using `DetailCard` + `DetailRow`: one row
for the class teacher's decision (name + date, from
`class_teacher_decided_by_name` / `class_teacher_decided_at`) and one for the
principal's, showing "Awaiting principal" while `status === 'pending_admin'`.

- [ ] **Step 7: Detail screen chrome**

In `StudentLeaveDetailScreen`, replace the bare `AppIcon chevron-back` with
`PageHeader` (`onBack`, `backLabel`, `noHorizontalPadding`, `divider={false}`), and
the hand-rolled status pill `View` with `StatusPill`. Render `ApplicantCard` above
the leave card when `leave.applicant` is present, and `ApprovalTrailCard` below it.

- [ ] **Step 8: List and queue screens**

`StudentLeavesScreen`: add `PageHeader` in place of the bare `Text headlineLg`;
render `Skeleton` rows on first load instead of an empty list.

`ApproveStudentLeavesScreen`: add `SearchFilterBar` filtering by student name and
admission number; `Skeleton` on first load; and inside the "New requests" tab, split
the list into two sections — **Needs your approval** (`queue_reason === 'awaiting_head'`,
or the viewer is the class teacher) and **Class teacher is away** (`'teacher_away'`) —
with section headers styled `labelMd onSurfaceVariant`, matching the notifications
screen.

- [ ] **Step 9: Verify**

Run: `cd client && npx tsc --noEmit`
Expected: no errors.

Run: `cd client && npx expo lint app modules common --no-cache`
Expected: no errors.

- [ ] **Step 10: Commit**

```bash
cd client && git add modules/student-leaves app/\(protected\)/student-leaves i18n/resources
git commit -m "feat(student-leaves): approver context, approval trail, house-pattern screens"
```

---

## Task 9: Rebuild the teacher-leaves screens

The 1439-line screen is the inconsistency. Rebuild it from the shared components
rather than editing it.

**Files:** as listed under *Client — teacher-leaves* in File Structure.

- [ ] **Step 1: Read the two reference screens first**

Read `client/modules/student-leaves/screens/StudentLeavesScreen.tsx` (list rhythm)
and `StudentLeaveFormScreen.tsx` (form rhythm) before writing anything. Those two
files define the pattern this task is copying. Do not design a new layout.

- [ ] **Step 2: Extract the stat tiles**

Create `client/common/components/StatTiles.tsx` — a row of equal-width count tiles
(`backgroundColor: palette.surfaceContainerLow`, `padding: spacing.md`,
`borderRadius: radius.md`, centred), taking
`tiles: { label: string; value: string; tone?: keyof Palette }[]`. The pattern is
copied from `modules/classes/screens/ClassDetailScreen.tsx:166-175`; migrate that
screen to the shared component in the same commit so there is one copy.

- [ ] **Step 3: Convert the hook to TanStack Query**

`hooks/useTeacherLeaves.ts` is hand-rolled `useState`/`useCallback`, so nothing
invalidates after an apply and every screen refetches by hand. Rewrite it with
`useQuery`/`useMutation`, exporting a `teacherLeavesKeys` object shaped exactly like
`studentLeavesKeys` in `modules/student-leaves/hooks/useStudentLeaves.ts`, with
mutations invalidating `teacherLeavesKeys.all`. The underlying
`teacherLeaveService` calls are unchanged.

- [ ] **Step 4: The card**

Create `components/LeaveRequestCard.tsx` by copying `StudentLeaveRow.tsx` and
swapping the fields: `PressScale`, `radius.xl`, `padding lg`, `gap sm`, 4px flat
left accent from `statusAccentToken`, `elevation.card`, **no border**, `StatusPill`
for status. Where the card offers cancel, it is an icon button
(`AppIcon trash-outline lg error`) in a right-aligned row in the card header — not
a text link, not a footer.

- [ ] **Step 5: Apply becomes a route**

Create `validation/schemas.ts` with a zod schema mirroring
`modules/student-leaves/validation/schemas.ts` (leave type, start/end date, half
day, reason), then `screens/TeacherLeaveFormScreen.tsx` and route
`app/(protected)/teacher-leaves/new.tsx`.

Copy `StudentLeaveFormScreen.tsx` wholesale and change the fields: `useForm` +
`zodResolver`, `FormSection` cards, `FormSelect` for leave type, `FormDatePicker`
for the dates, `FormTextArea` for the reason, `PageHeader` with back chevron +
Cancel `Link`, pinned full-width primary `Button`, dirty-check "Discard?" +
Android `BackHandler`.

Carry over the two behaviours the old modal had and the new screen must keep:
the **balance check** (block submit when the request exceeds the available days for
that type) and the **holiday warning** (tell the teacher when the range covers
non-working days). Both live in the old `ApplyModal` — port the logic, not the
layout.

Defaults use `schoolTodayIso()`, never `new Date().toISOString().slice(0,10)`.

- [ ] **Step 6: Balance and policy become routes**

Create `screens/TeacherLeaveBalanceScreen.tsx` +
`app/(protected)/teacher-leaves/balance/[type].tsx`, and
`screens/TeacherLeavePolicyScreen.tsx` + `app/(protected)/teacher-leaves/policy.tsx`.
Both are `PageHeader` + `DetailCard`/`DetailRow` scrolls — the same content the two
modals rendered, in a screen.

Delete `components/LeaveBalanceModal.tsx` and `components/LeavePolicyModal.tsx`.

- [ ] **Step 7: Rewrite the list screen**

Rewrite `screens/MyTeacherLeavesScreen.tsx` as:

```
PageHeader (title + Apply action)
DetailTabs  [ My leaves | Holidays ]        ← one level only
  My leaves:
    StatTiles  [ Approved | Pending | Rejected ]
    balance strip (horizontal scroll of balance cards → push balance/[type])
    FilterChips [ All | Pending | Approved | Rejected ]
    FlatList of LeaveRequestCard
      Skeleton on first load
      EmptyState with an "Apply for leave" action
  Holidays:
    existing holiday list, unchanged content
FAB 56pt radius.full → /teacher-leaves/new
```

The nested second `DetailTabs` row (Summary / Balance / Requests) is removed — those
become sections in one scroll.

Every `StyleSheet` block that restates a theme token goes; no `fontFamily` or
`fontWeight` in the module — use `Text` variants. No `numberOfLines={1}` on labels
or hints that explain an action.

- [ ] **Step 8: Check nothing still points at the deleted pieces**

Run: `cd client && grep -rn "LeaveBalanceModal\|LeavePolicyModal\|ApplyModal\|CancelRequestSheet" app modules common`
Expected: no results.

Run: `cd client && ls -d app modules common`
Expected: all three exist — a grep over a path that does not exist returns nothing
and proves nothing.

- [ ] **Step 9: Verify**

Run: `cd client && npx tsc --noEmit`
Expected: no errors.

Run: `cd client && npx expo lint app modules common --no-cache`
Expected: no errors.

- [ ] **Step 10: Commit**

```bash
cd client && git add modules/teacher-leaves common/components/StatTiles.tsx modules/classes app/\(protected\)/teacher-leaves
git commit -m "refactor(teacher-leaves): rebuild the leave screens on the house pattern"
```

---

## Task 10: Record the decisions and close out

**Files:**
- Create: `server/docs/architecture/adr/ADR-024-leave-approval-authority-by-stage.md`
- Create: `server/docs/modules/student-leave.md`
- Modify: `server/docs/architecture/debt-register.md`, `.claude/memory/v2-refactor.md`

- [ ] **Step 1: Write ADR-024**

Read `ADR-013-authority-belongs-to-the-relationship.md` for house format and follow
it. Record: approval authority is evaluated **per stage**, not per person (D2); the
head standing in for an absent teacher completes both steps in one action (D3); and
the rule is snapshotted at submit so a policy change never re-routes work in flight
(D7). ADR-013 is the direct ancestor — link it.

- [ ] **Step 2: Write the module doc**

Create `server/docs/modules/student-leave.md` following the shape of
`docs/modules/attendance.md`: the states and who moves between them, the tenant
policy and where it is configured, the queues, notification recipients, and the
surfaces (mobile student, class teacher, principal).

- [ ] **Step 3: Register any shortcut taken**

If any step in this plan left a shortcut, add a row to
`server/docs/architecture/debt-register.md` in the same commit that took it. If none
was taken, skip.

- [ ] **Step 4: Update the graph**

Run: `graphify update .`
Expected: prints `Rebuild failed` and exits 1 — that is normal on this repo
(`graph.html` is capped at 5,000 nodes; this corpus is ~8,200). Verify the run
landed by checking `graphify-out/graph.json` has a fresh mtime, not by the exit code.

- [ ] **Step 5: Commit the docs**

```bash
cd server && git add docs/
git commit -m "docs(student-leaves): ADR-024 and the student leave module doc"
```

- [ ] **Step 6: Dogfood before calling it done**

Invoke the `dogfooding-as-end-user` skill. Walk the whole flow as each persona —
student applying, class teacher approving, principal finishing, and a principal at
the wrong campus — with the rule both on and off, and with the class teacher away.
Tests passing is not the same as the feature working.

Then ask the user for a screenshot pass on the rebuilt mobile screens; they cannot
be run on this machine.

---

## Deployment notes

- Migration 142 runs on boot (`flask db upgrade`). Apply it to **both** local databases.
- Before deploying, count stuck rows: `SELECT count(*) FROM student_leaves WHERE status = 'pending_admin';` — those are requests the current bug has frozen. They are released by the Task 2 fix on deploy; no data repair needed. Count again after.
- No feature flag gates this. The switch defaults to off (`server_default=text("false")`), so every existing tenant keeps today's single-approval behaviour until a super-admin turns it on.
