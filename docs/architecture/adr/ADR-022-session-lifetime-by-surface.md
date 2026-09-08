# ADR-022 — A Session's Lifetime Is a Property of Its Surface

## Status

Accepted

---

## Date

2026-09-08

---

# Context

Until now a session lived for one number: `JWT_REFRESH_TOKEN_EXPIRES_DAYS`,
seven days, set once at sign-in and never extended
(`modules/auth/services.py::create_session`). `rotate()` stamped
`last_accessed_at` and left the expiry alone, and
`retention.purge_expired_sessions` deleted the row on schedule.

Two separate things are wrong with that, and they pull in opposite directions.

**It is too short where nothing is bought by being short.** A student who opens
the app every single day was still signed out on day seven, mid-week, with no
warning and no way to see why — because the clock ran from the act of signing in
and nothing they did moved it. A phone is a personal object kept behind the
operating system's own lock; weekly re-authentication on it is friction with
nothing purchased for it.

**It is too long where length is the risk.** A platform operator working in the
panel holds cross-tenant authority: `authenticate_platform_admin` is
deliberately cross-tenant, god-login is the operator's way into any school, and
policy evaluation is skipped for platform admins by invariant A3. That console
was getting exactly the same seven-day window as a Class-6 student's phone, and
a console left open in an office overnight stayed usable.

One number cannot be right for both. The `sessions.client_surface` column
already exists — added in Phase 0d, sent by all three clients as
`X-Client-Surface`, and until now recorded but never read for any decision.

# Decision

**A session carries two limits, and both are read from its surface.**

An **idle limit** slides forward on every successful rotation. It answers "has
this person gone away?" A session in use stays alive; a session nobody touches
dies on its own.

An **absolute cap** is measured from `created_at` and never moves. It answers
"how long may one act of proving who you are keep working?" Every session ends
eventually, however busy, which is what makes a lost phone stop being useful
without anybody having to notice it was lost.

| Surface | Idle | Absolute |
|---|---|---|
| `student-mobile`, `parent-mobile` | 30 days | 90 days |
| `admin-web` | 7 days | 30 days |
| `panel` | **30 minutes** | **12 hours** |
| `public-api`, `unknown` | 7 days | 30 days |

Implemented in `modules/auth/session_policy.py`; applied at
`create_session` (initial expiry) and in `rotate()` (the slide). Every value is
overridable per deployment — `SESSION_PANEL_IDLE_MINUTES` and siblings — so
tightening a window during an incident is configuration, not a release.

Three consequences that are part of the decision, not side effects:

- **A refresh token expires with its session, never after it.**
  `issue_refresh_token` takes `session.refresh_token_expires_at` rather than a
  constant of its own. A token with an independent window could outlive the
  ceiling it was meant to be bounded by, and renewing with it would extend a
  session past the point where its holder must prove who they are again.
- **`unknown` gets the conservative numbers, not the generous ones.** A build
  that predates the header must keep working (NFR-1); it must not be rewarded
  for declaring nothing.
- **The panel's cookies were shortened to match** (`panel/app/api/auth/*`), so a
  browser is not left holding a credential that the API stopped honouring hours
  earlier.

# Alternatives considered

**Keep one number and raise it.** Simplest, and wrong in the direction that
matters: it would give the panel a longer window, which is the surface where
length is precisely the risk.

**Idle limit only, no absolute cap.** Fixes the student's weekly sign-out and
introduces a session that, if used regularly, never ends. A stolen phone in
daily use by the thief would stay signed in indefinitely, and revocation would
depend on somebody noticing and acting. The cap is what makes the system safe
without requiring anyone to notice.

**Absolute cap only, no sliding.** What exists today, with a different number.
It does not fix the complaint: an active session still dies on a fixed clock,
which is the behaviour being removed.

**Let each school configure its own.** A school cannot reason about token
lifetimes, and getting it wrong is invisible until it is exploited. The surface
is the honest axis: it describes the risk, and the platform owns it.

# Consequences

Sessions live longer on phones, so the `sessions` table grows — the nightly
purge still bounds it, and the row count is now driven by the absolute cap
rather than by seven days. Everything Phase 8 established is untouched:
revocation bites on the next request, suspension ends sessions and retires
tokens, reuse detection ends a family, per-session listing and revocation still
work.

The panel change is a **tightening** and will be felt: an operator idle for
thirty minutes signs in again, and no operator session survives a working day.
That is the intended cost. A warning before the idle timeout fires is worth
building and is recorded as future work rather than assumed.

Related: ADR-003 (identity/authentication separation), Phase 8
(`AUTHENTICATION_PHASE_8_RESULTS.md`) for the rotation design this builds on.
