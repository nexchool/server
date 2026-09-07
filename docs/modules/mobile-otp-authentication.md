# Mobile OTP Authentication

Signing in with a code sent to a phone.

The first authentication method with **no stored secret**, and the first where
an attempt **costs money**. Almost every decision below follows from one of
those two facts.

---

# The method

```
identifier   mobile number, canonical E.164
proof        a six-digit code, sent by SMS, valid for five minutes
tenant       required, always
default      OFF for every school, existing and new
```

Registered in the same strategy registry as email and admission-number
sign-in, so the pipeline runs every gate it already owns — maintenance,
policy, lockout, account status, disambiguation, events, finalization — for a
code exactly as it does for a password. A new method is a class and a registry
row, never a second branch past a second copy of the gates.

Because it stores nothing to check against, the strategy declares
`credential_type = None` and offers `issue_challenge`, a shape the registry has
required since the pipeline was built: it refuses to start a strategy that
"proves nothing: it declares no credential type and offers no challenge."

---

# The mobile identifier

A mobile number is an **authentication identifier**, not a profile field.

`Person.phone_number` looks like the same thing and is not. It is typed by a
clerk during admission, never verified, freely rewritten by spreadsheet
imports, and — by design — shared: a father and a mother are two people
carrying one household number, and the person-matching layer exists precisely
because that is normal. Migrated school data is also full of one placeholder
number repeated across a fifth of the households.

So **nothing is ever promoted automatically**. An operator records the number
they confirmed, through `POST /api/students/<id>/mobile`.
`issue_mobile_identifier` is an
explicit, audited, idempotent operation an operator performs for one account
with a number they confirmed. `Person.phone_number` is a suggestion to show
them, never a source of truth.

An issued identifier starts **unverified** — unlike an admission number, which
a school knows because it assigned it. A school only believes the phone number
it was told. Possession is proved the first time a code sent to it is used,
and that is when `is_verified` becomes true.

## Normalization

Canonical form is **E.164**: `+919876543210`.

| Typed | Stored as |
|---|---|
| `9876543210` | `+919876543210` |
| `+91 98765 43210` | `+919876543210` |
| `098765-43210` | `+919876543210` |
| `+971 50 123 4567` | `+971501234567` |
| `n/a`, `12345`, `""` | *refused — no identifier is created* |

E.164 rather than "the digits", because a key that is only digits has to
answer what `09876543210` and `919876543210` mean, and every answer is a
guess. E.164 is the one representation where a number has exactly one
spelling, so a person cannot become two accounts by typing their own number
differently and two people cannot become one because their numbers end alike.

Parsing and validation use the `phonenumbers` library rather than a regex —
it knows which prefixes a country actually assigns, so a ten-digit number that
is the right length and no real subscriber is refused.

**Default region is `IN`**, a named constant. There is no country column on a
tenant to read one from, and every school on the platform today is in India —
the same statement the codebase already makes about the default timezone. It
is a *default*, not a restriction: a number that arrives in international form
keeps its own country. When a tenant has a country of its own, that constant
is the one place to read it from instead.

This is deliberately **not** `people/matching.normalize_phone`, which keeps the
last ten digits. That rule is right for finding probable duplicate people —
it is meant to be generous — and would be wrong here, where it would collapse
a foreign number onto an Indian one sharing its final ten digits. A fuzzy
match is a suggestion; an authentication identifier is a decision.

## Shared numbers — the open question

A partial unique index makes two live mobile identifiers with the same value
**impossible within one school**. Across schools they are fine: a household
number at two schools is two people's, and neither school learns about the
other.

Within a school, issuing a number somebody already has raises
`MobileAlreadyInUse` rather than quietly doing nothing — two people sharing a
phone is a real situation somebody has to decide about, and an operation that
silently succeeded without issuing anything would hide it.

**The resolution path handles the plural case anyway**, and refuses it: a
number that resolves to more than one account signs in nobody. Never
`.first()`. That code is unreachable today and is there so that relaxing the
index for households later cannot turn resolution into an arbitrary choice by
omission.

Whether households *should* share a login identifier is a product decision
this phase deliberately did not take — see the debt register.

---

# The code

Six digits, from `secrets.randbelow(10 ** 6)`: uniform by construction, with
no modulo bias and no predictable source. Not the clock, not an account id,
not a hash of anything, and not `random`, whose next output can be predicted
from its previous ones.

Six digits is a million combinations — far too few to survive unlimited
guessing and far more than enough to survive five. The brute-force defence is
the attempt limit, not the length.

## What is stored

**Never the code.** A per-challenge salted hash. So a database dump, a support
engineer, a log file and a backup all contain nothing that can sign anybody in.

The **number** is stored hashed too, which is a departure from the rest of the
auth schema worth stating. `account_identifiers` keeps a number in clear
because a school's office has to recognise it. A challenge row has no operator
reading it — it lives for five minutes and is only ever matched against a
number somebody just typed — so keeping it in clear would be storing personal
data for no purpose it serves.

The digest is **keyed with the application secret**, not the bare sha256 the
event table uses for email addresses. An Indian mobile has roughly ten billion
candidates; an unsalted digest of one is reversible by anybody who cares to
try.

## Lifecycle

```
created ─→ sent ─────→ consumed        the whole of a successful sign-in
   │         │
   │         ├───────→ superseded      a newer code was issued
   │         │
   └───────→ failed                    the provider refused it
```

Expiry and the attempt limit are **conditions, not states** — a challenge does
not need a background job to write `expired` on it to stop working.

There is no `delivered`. A provider accepting a message is not a handset
receiving one, and a status claiming otherwise would be a lie the system could
never check.

| Rule | Value |
|---|---|
| Lifetime | 5 minutes |
| Wrong guesses per code | 5 |
| Resend cooldown | 60 seconds |
| Codes per number | 5/hour, 10/day |
| Codes per address | 20/hour |
| Codes per school | 200/hour |

Every one of those is a single constant. A resend does **not** extend a code's
life; it issues a new one and the old one stops working the instant the new
one exists, so somebody holding two messages cannot use the first.

## Spending it, once

Verification is a single conditional UPDATE that consumes the challenge in the
same statement that checks it — unconsumed, unexpired, under the attempt
limit, right hash, all in the WHERE clause. Two requests arriving together
with the same correct code produce exactly one winner: whichever the database
serializes first, the other matches zero rows.

A Python-level "if not consumed: consume" would let both through, and under a
real race it would. Attempt counting is a database increment for the same
reason — an in-memory counter loses count under exactly the concurrency it
exists for.

Comparison is constant-time, so the number of matching leading digits cannot
be measured from how long the answer took.

---

# Rate limiting

OTP is the first method where an attempt spends a school's money and rings a
real person's phone, and that changes what a limit is for. The limits defend
three different things at once: a **victim** from having their phone rung all
night, a **school** from a bill somebody else ran up, and an **account** from
being guessed at.

None of the existing machinery could do this. `flask_limiter` is keyed on the
IP address alone — no defence against an attacker with a list of addresses
attacking one number. The database lockout is keyed on an account row, so it
cannot throttle requests for a number that resolves to no account. So this is
a new primitive, on the Redis client the cache layer already exposes for
one-time tokens.

**It fails closed.** The repository is split on this — the JSON cache fails
open because a missing entry is only slow; the sign-in handoff fails closed
because a code that cannot be tracked must not be issued. A rate limit that
stops working when Redis does is not a rate limit, and what it stops
protecting is somebody's phone bill.

Counters are bumped **after** a provider accepts a message, not before: a send
the provider refused cost nothing and rang nobody, so counting it would let a
broken integration lock a school out of its own sign-in.

---

# Enumeration resistance

Asking for a code answers **the same way whatever happens**: a number that
belongs to nobody, a school that has not enabled the method, a suspended
account, a number shared by two people, and a code that was genuinely sent all
produce one response. Anything else would answer, for free, the question an
attacker is asking — *is this number a NexSchool customer?*

The precise reason is recorded internally, so an operator investigating can
tell those cases apart. The caller cannot.

The one exception is being throttled, which is told plainly — the caller
already knows, because they are the one who sent the requests, and a client
that does not know it is rate limited simply retries.

Verification failures are equally uniform: a wrong code, an expired code and a
spent code are one `InvalidCredentials`.

---

# Tenant scoping

A number alone means nothing. It is looked up **inside the school that was
named**, never across schools, and an unnamed school is an error.

The request endpoint checks that a school was *named* rather than merely
resolvable. The ordinary login path falls back to the tenant with subdomain
`default` when nothing names one — a documented behaviour it deliberately
keeps — and here that fallback would be a hole: a request with no school would
send a code to whoever holds that number at the default school.

---

# The provider boundary

```
OTP service
    ↓  send_sms(tenant_id, destination, message, purpose="authentication_otp")
integrations/sms
    ↓
the school's provider          ← chosen there, never here
    ↓
normalized SmsSendResult
    ↓
ServiceUsageRecord             ← what happened
    ↓
billing                        ← what it costs, separately
```

No vendor name, no HTTP call, no retry policy and no price appears anywhere in
the authentication module — asserted by a test that parses every import under
`modules/auth/`.

Message text lives in its own file so that changing the wording — for a
template a provider must pre-register, for a second language — is not a change
to authentication logic.

**A timeout is never retried.** It may mean the provider accepted the message;
a retry would send a second one and charge the school twice. The send carries
an idempotency key so that a provider which honours one can be asked again
safely, and the decision to do so belongs to the provider that knows whether
it does.

Only a provider-accepted send reaches the usage ledger. A refused send creates
no usage, and no verification attempt ever does — checking a code sends
nothing.

---

# Tenant policy

`mobile_otp` goes through the same policy service as every other method, with
no OTP-specific flag and no OTP-specific table. It is **off for every school**,
existing and new: a tenant with no policy row gets email and password, and a
tenant with one gets whatever was enabled, which does not include this.

**Deploying this phase gives nobody a new way in.**

Enabling it now has a write endpoint, added because this is the first method a
school would plausibly want switched on and off and there was no way to do it
but a Python shell. Enabling a method that cannot work is **refused**: OTP
needs an SMS provider, and a school switched on without one would present a
sign-in option whose codes silently never arrive.

Since no real SMS vendor is registered in this build, that refusal is what
every attempt to enable it in production currently gets — correctly.

---

# Forced password change

An OTP proves possession of a phone. It does **not** set a password, so it
cannot discharge a requirement to change one.

A sign-in by code therefore leaves `force_password_reset` exactly as it found
it, and reports it in the response the same way a password sign-in does.
Silently clearing it would let anybody holding the phone skip a security
requirement an operator deliberately imposed. Pinned by a test.

Nothing else about forced password change was redesigned.

---

# Logging

Logged: tenant, provider, capability, operation id, normalized error code,
latency, and the last two digits of a number with a short digest.

**Never logged:** the code, the message body — for OTP the body *is* the
secret — the full number, or any credential.

---

# Before production SMS can be switched on

> Since Phase 5, a mobile identifier is also what `mobile_pin` signs in with —
> so `issue_mobile_identifier` asks whether *either* mobile method is enabled
> rather than only this one. See `mobile-pin-authentication.md`.

**No real SMS provider exists in this build**, and none was added. What a
future phase has to settle before a school can actually receive a code:

- **Choose a vendor** and register a provider client (Phase 3's integration
  layer is where it goes; nothing in authentication changes).
- **India's DLT regime.** A commercial SMS in India requires the sender to be
  registered on a telecom operator's DLT platform, with a registered header
  (sender id) and a pre-approved template. The message this phase sends is the
  text that would be registered; a template mismatch is rejected by the
  operator, not by us.
- **Sender id** provisioning, which is per-organisation and takes days.
- **Per-tenant credentials**, if schools bring their own vendor accounts —
  today a credential is NexSchool's own, named by an environment variable.
- **Delivery receipts**, if `delivered` is ever to mean anything: that needs an
  inbound webhook, which does not exist.

None of these are assumptions in the code. The architecture is vendor-neutral
and nothing above changes when a vendor is chosen.
