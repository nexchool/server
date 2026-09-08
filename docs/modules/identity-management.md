# Identity Management

## Purpose

The Identity Management module is how people get into Nexchool and how the
application decides which experience to show them once they are in.

It owns sign-in, sessions, credentials and the Active Context. It does not own
who a person is — that belongs to the People Domain — and it does not decide
what they may do — that belongs to the Authorization Domain.

A teacher remains a teacher when they forget their password. A parent remains a
parent when they never install the app. This module exists only to let those
people reach the software.

---

# Business Responsibilities

The Identity Management module is responsible for:

- Account Creation
- Sign In
- Sign Out
- Session Management
- Token Refresh
- Password Change
- Password Reset
- Forced Password Reset
- Active Context Selection
- Context Switching
- Account Suspension and Restoration
- Sign-In Audit

---

# Module Ownership

## Account

The credential a Person uses to reach the platform. A Person may have at most
one Account, and may have none.

---

## Session

One signed-in device. A Person signed in on a phone and a laptop has two
sessions, which expire, refresh and are revoked independently.

A Person may see where they are signed in and end any of those places, and an
operator with authority over accounts may do the same for somebody else in
their own organization — never for another organization, and never for a
platform operator working inside theirs. Ending one session ends only that
one; ending all of them is a deliberate, separate act that is recorded.

**How long a session lasts depends on where it was opened.** Using it keeps it
alive, and a separate limit ends it regardless of use — so a teacher who opens
the app daily is not signed out mid-week, while no session lasts forever on any
device. A platform operator's console is the strictest of them: idle for half an
hour, and over within a working day. See
`architecture/adr/ADR-022-session-lifetime-by-surface.md` for the limits and the
reasoning.

---

## Parent

A responsible adult in a household, and — where the school has chosen separate
parent logins — an authentication subject in their own right. Never a second
kind of account: one Person has one Account per school, whatever roles they
hold. See `parent-authentication.md`.

---

## Active Context

Which business experience the application is currently presenting.

---

## Credentials

Passwords, reset links and the rules protecting them (lockout, expiry, forced
reset).

A person may also sign in with a **code sent to their phone**, where the
school has enabled it — a factor rather than a credential: issued, verified
once and destroyed in flight, with nothing kept on the account between times.
A student may also hold a short **PIN** for signing in from a phone — a
credential of its own, alongside the password rather than instead of it, so
changing one never disturbs the other. See `mobile-otp-authentication.md` and
`mobile-pin-authentication.md`. A mobile number becomes a way in only when
somebody deliberately makes it one; the number on a person's record is a
contact detail, not a key to the building.

A school issues credentials rather than a person choosing one unaided: the
office can give a student a first password, replace one that has been lost,
or require a new one at the next sign-in without taking today's away. A
replacement invalidates the old password and ends the sessions it opened. An
issued password is shown once, to the operator who asked for it, and is never
stored, logged or recoverable afterwards — a lost slip is replaced, not looked
up. None of this happens on its own: no deployment, migration or policy change
issues, resets or expires anybody's credential.

---

# What This Module Does NOT Own

| Business Concept | Owner |
|------------------|-------|
| Person | People Domain |
| Staff | People Domain |
| Student Relationship | People Domain |
| Family Member | People Domain |
| Teacher | Academic Domain |
| Business Authority | Authorization Domain |
| Authority Profile | Authorization Domain |
| Permission Key | Authorization Domain |

Identity Management references these concepts to decide which experiences are
available. It never creates or modifies them.

---

# Dependencies

## People Domain

Provides the Person an Account belongs to, and the business relationships that
determine which contexts exist.

## Authorization Domain

Decides what the signed-in user may do. Identity never answers that question.

---

# Sign In

## Purpose

Sign In establishes that the person operating a device is the owner of an
Account, and starts a session.

---

## Workflow

```
Credentials

↓

Tenant Resolved

↓

Account Located

↓

Credentials Verified

↓

Account Status Checked

↓

Session Created

↓

Active Context Selected

↓

Signed In
```

---

## Business Outcome

Successful sign-in produces:

- A session
- An access token and a refresh token
- The set of available contexts
- The selected Active Context

---

# Account Status

Sign-in is refused when the Account is not usable. The reason is a real business
event, never a generic flag.

- Active
- Locked — too many failed attempts, clears automatically
- Suspended — withdrawn by the school, cleared by the school
- Closed — the person no longer has access

Refusing sign-in never changes the Person or any business relationship. A
suspended Account belongs to a teacher who still teaches.

---

# Sessions

A session represents one signed-in device.

Access tokens are short-lived and are refreshed using the refresh token without
asking the person to sign in again. Signing out revokes that device's session
and leaves other devices signed in — including the unauthenticated cookie path,
which since 2026-09-07 ends one session rather than all of them.

The refresh token **may be spent once**: renewing returns a new one and kills
the old. See `architecture/identity-domain.md` for what that means for a
client — store the replacement, and renew in one place.

Sessions are revoked when:

- The person signs out.
- The password changes, or a forced change is completed (every session but the
  one completing it).
- The account is suspended or closed. Reactivating restores none of them.
- The school disables the method the session was opened with.
- A spent refresh token is presented again — the session and its whole token
  family end, because two parties are holding one credential.
- The refresh token expires.

A revocation is felt on the next request, not at the next renewal: an access
token names its session and is refused once that session is gone.

---

# Active Context

## What it is

A Person may hold several business relationships at once. A teacher may be the
parent of a student in the same school. The application presents one of those
experiences at a time, and that choice is the Active Context.

Changing it changes navigation, the home screen and the default workflows.

It never changes authorization. A person carries the same business authority in
every context (ADR-006).

---

> **Implementation status (2026-08-08):** context *derivation* is live — the
> GraphQL `me` query returns a person's available contexts. Session-stored
> context and switching are **deliberately deferred** (ADR-011): under the
> default family access model nearly everyone holds exactly one context, so
> there is nothing to switch yet. Everything below describes the target
> design, not current behaviour.

## Where it lives

Active Context belongs to the **session**, not to the person.

A parent may be reading their child's attendance on a phone while the same
person, as a teacher, has a class list open on a laptop. Storing the context on
the person would make one device silently change the other.

A new session starts in the context the person is most likely to want, chosen
from their available contexts. Because reopening the application reuses the
existing session, the previous experience is restored automatically, which is
the behaviour ADR-004 requires.

---

## Available contexts

Available contexts are derived from the Person's business relationships. They
are never stored, so they cannot drift from the relationships they describe.

| Relationship | Context |
|--------------|---------|
| Staff | Staff |
| Staff participating academically | Teacher |
| Student Relationship | Student |
| Family Member of a student | Parent — only where the organization issues parent logins |

A Person with no business relationship has no context and cannot use the
application, even with a valid Account.

Under the default family access model most people hold exactly one context, and
the application presents it without asking (ADR-011).

---

## Switching

```
Signed In

↓

Select Available Context

↓

Session Context Updated

↓

Experience Changes
```

Switching requires no re-authentication and does not affect other sessions.

Requesting a context the Person does not hold is refused.

---

## Notifications

Notifications belong to the Person, not to a context (ADR-004). Opening a
notification switches the session to the context that notification belongs to,
then navigates. The person never has to switch manually to read their own
notification.

---

# Family Access

Who in a household receives an Account is an organization setting, not a fixed
rule (ADR-011).

**Shared with student** — the default. The school issues one credential per
student and the household uses it. Parents are recorded as People and Family
Members but hold no Account, which is ordinary rather than exceptional:
authentication has always been optional.

**Separate parent login** — parents receive their own Account and a Parent
context.

Because parents are modelled as People in both modes, moving a school from one
to the other means issuing Accounts to People who already exist. It requires no
migration.

While access is shared, everything the account can see, the student can see.
Communication that is genuinely unsuitable for a child must not be delivered to
a shared account.

---

# Password Reset

Two workflows, for two different business situations.

**Forgotten password** — the person requests a reset link, proves control of
their registered contact, and sets a new password.

**Forced reset** — the school issues a temporary password, and the person must
choose their own before continuing. This is the normal path when an
administrator creates an account for someone.

Both revoke every existing session: a password change means the old credential
is gone everywhere.

---

# Account Lifecycle

```
Person Exists

↓

Account Created (Optional)

↓

Active

↓

Suspended / Restored

↓

Closed
```

Closing an Account never removes the Person, their relationships or their
history. It removes access, nothing else.

---

# Transport

Credential handling stays on REST, which is where the backend architecture
places infrastructure concerns: sign in, sign out, token refresh and password
reset.

Identity questions the application asks about the signed-in person are GraphQL,
because they are business capabilities:

- The signed-in Person and their relationships
- Available contexts
- Switching the Active Context

Each operation is exposed by exactly one transport.

---

# Business Rules

## A Person may have at most one Account.

One human, one credential, however many responsibilities they hold.

---

## An Account always belongs to a Person.

Accounts are never created on their own.

---

## Authentication is optional.

A Person without an Account is a full participant in the school's records.

---

## Closing an Account never removes business history.

Access and identity are independent lifecycles.

---

## Active Context never grants authority.

It selects an experience. Authorization is evaluated independently on every
action.

---

## A context must be held to be selected.

Available contexts always derive from current relationships.

---

## Changing a password ends every session.

---

# Related Documents

- ../architecture/identity-domain.md
- ../architecture/people-domain.md
- ../architecture/authorization-domain.md
- ../architecture/adr/ADR-003-identity-authentication-separation.md
- ../architecture/adr/ADR-004-active-context.md
- ../architecture/adr/ADR-010-incremental-v1-to-v2-migration.md
- ../architecture/adr/ADR-011-family-access-model.md
