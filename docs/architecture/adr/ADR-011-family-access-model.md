# ADR-011 — Family Access Model

## Status

Accepted

---

## Date

2026-08-05

---

# Context

Nexchool needs to decide who receives a login on behalf of a family.

The architecture already supports the general case: a Person may hold a Student
relationship or a Family Member relationship, each of which could carry its own
Account and its own experience (ADR-001, ADR-003, ADR-004).

Real schools are narrower than that. In the Gujarat day schools Nexchool is being
built for, the school issues one set of credentials per student, and whoever in
the household needs it uses it. A parent of a Grade 2 student holds the child's
login because the child has no phone. A Grade 11 student uses it themselves.

The information each of them opens the application to see is very largely the
same: timetable, attendance, homework, holidays, announcements, results, fees.

The v1 platform reflects this by accident rather than by design. It seeds a
"Parent" role and the mobile application has a parent experience, but nothing
links a parent to a child, so the parent experience cannot function. In practice
families use the student's credentials.

Building a separate parent portal now would mean building a second set of
credentials, a second notification target and a second experience for an audience
that has not asked for them.

---

# Decision

Family access is a **per-organization setting**, not a fixed architecture.

**Shared with student** — the default. The Student relationship carries the
Account. Parents exist as People and as Family Members, and receive no Account.
There is no Parent context.

**Separate parent login** — optional. Parents receive their own Account, their
own Person identity and a Parent context alongside whatever else they hold.

Both modes run on the same data model. Parents are recorded as People and Family
Members from the first day regardless of which mode a school uses.

---

# Rationale

## The product should match how schools actually distribute logins

Most Indian day schools hand out one credential per student at admission. A
platform that insists on separate parent accounts forces the school to collect
parent emails it does not have, and to explain a second login to families who
did not want one.

## The information needs genuinely overlap

Where the student and parent views differ, they differ in emphasis rather than
content. That does not justify two identities.

## Deferring costs nothing later

This is the decision that makes the deferral safe: **parents are modelled
properly from the start even though they cannot log in.** They are People, with a
Family Member relationship, a name, a phone and a role in the family.

Turning on separate parent logins for a school therefore means issuing Accounts
to People who already exist. It is not a schema change, not a data migration and
not a new domain — which is precisely the property the v2 architecture was built
to have. Configuration, not forks.

Had parents remained columns on the student row, as in v1, this decision would
have been irreversible without a migration.

---

# Alternatives Considered

## Option 1 — Separate parent accounts everywhere

### Advantages

- One model for every school.
- Actions are attributed to an individual.

### Disadvantages

- Builds an experience no current school has asked for.
- Requires parent contact details the school often does not hold.
- Two credentials per family to issue, reset and support.
- Duplicates most of the student experience.

Decision:

Rejected for now.

---

## Option 2 — Parent account only, no student account

### Advantages

- Single credential per family.
- Matches primary school reality.

### Disadvantages

- Senior students genuinely use the application themselves.
- A student would depend on a parent to see their own timetable.

Decision:

Rejected.

---

## Option 3 — Per-organization setting, shared by default

### Advantages

- Matches how schools operate today.
- Nothing unused is built.
- Schools that need separate logins can have them.
- Switching modes requires no migration.

Decision:

Accepted.

---

# Consequences

## Positive

- One credential per student, which is what schools already issue.
- No parent portal is built before a school wants one.
- The Family model still records parents, so communication, fees, emergency
  contacts and sibling detection all work.
- International and metropolitan schools can enable separate logins without a
  code change.

## Trade-offs

**Attribution becomes family-level.** An action taken on a shared account cannot
distinguish the student from the parent. Audit records will say the account
acted, not which human did. For fee payments and consent this is a real
limitation, and it is the main reason a school would switch modes.

**Everything the account can see, the student can see.** Fee dues, outstanding
amounts and any communication meant for a parent are visible to the student.
Content genuinely unsuitable for a child must not be delivered to a shared
account.

**Notifications address the household, not a person.** Until separate logins are
enabled, a message intended for a parent reaches the family's single account.

---

# Impact on Active Context

Under shared access most people hold exactly one context, and the application
presents it without asking.

Active Context remains part of the architecture because it is what makes the
other mode work: when a school enables separate parent logins, a teacher who is
also a parent at that school holds two contexts and switches between them
(ADR-004). Nothing about the mechanism changes — only how many people have more
than one context to switch between.

---

# Related Documents

- ADR-001-person-centric-architecture.md
- ADR-002-family-relationship-model.md
- ADR-003-identity-authentication-separation.md
- ADR-004-active-context.md
- ../../modules/identity-management.md
