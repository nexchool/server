# Parent Authentication

A parent signs in as themselves, and reaches their own children.

---

# The shape of the thing

```
Person ──── FamilyMember ──── Family ──── FamilyMember(child) ──── Student
            (father)                            × many
```

A parent is **one Person and one membership**. Their children are the other
members of the same household. So one parent with three children is:

```
ONE Person · ONE Account · THREE family relationships
```

and never three parent accounts. The constraint that makes this work already
existed: `family_members` is unique on `(family_id, person_id)` — scoped to the
household, not to a child — so a single membership covers every child in it.

**Nothing in the identity model changed for this.** No new table, no new
column, no second account. What Phase 6 added is a way to turn that
relationship into a login, and a way to ask which students it covers.

---

# A relationship is not an account

Recording that a father exists creates a Person and a membership. It does not
create a login, and no import, admission or backfill has ever done so.

An account appears only when somebody **provisions one deliberately**, for a
school that has chosen separate parent logins. That is what makes it
auditable.

The account hangs off the Person, not off any child. So removing one child's
relationship leaves the parent, their account, their credential and their
other children exactly as they were — tested.

---

# `family_access_mode` decides everything

ADR-011's setting, from Phase 0c, unchanged and not duplicated. Two values:

| | |
|---|---|
| `shared_with_student` | **the default.** A household signs in as the student. Parents are People and Family Members and receive no account. |
| `separate_parent_login` | A parent may be given an account of their own. |

Set by `PATCH /api/platform/tenants/<id>/auth-policy
{"family_access_mode": "separate_parent_login"}` — platform-admin only, like
every other read and write of this policy.

**Deploying Phase 6 changes nothing for a school on the default.** No parent
becomes an authentication subject, no role becomes holdable, no account is
created, and provisioning is refused outright. That is regression-tested, not
assumed.

Switching **on** makes provisioning *possible*, never automatic — turning the
mode on for a school with two hundred parents creates zero accounts.

Switching **off** destroys nothing: accounts, credentials, identifiers,
sessions and relationships all survive. The parent simply stops being a parent
authentication subject. Expand before contract; a policy change must never
delete identity.

---

# Parent is a subject kind, not a login method

The method is `email_password` — the existing strategy, unchanged, with no
`ParentEmailPasswordStrategy` anywhere. A session says:

```
login_method                 email_password
authenticated_identifier_id  the parent's email identifier
amr                          email_password
tid                          the school
```

There is no `parent_login` method, because "parent" describes *who* signed in,
not *how*.

The subject kind is derived from the relationship — a non-child membership —
**and** the mode. Both conditions, evaluated by the policy service that
already owned the question. Subject kinds are a union: a person may be staff
*and* parent *and* a former student, and holds every method any of those kinds
allows.

---

# The role nobody could hold

A `Parent` authority profile has been seeded into every school since roles
existed, with sensible read permissions for a child's attendance, timetable
and results. **Nobody had ever held it, and nobody could.** Authority is
implied by matching `roles.implied_by_relationship`; the catalogue never
declared one for `Parent`; so the implication had nothing to match on. The role
sat in every tenant, complete and unreachable.

Phase 6 declared it (`implied_by_relationship: 'parent'`) and migration 131
repaired the rows that already existed — the same shape as migration 103, which
is this repository's precedent for "the catalogue changed and existing rows
must follow", since the seeder deliberately only ever *adds* permissions.

**That grants nobody anything on its own.** The implication is gated on the
school running separate parent logins, and every school defaults to shared.

---

# Provisioning

```
provision_parent_login(person, email=…, actor_user_id=…)
```

The rules it will not bend:

**One account per person per school.** If the person already has one — because
they are a teacher, a former student, or the parent of a child admitted last
year — that account is **reused**. A second is never created, and the database
would refuse one anyway (`uq_users_tenant_person_live`). Reuse issues no new
password: they have one, and returning a new one would reset a working login
for somebody who did not ask.

**A real email, or nothing.** Phase 6 authenticates parents with email and
password, so an account needs an address. One is never invented, never derived
from a name, and never borrowed from the child. A parent with no usable
address gets no login and remains a perfectly valid Person with a perfectly
valid relationship — that is what ADR-003 means by authentication being
optional. An address already belonging to somebody else at the school is
refused rather than taken: silently taking it would give one human another's
password resets.

**The school must have chosen this.** Under shared access, provisioning is
refused rather than quietly preparing an account for later.

The password comes from the existing A5 generator — nothing derived from the
child's admission number, anybody's date of birth, a phone number or a name —
and is returned once, following the same contract every issued credential in
this codebase follows.

`users.email` was **not** made nullable, and no credential system was
duplicated: a parent password is an ordinary `credential_type='password'` row
through the existing issuance path.

---

# Authorization is relationship-scoped

Authentication says who signed in. It does not say what they may see.

`children_of(person)` answers the second question, from the relationship
rather than from anything the caller sends — there is no student id in the
request for somebody to substitute. It reads across **all** the households the
parent belongs to, not just one: a parent whose children live in two families
(a re-marriage, a guardian who took in a second child) is one person with one
account, and answering from a single household would silently drop half their
children.

Tenant scoping is structural: a membership belongs to a family, a family
belongs to a school, and the students are read inside the same one. There is no
path that could return another school's roll.

`may_access_student(account, student_id)` is a membership test against that
resolved set — so a parent asking about a child who is not theirs gets the same
answer as one asking about a child who does not exist.

**What remains deferred:** wiring that check into every child-facing module.
Phase 6 establishes the boundary and the foundational tests; the per-module
work belongs with the parent product, and until it is done a parent's
practical reach is what the `Parent` role's read permissions allow.

---

# What Phase 6 deliberately did not do

- **Debt 58 is untouched.** No mobile identifier is created, no parent is
  resolved by phone number, and the household-mobile uniqueness question is
  exactly where Phase 4 left it. Parent authentication here is email and
  password only.
- **No parent OTP or PIN.** Those are methods; adding them is a policy rule and
  a provisioning path, not a redesign.
- **No invitations.** The existing login-link is platform-admin-only by
  construction — its payload carries an admin id and its redeem path
  hard-filters `is_platform_admin=True`. It cannot onboard a parent, and
  inventing a second token architecture to make a screen look finished would
  have been the wrong trade. Provisioning is admin-driven; invitation
  onboarding is deferred work.
- **No parent portal.** There is no parent-facing client today, and Phase 6 did
  not build one.
- **No billing, no SMS, no provider contact.** Email and password cost nothing.

---

# A known ambiguity, reported not resolved

The person matcher deduplicates a family member by `(role, contact, name)` and
**requires a phone or an email**. Two consequences a school will meet:

1. A sibling imported with a blank parent phone, into a household that does not
   yet exist, creates a **second parent Person** — and therefore, if both are
   provisioned, two accounts for one human. The repair is the existing person
   merge tool, which is a human decision by design (ADR-010).
2. A parent recorded once as `father` and once as `mother` is two people, for
   the same reason.

Neither is introduced by this phase and neither is safe to fix automatically —
merging two people is exactly the judgement ADR-010 says to leave to somebody
who can ask. Worth knowing before a school provisions in bulk.
