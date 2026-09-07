# Authentication — Phase 8: Production Hardening & Lifecycle Completion

**Verdict: PASS.**

The four P1 findings from Phase 7 are closed, and so are four more that
closing them exposed. The refresh token is now an opaque, hashed, single-use
credential that rotates and detects its own replay; a revoked session stops the
access token already in somebody's hand on its next request; suspension is a
real operation with a screen; a provisional PIN is enforced, not merely
recorded; and all three client applications renew a session exactly once, no
matter how many requests notice at the same moment.

Everything below was established by running code, not by reading it. Where the
repository disagreed with an earlier report, the repository won and the
disagreement is written down.

---

## 1. What was wrong, and what it is now

| | Before | Now |
|---|---|---|
| Refresh token | A JWT stored in clear in `sessions.refresh_token`, reusable until expiry, with a uniqueness bug that let two sessions collide | 48 bytes of `secrets.token_urlsafe`, stored only as a SHA-256 digest under a unique index, spent once, replaced on every use |
| Replaying one | Worked, indefinitely | Ends the session and every generation of its token family, and is recorded |
| Revoking a session | Took effect at the next refresh — up to fifteen minutes of continued access | Takes effect on the next request |
| Suspending an account | Not an operation | `POST …/suspend`, with sessions revoked, tokens retired, an audit row naming the actor, and a screen |
| A provisional PIN | A boolean nobody read | Blocks every route but the change flow, for PIN sessions only |
| A wrong PIN | Spent the account's shared lockout budget, so knowing a mobile number locked the owner out of their password | Bounded by the PIN's own limiter, keyed on the number |
| Policy denial, pre-auth | `403 MethodNotAllowed` — an account-existence oracle needing no password | `401 InvalidCredentials`, identical to an unknown identifier |
| Production JWT secret | Defaulted to `your_default_secret_key` | Refuses to boot without a real, distinct one |
| Logging out | Depended on a refresh token being attached to the request | The access token names its own session |
| Client renewal | The refresh token rode along on every request | One shared renewal per app, one retry, then sign out |

---

## 2. Phase 7's findings

### F1 — the marksheet permission (closed in Phase 7)

Fixed and regression-tested during the audit itself, as that phase's rules
allowed for a production-blocking defect. Nothing further here.

### F2 — a pre-authentication account-enumeration oracle

**The defect.** The policy gate and the lockout gate each answered with their
own status and message, and both run *before* any credential is checked. An
unauthenticated caller could therefore ask "does this admission number exist
at this school?" and read the answer off the status code, with no password at
all. The lockout gate was worse than the policy gate: its distinct `429` said
not merely that an account exists but that it is *currently under attack*,
which is a live signal about which accounts are worth attacking.

**The fix.** Both gates now refuse with `401 InvalidCredentials` and the same
message as a wrong password. The precise reason — `policy_denied`,
`account_locked` — still reaches the `auth_events` row, so an operator
investigating can tell the cases apart and the caller cannot.
`server/modules/auth/pipeline.py`.

**Proved by** `tests/auth/test_phase7_findings_closed.py::test_F2_*` — a real
account and a fabricated one compared byte for byte, a locked account compared
against an unknown one, and the recorded reason asserted separately so the
uniformity outward does not cost auditability inward.

### F3 — a PIN attacker could lock a student out of every other method

**The defect, and a second one underneath it.** The reported half was that the
PIN throttle's refusal reached `_count_failures`, so exhausting the throttle
also locked the account. Fixing that exposed the real shape of the problem:
the ten wrong PINs *before* the throttle trips were each counted too, and the
account lockout is five. So anyone who knew a student's mobile number could
lock that student out of their password with five guesses they were never
entitled to make.

**The fix.** A strategy now declares `counts_toward_account_lockout`, and both
mobile methods set it `False`. The reasoning is written on the base class: the
account lock is one counter shared by every way into an account, and a method
whose identifier is semi-public — a mobile number is on the admission form and
known to every classmate — must not be able to spend it. Those methods are not
thereby unprotected; they are protected by a limiter keyed on the number,
which also covers numbers that resolve to no account, something an
account-keyed counter cannot do. A lock earned elsewhere still applies to
them: this governs only what *earns* one. A new `ThrottledOut` exception
carries the throttle's refusal without it being read as a wrong PIN.

`server/modules/auth/strategies/base.py`, `mobile_pin.py`, `mobile_otp.py`,
`pipeline.py`.

**Proved by** `test_F3_spamming_a_pin_does_not_lock_the_email_password` — which
failed against the first fix and passes against this one — and
`test_F3_the_pin_itself_is_still_thoroughly_throttled`, so the fix cannot
degenerate into removing the limit.

### F4 — the production JWT secret

**The defect.** `JWT_SECRET_KEY` fell back to the string
`your_default_secret_key`, which is in the repository. Anyone with the source
could mint a valid token for any account in any tenant.

**The fix.** `ProductionConfig.init_app` refuses to start when the variable is
missing, when it is the published default, or when it equals `SECRET_KEY` —
one secret doing two jobs means a session-cookie leak is also a token-forging
key. Development is untouched. `server/config/settings.py`.

**Proved by** four tests including the passing case, so the guard cannot be
satisfied by refusing everything.

### F5 — `must_change` on a PIN meant nothing

**The defect.** Phase 5 wrote the flag and Phase 5 read it nowhere. A school
that clicked "Ask for a new PIN" got a stored boolean and no behaviour: the
child carried on using the PIN the school had handed out.

**The fix.** `pin_change_is_outstanding` in `core/authentication.py`, mirroring
the password gate that was already there. It blocks every route except the
change flow, the profile and logout — otherwise the person is stuck — and it
fires **only when the session's `login_method` is `mobile_pin`**. The
requirement is about the credential in use, not about the person: a pupil
signing in with their password should not be stopped by a PIN they have not
touched.

**Proved by** the end-to-end walk in `test_F5_a_provisional_pin_cannot_reach_the_application`
(sign in, blocked, change, unblocked, flag cleared) and by
`test_F5_a_password_session_is_not_stopped_by_a_provisional_pin`.

### F6 — credential issuance was unbounded per actor

**The defect.** A compromised administrator session could harvest fresh
plaintext for an entire school at the global 200-per-minute default. There was
no per-actor ceiling.

**The fix.** `actor_rate_key` in `core/extensions.py` keys the limit on the
acting user rather than the address — a school behind one NAT would otherwise
share a limit, while an attacker with a proxy pool would evade one. Applied to
eight credential, PIN and identifier routes and to parent provisioning: 30 a
minute for single operations, 6 for bulk.

**Proved by** `test_F6_bulk_issuance_is_bounded_per_actor`, which needed a new
`throttling` fixture — see §7.

### F7 and F8 (from the same audit)

Refresh-token weaknesses and immediate revocation. Both are the substance of
§3 and §4 below.

---

## 3. The refresh token

### What it is

`server/modules/auth/refresh_models.py`. 48 bytes from `secrets.token_urlsafe`,
opaque — it is not a JWT and carries no claims — and stored only as a SHA-256
digest under a unique index. The row records its generation, when it was
consumed, and which token replaced it, so a family is walkable in either
direction.

Hashing rather than encrypting is the right shape because nothing ever needs
to read a stored token back: a presented token is hashed and looked up. A
database leak yields digests of 48-byte random values, which is not a
reversible problem.

### Rotation, and what a replay means

`rotate()` in `tokens.py` spends the presented token and issues its successor.
The consuming `UPDATE` carries its conditions in the `WHERE` clause, so two
clients racing on one token produce exactly one winner and the loser is
treated as a replay — which is the correct reading: if two parties hold the
same token, one of them should not.

A replay ends the whole family: the session is revoked and every unspent
generation consumed, and `refresh_token_reuse_detected` is recorded. Which
party is the thief cannot be known from inside a request, so both sign in
again. That is the safe answer and the only one that does not leave a thief
with working access.

**A grace window was considered and rejected.** The usual way to make rotation
survive a chatty client is to forgive a replay within a few seconds and hand
back the same successor. It would have let the old clients keep working
untouched. It was rejected because it hands a thief a valid working token
during exactly the window in which a thief is most likely to act, and reuse
detection is the single control that notices theft at all. The clients were
fixed instead (§6).

### Every refusal is one answer

Unknown, expired, replayed, revoked session, suspended account, suspended
school: all `401`. The reason is recorded, never returned.

### Migration 132 signs everybody out, on purpose

The migration creates `refresh_tokens` and then runs

```sql
UPDATE sessions SET revoked = true, refresh_token = NULL WHERE revoked = false;
```

Existing tokens are the plaintext, colliding ones — precisely the population
the new design exists to replace — and there is no honest way to migrate a
secret into a digest without the secret. Everyone signs in again once. This is
stated in the migration itself, not only here.

---

## 4. Revocation, felt now

Every access token carries a `jti` and a `sid`. `authenticate_request` checks
that the named session is live before it will act on the token, so revoking a
session stops the token already in a browser on its *next request* rather than
at its next renewal.

`session_is_live(None)` returns `True`, so a token minted before this phase is
not summarily rejected — it simply cannot be revoked, and migration 132 has
already ended every session that could hold one.

One ordering defect was found and fixed while building this: `_finalize_login`
minted the access token *before* creating the session, so `sid` was always
absent and the whole mechanism was inert. The two-line reorder is the only
change to that function, and §37 anticipated it.

---

## 5. Suspension, and the other account states

`server/modules/auth/account_status.py`.

`suspend_account` sets the flag, revokes every session, retires every refresh
token, and records the actor and reason. It refuses to touch a platform
administrator (A3) and is idempotent. It changes **access, never the record**:
a suspended pupil is still enrolled, still has their password, still has their
person.

`reactivate_account` restores the ability to sign in **and nothing else**. No
session comes back — the result says `sessions_restored: 0` and the UI says so
in words — because reviving a session would resurrect whatever device held it,
including the one the suspension was about.

### The state matrix (§33)

Every row asserted against a live request in
`tests/auth/test_authentication_state_matrix.py`:

| State | Access token | Refresh | Fresh sign-in |
|---|---|---|---|
| Healthy | works | works | works |
| Locked | **works** | **works** | refused |
| Suspended | refused | refused | refused |
| Reactivated | refused | refused | works |
| Deleted | refused | refused | refused |
| School suspended | — | refused | refused |
| Session revoked | refused | refused | works |
| Maintenance mode | **works** | **works** | refused (503) |

The two surprising rows are deliberate and are argued in the tests. A **lock**
is a brake on guessing, not a revocation: throwing out someone already inside
because a stranger typed their address wrong five times would make the lockout
itself a denial of service. **Maintenance** is an availability control, not a
security one: ending live sessions during a deploy would sign out a whole
school to protect nothing. The refusal that does matter — a suspended school —
is enforced inside `rotate`, so refresh is not a loophole around it.

### A method being switched off (§27)

This had no answer before. Turning a method off stopped the *next* sign-in and
left every current one running for as long as its session lived — the door
shut on the screen and open for everyone already through it.

`end_sessions_opened_with` now runs on the disable path. Only sessions opened
*with* that method end; someone who signed in with their password is
unaffected even if they also hold a PIN, because the decision was about a way
in, not about a person. Each candidate is re-tested with `is_method_allowed`
rather than by re-deriving who the rule covers, so subject kind and surface are
read the one way the pipeline reads them, and a rule that turns out not to
cover an account leaves it alone. Re-enabling brings nothing back, for the same
reason reactivation does not.

---

## 6. The clients

All three renew through a single shared promise. This is not a nicety: a
dashboard fires several requests at once, they 401 together, and without a
single flight each would present the same refresh token — which, now that a
token may be spent once, is indistinguishable from theft. The server would do
the right thing about that, and the user would experience it as being signed
out for opening a busy page.

The refresh token is therefore **no longer attached to ordinary requests** in
any application. It is spent in one place, only when a 401 says it is needed.

| | Renewal | Notes |
|---|---|---|
| `admin-web` | `src/lib/sessionRefresh.ts` | Also wired into GraphQL, which reports an expired token as a 200 carrying `UNAUTHENTICATED` and so never reached the transport's own retry; and into the SSE inbox stream, which previously signed the user out when a long-held stream reconnected after expiry |
| `panel` | `lib/sessionRefresh.ts` → `app/api/auth/renew` | See below |
| `client` (Expo) | `common/services/sessionRefresh.ts` | Plus seven direct PDF/blob downloads moved onto a shared `authHeaders()` and given the same one retry |

Each retries **once**. A second refusal is a real one.

### The panel had no renewal at all

Found while doing this work: the panel stored a 15-minute access token in a
60-hour cookie and held no refresh token anywhere. An operator was signed out
mid-task with nothing able to renew them, and the cookie went on claiming
otherwise for two and a half days.

It now stores both, and they are deliberately different in kind: the access
token stays readable by JavaScript because `lib/api.ts` must put it in a
cross-origin `Authorization` header, while the refresh token is **httpOnly**,
because nothing in the browser needs to read it — renewal happens in a route
handler on the panel's own origin — and it is the long-lived credential.
Logout clears both; leaving the refresh cookie behind would let the next page
load renew its way back into a session the operator had just ended.

### Logout is deterministic

Logout used to depend on the refresh token being attached to the request,
which no client does any more; it would have started returning 400. It now
identifies the session from the access token's `sid` — Authorization header
first, then the panel's cookie, with the refresh header still accepted for
older builds. The same applies to `force-reset` and to "sign out everywhere
else", both of which used the header to decide which session to keep and would
otherwise have silently stranded or over-revoked. `current_session_id()` is
the one owner of that question.

The cookie branch still ends **one** session. Phase 8 was told not to keep the
behaviour where an unauthenticated cookie path could revoke all sessions, and
`test_a_cookie_alone_cannot_sign_somebody_out_of_everything` holds that line.

---

## 7. Screens

**`AccountAccessPanel`** — on a student's Sign-in tab, beneath the credential
panel, behind `user.manage`. Status (active / suspended / temporarily locked,
which is a different thing and says so), what the person may sign in with,
whether a password change is outstanding, the list of signed-in devices with
per-device and sign-out-everywhere actions, and suspend/restore with an
optional reason recorded against the audit row.

**`MySessionsCard`** — on the profile page, no permission required. The person
who first suspects their password is known is usually its owner, and making
them wait for an administrator is the difference between a scare and a breach.

Neither can display a secret. A session is an app, an address and a time;
`list_sessions` has no field that could carry a token and `describe_access`
none that could carry a credential. Asserted, not assumed:
`test_the_access_summary_never_carries_a_secret` and
`test_the_session_list_names_places_and_never_tokens`.

---

## 8. Tests

```
server:     pytest tests/auth/ -q      →  673 passed, 0 failed
            pytest -q                  →  3365 passed, 0 failed
admin-web:  npx vitest run             →  346 passed (43 files)
            npx tsc --noEmit           →  clean
panel:      npx tsc --noEmit           →  clean
client:     npx tsc --noEmit           →  clean
```

Nothing is skipped and nothing is expected-to-fail.

Lint was run in all three. Every remaining error and warning pre-dates this
phase and is in a file it did not touch.

### New files

| File | Covers |
|---|---|
| `tests/auth/test_token_lifecycle.py` (21) | Opacity, hashing, rotation, the §39 replay sequence in full, races, immediate revocation, suspension end to end, cross-tenant isolation |
| `tests/auth/test_phase7_findings_closed.py` (14) | One group per finding, named for it, so a regression names the finding it reopens |
| `tests/auth/test_authentication_state_matrix.py` (15) | The §33 matrix, policy disablement, maintenance, what an administrator is shown |
| `tests/auth/test_logout_and_sessions.py` (11) | Deterministic logout, the cookie limit, sign-out-everywhere-else, forced password change |
| `admin-web/src/lib/sessionRefresh.test.ts` (8) | Both tokens stored, one spend under concurrency, no header leak, every failure mode |

### Twenty-one existing tests were rewritten, none weakened

They were characterization tests pinning the old behaviour, and the old
behaviour is what this phase was asked to change. Each now asserts the fixed
behaviour and is at least as strong:

- Policy and lockout: `403`/`429` → `401`, with the reason read from
  `auth_events` since the statuses are now deliberately uniform.
- Token claims: `jti` and `sid` added to the asserted set.
- Refresh token: asserted **opaque** — `pytest.raises(DecodeError)` — and
  asserted absent from `sessions.refresh_token`.
- Rotation asserted through the response.
- Revoked session: was "still works until refresh", now `401`.
- The collision test was rewritten to assert the collision is now
  *impossible*: the unique index raises `IntegrityError`.
- Actor identity: `user_agent LIKE 'actor:%'` → the `actor_user_id` column.
- PIN throttle: asserted via `pytest.raises(ThrottledOut)`.
- The one outside `tests/auth/` —
  `test_login_lockout_without_tenant.py::test_repeated_tenantless_guesses_lock_the_account`
  — asserted the `429` F2 removed. It now asserts the lock itself and the
  `account_locked` reason on the audit row, which is the property it was
  really guarding, rather than a status an attacker could read.

### One test-infrastructure change

`tests/conftest.py` disabled the limiter for the whole suite, on the stated
grounds that "no test asserts it" — which F6 made false. There is now an
opt-in `throttling` fixture that turns it on for one test and resets the
counter on the way in and out, and the suite points the limiter at
`memory://`, because counting in the deployment's Redis meant inheriting
yesterday's attempts and leaving today's behind.

---

## 9. Migrations

| | Does | Reversible |
|---|---|---|
| 132 | Creates `refresh_tokens`; invalidates every existing session (§3) | Yes |
| 133 | Adds `auth_events.actor_user_id`, migrating the `user_agent LIKE 'actor:%'` rows that encoded it before there was a column | Yes |

Both validated `upgrade → downgrade → upgrade` against a clone of real data.
133 migrates the actors it can read and fabricates none: a row that never
recorded who acted keeps saying so.

---

## 10. Where the repository disagreed with earlier reports

- Phase 6 and Phase 7 reports both said forced password change was
  "frontend-only". It is not: `core/authentication.py` has had a server-side
  gate throughout. Reported as a discrepancy rather than quietly reconciled;
  the PIN gate in F5 was built as its mirror.
- Phase 7 reported F3 as "the throttle's refusal is counted as a failure". The
  code showed a larger hole underneath it (§2, F3). Both are closed; the
  report's version alone would not have fixed the attack.

---

## 11. What this phase deliberately did not do

- **No grace window on reuse detection** — argued in §3.
- **Debt 58 (`users.email` NOT NULL`) untouched**, as instructed.
- **No SMS provider selected**; the integration boundary is unchanged.
- **No business logic touched** in examinations, attendance, fees or
  timetable. The only files outside `auth` that changed are the credential
  routes that needed a rate limit, and the client call sites that were sending
  a refresh token they must stop sending.

---

## 12. Before deploying

1. **Set `JWT_SECRET_KEY`** in production, distinct from `SECRET_KEY`. The app
   will now refuse to boot without it — that is the point, but it means the
   deploy fails rather than degrades if it is missed.
2. **Run migrations 132 and 133.** 132 signs everyone out; say so.
3. **Ship all three clients together.** A build that still expects to renew by
   attaching a refresh token to every request will be signed out at its first
   expiry. The Expo repository does not deploy on a `main` push unless the
   commit message carries `[store-release]` or `[ota]`.
