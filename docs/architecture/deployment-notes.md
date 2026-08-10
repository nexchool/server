# Deployment notes — living document

> What a deploy of `develop` needs beyond "pull and restart", and why.
>
> **Nothing here has been applied to production.** The stabilization work is
> local-only until `develop` merges to `main`. Add a line here in the same
> commit that creates the need, the way `debt-register.md` works — a step
> remembered at deploy time is a step already forgotten.

**Last updated:** 2026-08-09.

---

## 1. Migrations — run `flask db upgrade`

`startup.sh` already runs migrations on boot, so this is a check rather than a
manual step. Four are new since the last `main`:

| Revision | What it does | If it does not run |
|---|---|---|
| `103_a_teacher_is_not_an_onboarder` | Revokes `school_setup.read` from the Teacher role in every tenant. | Teachers keep an onboarding permission they should not have. Nothing breaks. |
| `104_a_merge_records_who_and_why` | Adds `classes.merged_by_user_id` and `classes.merge_reason`. | **The API will not boot** — the model declares columns the table lacks. |
| `105_a_sub_admin_keeps_the_classes_module` | Grants `school_unit.read`, `programme.read`, `grade.read` to existing sub-admin roles that hold `class.read` / `class.manage`. | Existing sub-admins see an empty Classes screen, and editing one silently revokes their Classes access (see §4). |

`105` must run **after** the new sub-admin catalogue is deployed, which is
automatic — they ship in the same commit.

## 2. Redis is now required for rate limiting

`core/extensions.py` points Flask-Limiter at `REDIS_URL`. Production already
sets it (Celery uses the same instance), so this needs **verification, not
configuration**:

```bash
# in the API container
python -c "from app import create_app; a=create_app(); \
from core.extensions import limiter; print(type(limiter.limiter.storage).__name__)"
# expect RedisStorage, not MemoryStorage
```

In-memory fallback is enabled, so an unreachable Redis degrades the limiter
rather than taking the API down — but it also silently restores the old
per-worker behaviour, which is why the check is worth doing once after deploy.

**This changes live behaviour.** Brute-force protection on login tightens from
~9 attempts to 5 (measured, see `reviews/2026-08-09-stabilization-audit.md`).
That is the documented intent in `security-guardrails.md`; it is listed here
because it is a real change to what a user experiences, not because it is
in doubt.

## 3. The seed command changed

`startup.sh` and the infra `make seed` now run **`scripts.seed_rbac` only**. Six
scripts were deleted — `backfill_academic_calendar_permissions`,
`backfill_admin_finance_permissions`, `backfill_teacher_leave_permissions`,
`backfill_timetable_subject_permissions`, `grant_hostel_permissions`,
`seed_holiday_permissions`. Any runbook, cron entry or deploy job that names one
of them will fail on a missing module.

`seed_rbac` now seeds every active tenant's roles, which is what it always
claimed to do and never did — its role phase resolved the tenant off the request
and failed on every CLI run. Expect it to report grants added on first run
against a database that has been drifting.

To take a grant *away*, or to see what would change first:

```bash
python -m scripts.reseed_rbac --dry-run     # report, change nothing
python -m scripts.reseed_rbac --reconcile   # revoke what the catalogue no longer grants
```

`--reconcile` is deliberately not part of the deploy. It removes every grant on
a default role that `modules/rbac/catalog.py` does not name, including one an
operator added by hand.

## 4. What to check after the first deploy

- A **sub-admin with the Classes module** can open Classes and see the campus,
  programme and grade filters populated. If they are empty, `105` did not run.
- The **Teacher role** no longer holds `school_setup.read`, and a teacher can
  still open a mediums or subject-context list (those reads now accept
  `class_subject.read`).
- **Login refuses the sixth attempt in a minute**, not the tenth.
- `GET /api/subscription/state` does not intermittently 500. That was the
  in-memory limiter's expiry thread and should be gone with §2.

## 5. Not a deploy step, but it will surprise someone

`scripts/seed_multi_campus_fixture.py` exists for local testing of branch scope
— a second campus and a restricted sub-admin. It is **not** for production and
takes `--remove`. It is in `scripts/` because the demo tenant had one campus and
no restricted user, so branch scope was covered by tests and by nothing anyone
could click.
