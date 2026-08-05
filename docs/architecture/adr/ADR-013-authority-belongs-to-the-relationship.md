# ADR-013 — Authority Belongs to the Relationship, Not the Account

## Status

Accepted

---

## Date

2026-08-05

---

# Context

The Authorization Domain describes Business Authority, Authority Profiles,
Capabilities, Business Actions, Permission Keys, Scope and Temporary Delegation.
Read alone it suggests a domain waiting to be built.

Reading v1 shows most of it already exists under technical names.

| Domain concept | v1 implementation |
|----------------|-------------------|
| Permission Key | `permissions.name` — already `student.create`, `fee.collect` |
| Authority Profile | `roles` + `role_permissions` |
| Capability | a module in the sub-admin catalog (`students`, `finance`) |
| Business Action | that module's levels (`view`, `edit`, `operate`, `manage`) and toggles (`delete`, `refund`) |
| Scope | `core/branch_scope.py` — branch-aware modules |
| Authorization Decision | `require_permission` → `has_permission`, with `manage` implying the rest |

Building `authority_profiles`, `capabilities`, `business_actions` and
`permission_keys` beside these would repeat the mistake ADR-012 exists to
prevent: duplicate ownership, created in the name of following the architecture.

Three things, however, are genuinely absent — and one of them is the principle
the whole domain rests on.

---

# Decision

**Authorization is reconciled with the existing tables, as in ADR-012.** Role is
the Authority Profile. `permissions.name` is the Permission Key. The sub-admin
catalog is the Capability and Business Action vocabulary. No parallel tables.

**Authority is attached to the business relationship, not to the account.**
ADR-006 states it plainly: *"A User never owns authority. Authority belongs to
the business relationship."* v1 assigns roles to a User. That is the one
structural difference, and it is the one being closed here.

A new record — `staff_authorities` — states that an employed person holds an
Authority Profile. Permission resolution reads it, and **only while the
employment is live**.

---

# Why This Is the Difference That Matters

Attaching authority to an account makes revocation a thing somebody must
remember. A teacher resigns; their employment ends; their account may sit
untouched for weeks still carrying `student.manage`. Nothing in the system knows
the two facts are related.

Attaching it to the employment makes revocation a consequence. Employment ends,
authority ends, because the authority was never anything but an aspect of that
employment. Nobody has to remember.

The same follows for the other cases the domain describes:

- A person who is both teacher and parent holds one account and one set of
  authorities, derived from the relationship that grants them — not from
  whichever role someone attached to the login.
- A suspended employee loses authority for the duration without their account
  or history being altered.
- Delegation becomes expressible: authority can be lent from one employment to
  another for a period, because it lives somewhere that has a lifecycle.

---

# What Is Still Missing After This

Stated so it cannot be mistaken for finished.

1. **Temporary Delegation** — no representation yet. It belongs against the
   employment, with effective and expiry dates, and it expires without
   intervention.
2. **Capabilities as data.** The catalog is a Python dictionary, so a school
   cannot create the Authority Profiles the domain promises ("Academic
   Coordinator", "Examination Coordinator"). Until it is data, School Authority
   Profiles do not exist.
3. **Retiring account-held roles.** `user_roles` remains during transition;
   permission resolution reads both. Migration debt, with an exit below.

---

# Alternatives Considered

## Option 1 — Build the domain as new tables

### Advantages

- Vocabulary matches the documents exactly.

### Disadvantages

- Four tables duplicating four that exist and work.
- Two authorization systems live at once, on the path every request takes.
- Repeats precisely the error ADR-012 records.

Decision: Rejected.

---

## Option 2 — Rename the v1 tables to the domain vocabulary

### Advantages

- One name per concept, everywhere.

### Disadvantages

- A mass rename of live tables on the request-critical path, for vocabulary
  rather than behaviour.

Decision: Rejected. The mapping is recorded instead, as with Section and Class.

---

## Option 3 — Reconcile, and move authority onto the relationship

### Advantages

- No duplicate ownership.
- Closes the principle the domain rests on.
- Revocation becomes a consequence rather than a chore.
- Leaves delegation and school-defined profiles straightforwardly addable.

Decision: Accepted.

---

# Consequences

## Positive

- Authority ends when employment ends, without anyone acting.
- Suspension withdraws authority without touching the account or its history.
- One authorization model, not two.

## Trade-offs

- Two sources of authority during transition — account-held and
  relationship-held — resolved as a union. Migration debt, tracked below.
- Permission resolution now depends on employment status, so a change of
  employment must invalidate the cached permission set. Until it does, a
  departure takes effect within the cache TTL rather than immediately.
- Role remains the table name for Authority Profile; this record is the bridge.

---

# Migration Debt

**Two sources of authority.**

- *Why:* every existing user holds authority through `user_roles`, and every
  route depends on it.
- *Goes when:* assignments are moved onto employments and the account-held path
  is removed.
- *Removed by:* Milestone **M4 — Authorization**, after which `user_roles` is
  dropped.

---

# Related Documents

- authorization-domain.md
- ADR-006-business-authority-authorization.md
- ADR-012-academic-domain-reconciliation.md
- reviews/2026-08-05-foundation.md
