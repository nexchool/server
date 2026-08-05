# ADR-010 — Incremental Migration from the v1 Schema

## Status

Accepted

---

## Date

2026-08-05

---

# Context

The v1 platform is in production. It models people as three independent records,
each of which carries its own copy of a person's identity.

```
users      email, password, name, profile picture
students   user_id, date of birth, gender, phone, address,
           father name / phone / email / occupation / income,
           mother name / phone / email / occupation / income,
           guardian address / occupation / Aadhaar
teachers   user_id, phone, address, joining date, designation, status
```

Four properties of this schema decide how the migration must work.

**Every student and every teacher requires a login.** `students.user_id` and
`teachers.user_id` are both NOT NULL. A driver, a nursery student or a parent who
never opens the app cannot be represented at all. ADR-003 requires the opposite:
authentication is optional.

**Parents do not exist as records.** They are columns on the student row. The
platform seeds a "Parent" role and the mobile application has a parent
experience, but nothing anywhere links a parent to a child. The parent portal is
therefore unimplemented rather than implemented differently — there is no parent
data to preserve beyond those columns.

**Siblings duplicate their parents.** Two children of one family each carry a
full copy of the father and mother details, with nothing connecting them.

**Identity is duplicated across tables.** Name lives on `users`, phone and
address on both `students` and `teachers`, date of birth and gender on
`students`.

The v2 architecture (ADR-001) replaces this with one Person per human and
independent business relationships. The question this record answers is how to
get from one to the other while production keeps running.

---

# Decision

The migration is **incremental and additive**, performed module by module, and
it **never merges two people automatically**.

Concretely:

1. **Add, then backfill, then constrain, then clean up.** Each step is its own
   migration. New structures are introduced nullable, populated, and only then
   made mandatory. Legacy columns are dropped in a separate, later migration once
   nothing reads them.

2. **One Person per existing record.** The backfill creates exactly one Person
   for each existing user, and one Family per existing student. It preserves
   today's reality precisely rather than improving it.

3. **Merging people is a business decision, not a migration step.** The platform
   surfaces suggested duplicates and provides an explicit merge workflow that a
   school administrator performs and can review. The migration itself never
   guesses.

4. **Per-module cutover.** A module moves to the v2 model as a unit: its reads
   move to Person, its writes follow, and only then are its legacy columns
   removed. Modules not yet migrated continue to work unchanged.

---

# Rationale

## Why not merge automatically

The tempting rule is "same phone number means same person". In Indian schools
that rule is wrong in both directions.

A father and a mother routinely share one phone number, so matching on phone
would merge two different humans into one. Conversely a parent who is also a
teacher often gives the school a different number in each capacity, so matching
on phone would fail to merge one human recorded twice.

The asymmetry that settles it: **merging two people is reversible only if the
merge is recorded; splitting a wrongly merged person is not.** Once a father's
and mother's records are fused, the information needed to separate them —
which fact belonged to whom — is gone. A duplicate person, by contrast, is
visible, harmless and correctable at any later date.

So the migration produces duplicates on purpose. A school with many siblings will
see the same parent listed once per child until an administrator merges them.
That is a known, stated cost, chosen because the alternative corrupts records
irreversibly and silently.

## Why additive rather than a rewrite

Business Principle 9 and Engineering Principle 10 both require evolution through
a compatibility layer instead of a rewrite. Additively adding `person_id`
alongside the existing columns means every migration step leaves the tree
deployable and every step is individually reversible, which is what makes it
safe to run against a production database that is serving schools.

## Why per-module rather than all at once

The People model touches students, staff, families, attendance, fees and
communication. Converting them together would mean a single change that cannot
be verified in parts and cannot be rolled back in parts. Converting them one at a
time keeps each change small enough to review and reverse.

---

# Alternatives Considered

## Option 1 — Greenfield database, re-onboard every school

### Advantages

- Clean schema with no transitional state.
- No backfill logic to write or verify.

### Disadvantages

- Discards live production data.
- Every pilot school must be re-onboarded manually.
- The migration is never rehearsed, so the same problem returns for the next
  schema change.

Decision:

Rejected.

---

## Option 2 — Convert the whole schema in one migration

### Advantages

- Short transitional period.
- No compatibility columns.

### Disadvantages

- Cannot be verified incrementally.
- Cannot be rolled back partially.
- Requires every module and client to change simultaneously.

Decision:

Rejected.

---

## Option 3 — Additive, per-module, with explicit merging

### Advantages

- Every step is reversible and independently deployable.
- Production keeps running throughout.
- People are never silently fused.
- The transitional state is visible in the schema, so it cannot be forgotten.

### Disadvantages

- A period during which both old columns and new tables exist.
- Duplicate people persist until administrators merge them.

Decision:

Accepted.

---

# Consequences

## Positive

- Production continues serving schools during the migration.
- Each migration step is small, reviewable and reversible.
- No person record is ever corrupted by an automated guess.
- The backfill is rehearsable: it can be run repeatedly against a copy.

## Trade-offs

- The schema carries transitional duplication until cleanup migrations run.
- Duplicate Person records exist until merged, most visibly for siblings' parents.
- Every migrated module needs a cleanup migration, which must actually be
  written rather than left indefinitely.

---

# Migration Sequence

Each module follows the same four steps.

```
Add structures (nullable)

↓

Backfill from existing data

↓

Apply constraints

↓

Cut the module over

↓

Drop legacy columns
```

Legacy columns are dropped only after the module reads and writes exclusively
through the v2 model.

---

# Duplicate Suggestions

The platform may suggest that two Person records describe the same human.
Suggestions are advisory and are shown to an administrator for confirmation.

Reasonable signals include:

- Same phone number and similar name.
- Same date of birth and similar name.
- Same government identifier.

A suggestion never results in an automatic merge, and a merge always records
what was combined so the decision remains auditable.

---

# Related Documents

- ADR-001-person-centric-architecture.md
- ADR-002-family-relationship-model.md
- ADR-003-identity-authentication-separation.md
- people-domain.md
- ../../modules/identity-management.md
