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

2. **The backfill merges only on conclusive evidence.** Where the evidence is
   conclusive it merges automatically, because leaving thousands of known
   duplicates for a human to clear is its own kind of data loss. Where the
   evidence is merely suggestive it creates separate People and records a
   suggestion for an administrator.

3. **Conclusive means same family role, same phone or email, and same name.**
   The rule is defined in *Automatic Merging* below. Everything outside it is a
   suggestion.

4. **Per-module cutover.** A module moves to the v2 model as a unit: its reads
   move to Person, its writes follow, and only then are its legacy columns
   removed. Modules not yet migrated continue to work unchanged.

---

# Automatic Merging

Two parent records describe the same human, and are merged automatically, when
**all** of the following hold within one organization:

- They occupy the **same family role** — father with father, mother with mother,
  guardian with guardian.
- Their **phone numbers match**, compared as digits only with any country code
  or leading zero removed. An email match may substitute for a phone match.
- Their **names match** after normalisation — lower-cased, punctuation and
  honorifics removed, internal spacing collapsed.

A missing phone and email is never enough on its own. Names alone are never
enough.

Anything that does not satisfy every condition becomes two People and one
suggestion.

---

## Why the family role guard is the important part

The tempting rule is "same phone number means same person", and in Indian
schools that rule is wrong in both directions.

A father and a mother routinely share one household phone. Matching on phone
alone would fuse two different humans into a single record. Conversely a parent
who also teaches at the school often gives a different number in each capacity,
so phone matching alone would also miss a genuine duplicate.

Comparing only within the same family role removes the dangerous half of that
problem by construction: a father can never be merged into a mother, no matter
how much contact information the household shares. Requiring the name to match
as well as the phone covers the remaining case of a recycled or mistyped number.

## Why merge at all rather than leave it to administrators

Sibling duplication is systematic, not occasional. In a school where a third of
students have a sibling enrolled, refusing to merge produces thousands of
duplicate parents — a backlog nobody will ever clear, which means parent
communication and fee records stay fragmented indefinitely. Automating the cases
that are beyond doubt is what makes the remaining suggestions few enough to be
reviewed at all.

## Why the boundary sits where it does

**Merging is recoverable, unmerging is not.** A merge records what it combined,
so it can be undone. A wrong merge that is never noticed silently destroys the
knowledge of which fact belonged to which human. The rule above is therefore
drawn to include only cases where being wrong is implausible, and to leave
everything else — including a parent who appears to also be a staff member — to
a human who can simply ask.

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

## Option 3 — Additive, per-module, with bounded automatic merging

### Advantages

- Every step is reversible and independently deployable.
- Production keeps running throughout.
- Systematic sibling duplication is resolved without human effort.
- People are never fused on ambiguous evidence.
- The transitional state is visible in the schema, so it cannot be forgotten.

### Disadvantages

- A period during which both old columns and new tables exist.
- Suggested duplicates persist until an administrator reviews them.

Decision:

Accepted.

---

# Consequences

## Positive

- Production continues serving schools during the migration.
- Each migration step is small, reviewable and reversible.
- Siblings resolve to one father and one mother without manual work.
- No person record is corrupted by an automated guess.
- The backfill is rehearsable: it can be run repeatedly against a copy.

## Trade-offs

- The schema carries transitional duplication until cleanup migrations run.
- Parents recorded under different names or numbers for different children stay
  separate until someone confirms the suggestion.
- Every merge must record what it combined, or the guarantee that merges are
  recoverable is not real.
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

Everything short of the automatic rule becomes a suggestion shown to an
administrator, who confirms or dismisses it.

Typical suggestions:

- Same phone, similar but not identical name.
- Same name in different family roles — possibly one household phone, possibly
  two different people.
- A parent who appears to also be a staff member.
- Same date of birth and similar name.
- Same government identifier.

Every merge, automatic or confirmed, records what it combined, so the decision
remains auditable and recoverable.

---

# Related Documents

- ADR-001-person-centric-architecture.md
- ADR-002-family-relationship-model.md
- ADR-003-identity-authentication-separation.md
- people-domain.md
- ../../modules/identity-management.md
