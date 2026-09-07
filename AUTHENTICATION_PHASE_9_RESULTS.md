# Authentication — Phase 9: Operations & Messaging Integration

**Verdict: PASS, with two defects found by using the application that no test
could see, both fixed, and one product question left open.**

An operator can now switch a school's sign-in methods on and off, point a
school at a messaging vendor, and read the code a test provider "sent" —
which is what makes `mobile_otp` testable without a vendor account at all.
All three methods that had never been exercised now sign a student in.

Everything below was established against the running stack, not by reading
code. Where the walkthrough disagreed with what the tests said, the
walkthrough won and the disagreement is written down.

---

## 1. What was missing, and what it is now

| | Before | Now |
|---|---|---|
| Switching a method on | A Python shell. The panel card was read-only and said so | Toggles per subject kind, refusing what cannot work |
| Which methods the panel knows | Whatever rules a school already had — and the seeder writes only `email_password`, so the three interesting methods were invisible | `GET /platform/auth-methods`, read from the strategy registry |
| A method that cannot serve a person | `mobile_pin` offered for staff, silently never working | Declared `subject_kinds`, refused at `set_method`, hidden in the UI |
| Choosing a channel | SMS, hardcoded | `tenant_auth_policies.otp_delivery_channel`, one channel, no fallback (ADR-021) |
| Providers | One test double | `fake_sms`, `fake_whatsapp`, `msg91`, `meta_whatsapp` |
| Reading a test OTP | Impossible — the fake discarded the body | An outbox, dev-gated, 404 in production |
| Testing a provider | Nothing | An explicit, billable, rate-limited test send, kept separate from health |
| Turning an integration off | Allowed, leaving a school showing an OTP button whose codes never arrive | Refused, naming the method that depends on it |
| Whether the platform can offer WhatsApp | Unanswerable without opening a school | A catalog page reporting which credentials are set on this server |

---

## 2. Two defects the tests could not see

### D1 — the OTP challenge was never committed

`POST /api/auth/otp/request` created a challenge, sent the code, returned
`{"sent": true, "challenge_id": …}` — and never committed. Measured against
the running stack:

```
challenges BEFORE: 0
response: sent=True, challenge_id present
challenges AFTER:  0
```

The message went out and there was nothing to verify it against. **Mobile OTP
could not succeed for anyone.** The login refused with `401 InvalidCredentials`,
which reads as a wrong code and was in fact a missing challenge.

This predates Phase 9 — `git diff fdb12c8 HEAD -- modules/auth/routes.py` was
empty when it was found. The suite missed it because no test asserted that a
challenge **survives the request that created it**; they inspect the same
session the request used.

### D2 — every failed login's audit row was discarded

Found by the audit D1 prompted. `_login_through_pipeline` committed on no
non-success path, so `auth_events` rows for a wrong password, a lockout, a
policy denial or an unresolved tenant were all rolled back. Only successful
logins persisted a row, via `_finalize_login`'s incidental commit.

This made a stated Phase 8 property inert: that phase deliberately returns an
identical `401` for a policy denial, a lockout and a wrong password, on the
argument that "the precise reason still reaches the `auth_events` row, so an
operator investigating can tell the cases apart." The rows were not reaching
it. `.claude/rules/security-guardrails.md` requires authorization failures to
be logged; they were not.

Both are fixed, both have regression tests that fail without the fix, and the
underlying trap — a service layer that flushes while the route owns the commit,
with nothing enforcing that a commit dominates every early return — is recorded
as debt.

### D3 — the outbox did not work under gunicorn

The outbox began as a process-local `deque`. The API runs several gunicorn
workers, so a send landed in one and a read hit another: **2 of 12 reads
returned the message, 10 returned nothing.** A developer would conclude the OTP
had silently failed. Every test passed, because the Flask test client is one
process. Now backed by Redis — already a dependency, bounded, TTL'd, dev-gated,
and only ever holding a fake provider's messages. After the fix, 12 of 12.

---

## 3. The walkthrough

**As the platform operator.** Every refusal returns its own specific sentence,
and the panel now shows that sentence rather than the generic "Validation
failed" it displayed before this phase fixed the client's error parsing:

| Attempt | Result |
|---|---|
| Enable `mobile_otp` with no provider | Refused — "this school has no working sms provider" |
| Enable `mobile_pin` for staff | Refused — "'mobile_pin' does not serve 'staff' accounts" |
| Enable `msg91` with no credentials | Refused — "the credentials this provider needs are not set on this server" |
| Configure `fake_sms` | Created **disabled**, as designed |
| Enable it, then enable `mobile_otp` | Allowed |

**As a student.** All three previously untested methods sign in:

| Method | Result |
|---|---|
| Mobile + OTP, code read from the outbox | Signed in, access and refresh tokens issued |
| Admission number + password | Signed in |
| Mobile + PIN | Signed in |

**In the panel.** The catalog page lists both capabilities and all four
providers, labels the test doubles as unable to run outside development, and
reports `MSG91_AUTH_KEY` and `META_WHATSAPP_ACCESS_TOKEN` as *not set* — which
is the honest answer to "can we offer WhatsApp yet?". On the tenant page,
Students show four methods and Staff and Parents show three, because
`mobile_pin` declares itself students-only. The test-send control says it sends
a real, billable message that will ring a phone, and is not called a connection
check.

---

## 4. The open question

**A test send needs its own registered template, and an operator has no way to
know that.** The test send uses purpose `integration_test`, so a school that
has registered only its OTP template gets:

> This school has no template registered for 'integration_test'.

For a real vendor this is arguably correct — DLT will not carry unregistered
text, so a test message genuinely needs its own approved template. But it means
"Send test message" fails for every newly configured school, and registering a
DLT template purely to test is real friction.

The alternative is to send the school's **OTP** template with placeholder
values, which tests the template that actually has to work — a stronger test,
since a missing OTP template is the failure that matters. Not decided here.

---

## 5. Deliberately not done

- **No automatic channel fallback.** ADR-021 argues it doubles the failure
  modes and makes a bill hard to explain, for a reliability problem nobody has
  measured.
- **No per-school vendor credentials.** The platform owns the accounts; a
  per-tenant secret would be the first secret in this database.
- **Meta's authentication-template button component is not constructed.** Those
  templates require one, and a body-only send will fail loudly rather than
  silently. Guessing the shape without an approved template to check against
  would have baked a wrong interface in.
- **WhatsApp for anything but OTP**, and notification-template management.

---

## 6. Before this can send a real message

The code is not the critical path; the paperwork is. See
`docs/operations/otp-vendor-registration.md`. In outline: DLT entity
registration, a sender header and an approved template for SMS; Meta business
verification, a WhatsApp Business Account and an approved authentication
template for WhatsApp; then the two environment variables. **And the billing
catalog** — debt 61 — because nothing seeds it, so today a message sends and
records no usage at all.
