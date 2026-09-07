# Mobile PIN Authentication

A student signs in with their mobile number and a six-digit PIN.

> Not to be confused with **mobile OTP** (`mobile-otp-authentication.md`),
> which is found by the same identifier and proved by a code sent to it. A PIN
> is a stored credential; an OTP is a factor destroyed in flight. A school may
> enable either, both, or neither.

---

# The method

```
identifier   mobile number, canonical E.164
credential   a six-digit PIN, stored hashed
subject      students only
tenant       required, always
default      OFF for every school, existing and new
cost         nothing — no SMS, no provider, no usage record
```

Registered in the same strategy registry as the other three, so the pipeline
runs every gate it already owns. The strategy answers two questions — *which
account* and *is this the PIN* — and nothing else.

---

# PIN vs password

They are **different credentials on the same account**, not two views of one.
`account_credentials` has allowed `('password', 'pin')` since it was created,
with a unique index on `(account_id, credential_type)` for live rows, so a
student may hold both and neither is the other.

What follows from that, without any code to enforce it:

| | Password | PIN |
|---|---|---|
| Row | `credential_type='password'` | `credential_type='pin'` |
| Synced from `users.password_hash` | yes, by `person_link` | **no** — the hook filters on `password` |
| `must_change` | its own column, mirrored from `users.force_password_reset` | its own column, independent |
| Reset by | password issuance | PIN issuance |

So changing a password does not touch the PIN, resetting a PIN does not touch
the password, and requiring one to be changed says nothing about the other.
Each of those is a test.

**A PIN login reports itself as `mobile_pin`.** It never appears as
`email_password` or `mobile_otp` in a session, a token or an audit record.

---

# What a PIN may be

```
length            exactly 6 digits
characters        digits only
leading zeros     preserved — 000123 is six digits
parsed as         a string, never an integer
```

The last one matters more than it looks. `000123` parsed as an integer becomes
`123` — a different, shorter secret, and one whose hash would then match
anybody who chose `123`. Nothing in the module converts a PIN to `int`, and a
test asserts the two do not verify against each other.

## Trivial PINs are refused

Against a limited number of online guesses, an attacker spends them on the
handful of values people actually pick. Rejecting those is worth more than any
amount of hashing.

The refused set is **derived, not collected** — roughly 1,150 values, every one
of which is:

- all one digit (`000000`, `111111`)
- an ascending or descending run (`123456`, `654321`)
- a repeated short block (`123123`, `121212`)
- a doubled run (`112233`, `445566`, `332211`)

A thousand-entry list copied from a breach corpus would refuse PINs nobody
here would pick and would still miss the next one. These are the patterns a
person reaches for when asked to invent six digits on the spot.

**What is deliberately not refused:** a PIN is not rejected for resembling an
admission number or a date of birth. Checking that would mean reading the
child's record every time a PIN is set, and it would leak — an attacker who
can see which PINs are refused for one student learns something about that
student. The defence against a guessable PIN is that the school issues a
random one.

The trivial set is **not published** by the API. An attacker who knows which
PINs are refused knows which to skip, and the list is small enough for that to
matter.

---

# Generation and storage

`secrets.randbelow(10 ** 6)`, zero-padded — uniform by construction, no modulo
bias, and not `random`, whose next output can be predicted from its previous
ones. The same device the OTP uses. Re-drawn if it lands on a trivial value.

Nothing about the child is mixed in: not the admission number, the date of
birth, the phone number, the name or the year. That is invariant **A5**, and a
PIN derived from any of them is a PIN their classmates can guess.

**Hashed with the same helper passwords use.** A PIN is shorter, not less
valuable, and a weaker hash chosen because the input is short is how a
database leak becomes a million recovered PINs. The plaintext is returned by
the operation that generated it and exists nowhere else — no column, no cache,
no log, and no read path in the product can produce one.

---

# The attempt limit is the security

Six digits is a million values. An offline attacker exhausts that in seconds;
an online one never reaches it, **provided the online path counts**. So the
limit is not a hardening measure here — it is the security of the method, and
it fails closed.

| Dimension | Limit | Closes |
|---|---|---|
| per (tenant, mobile) | 10/hour, 25/day | grinding one number |
| per IP | 30/hour | one attacker across many numbers |
| per tenant | 500/hour | a rotating-IP swarm on a whole school |

Ten guesses an hour against one number is 87,600 a year: about a 9% chance
after a year of uninterrupted attack on one child, with the other two ceilings
preventing that from being run against a school in parallel.

**Only failures are counted**, and a correct PIN clears the count against that
number — but **not** the per-IP or per-tenant counters, because one correct
PIN somewhere in a school says nothing about the thousands of wrong ones an
attacker is making elsewhere, and clearing them would be a reset button.

**A number with no PIN is counted too.** Otherwise the allowance itself is an
oracle: unlimited guesses at numbers without a PIN and limited ones at numbers
with one is an answer to "does this student use PIN sign-in".

This is not a second throttle architecture. The Redis primitive, the keyed
hashing and the fail-closed policy come from the OTP throttle built in Phase
4; what is added is the PIN-shaped policy. The existing account lockout is
deliberately not relied on — it is keyed on an account row, and an
enumeration-resistant login must count guesses at numbers that resolve to no
account at all.

---

# Students only

The product asked for a PIN for children signing in on a phone, not a second
password for staff. **Two independent things enforce it**, because one of them
being wrong should not be enough:

1. **Policy.** A school enables `mobile_pin` for the `student` subject kind.
   An account with no studentship is denied by the policy gate.
2. **The strategy.** It will not resolve an account whose person is not a
   student of the school.

Subject kind is asked of the identity layer, not recomputed — and it tests
**membership, not equality**, because a person may legitimately be both a
student and staff. Such a person is still a student, and can still sign in.

---

# The mobile identifier

`mobile_pin` depends on an explicitly issued `account_identifiers` row of type
`mobile`, recorded by an operator through
`POST /api/students/<id>/mobile {"mobile": "…"}`. Phase 4's rule stands in full: **`Person.phone_number` is never
promoted.** It is clerk-typed, unverified, rewritten by spreadsheet imports,
shared across households by design, and full of repeated placeholders in
migrated data.

One change was needed. `issue_mobile_identifier` originally asked whether OTP
was enabled — right while OTP was the only thing a mobile number was for, and
wrong the moment a second method used the same identifier. It now asks whether
**either** mobile method is enabled, so a school that gives its students PINs
but not codes can issue the numbers those PINs sign in with.

## Shared numbers — debt 58, untouched

A partial unique index still forbids two accounts at one school holding the
same mobile number, and Phase 5 **did not change it**. Whether a household
should share a sign-in identifier is a product decision that belongs with
parent accounts, and taking it here would have constrained that design.

So today: one student account per mobile number per school. Resolution still
returns every match and signs in nobody when there is more than one.

---

# Issuing, resetting, changing

Through the existing credential administration service — not a parallel
`pin_admin`. The same lifecycle the password has:

| Operation | Effect |
|---|---|
| issue | a random PIN; skipped if one exists |
| issue with `reset` | replaces it, ends the sessions using it |
| force change | sets `must_change` **on the PIN row only**; enforced from 2026-09-07 — see below |
| bulk issue | a class at a time, `reset` off by default |
| status | issued or not, provisional, must-change, dates — never digits |

A reset **rotates one row** rather than creating a second: the unique index
would refuse a duplicate anyway, and doing it deliberately means a reset is an
update rather than an `IntegrityError` somebody has to interpret.

**A provisional PIN is enforced (2026-09-07).** Until Phase 8 the flag was
written and read nowhere: a school that clicked "Ask for a new PIN" got a
stored boolean and the child carried on using the PIN the school had handed
out. `pin_change_is_outstanding` (`core/authentication.py`) now refuses every
route except the change flow, the profile and logout — otherwise the person is
stuck — and it fires **only when the session's `login_method` is
`mobile_pin`**. The requirement is about the credential in use, not about the
person: a pupil signing in with their password is not stopped by a PIN they
have not touched.

**A reset now takes effect immediately.** Access tokens used to live out their
remaining minutes after a PIN reset, exactly as they did after a password
reset. Since Phase 8 an access token names its session, so revoking the
session stops the token already on the phone on its next request.

A holder changes their own PIN at `POST /api/auth/pin/change`, which requires
the current one — being signed in is not by itself permission to change a
second credential.

**Bulk student import does not issue PINs or mobile identifiers**, and was not
changed. Importing a spreadsheet gives a student a password and an admission
identifier, as it always has; a PIN is issued deliberately, for students whose
number a school has confirmed.

---

# What it costs

Nothing. A PIN sign-in sends no message, calls no provider, and creates no
`ServiceUsageRecord` — asserted by a test that fails if the SMS capability is
so much as invoked, and by a structural test that the PIN modules import
neither `integrations` nor `billing`.

A PIN is an internal credential, not a third-party service. If a future phase
lets somebody reset a forgotten PIN by SMS, that is a separate operation with
its own cost, and must not be conflated with signing in.

---

# Enumeration resistance

A wrong PIN, a number nobody holds, a number that is not a student's, a
suspended account and a throttled number all produce one `InvalidCredentials`.
The throttle refusal is reported as a failed sign-in rather than as a distinct
error — a response that said "you are being throttled" for a number under
attack and "wrong PIN" otherwise would tell an attacker which numbers are
worth attacking.

---

# Session and token

```
login_method               mobile_pin
authenticated_identifier_id  the mobile identifier row
amr                        mobile_pin
tid                        the school
```

Through the existing `_finalize_login`, which was not modified.
