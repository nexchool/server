# Architecture Compliance Report — Stabilization Milestone

**Date:** 2026-08-07
**Question:** does the implementation still faithfully represent the architecture
in `server/docs`?
**Evidence:** the code and the database. Performance measured on the committed
scale fixture at 500 / 5,000 / 15,000 students, never on the demo tenant.
**Suite:** 1,259 passing.

---

# People Foundation

**Completion: 95%** · **Status: stable**

One record per human, and every path that learns something about a person
writes it there — admission, edits, both bulk importers, self-service profile
changes, the platform admin form. Households express single parents,
grandparents and court-appointed guardians through one structure, and name the
adult the school actually rings.

People depends on nothing, enforced by a test that reads imports. That is the
property the whole dependency order rests on.

**Remaining risk.** Duplicate detection is quadratic inside a match bucket. On
ordinary data that is a second; on migrated data where thousands of parents
share one office number it is 65 seconds — measured, not estimated.

**Debt.** The student family columns are still dual-written, because the Expo
app reads them.

**Blocking:** none.

**Recommendation.** Bound the duplicate scan before the first real school is
imported. It is the one People defect a customer would meet on day one.

---

# Identity

**Completion: 90%** · **Status: stable**

Authentication implemented once and consumed by both transports. The boundary
leak is closed: `available_contexts` asks People rather than reading Academic,
and an import-level test keeps it closed.

The rule that an account belongs to a person lives here, in Identity, because
it is a fact about accounts — not in People, which must not know accounts
exist.

**Remaining risk.** None material.

**Debt.** Active Context is designed (ADR-004) and not stored. Correct: there
is nothing to switch to while households share a login (ADR-011).

**Blocking:** none.

---

# Authorization

**Completion: 55%** · **Status: half migrated, and the half that is done is the
irreversible half**

Authority is held by the employment, not the login. Ending employment ends
authority with no second flag to remember. Delegation exists. Being a student
implies a student's access without a grant. `user_roles` is dropped.

**What is not done.** The vocabulary. Business Actions, Capabilities and
Authority Profiles are still documents; the live check is
`has_permission(user, "attendance.manage")` across 16 files.

**Remaining risk.** Every module written before the vocabulary moves will use
the old one. That is a rewrite of call sites, not a redesign — which is
precisely why the holder was moved first.

**Blocking:** none. It does not block Examination.

**Recommendation.** Do this before the next *two* modules rather than the next
one. The cost grows linearly with modules written, and it is mechanical.

---

# Academic Foundation

**Completion: 70%** · **Status: sound, poorly navigable**

Admission and academic enrollment are separated as ADR-007 requires:
`student_class_enrollments` owns placement and carries history.
`students.class_id` is a cache with one writer, now proven by test.

**Remaining risk.** Academic has no owner module. The domain is spread across
`classes`, `academics`, `grades`, `mediums`, `academic_programmes` and
`subjects`. Ownership is documented but invisible in the layout, so a new
reader cannot find it — and this milestone found two duplications hiding in
exactly that gap.

**Debt.** `classes.teacher_id` remains as a cache, permanently and by decision.

**Blocking:** none.

**Recommendation.** Give Academic an owner module before it grows further.
Examination will add to it.

---

# Teaching Assignment

**Completion: 90%** · **Status: newly the single abstraction**

`class_subject_teachers` owns subject teaching. `class_teacher_assignments`
owns class-teacher responsibility. `class_teachers` is dropped, and
`is_class_teacher` with it — a responsibility for a whole class was being
stored as a property of teaching one of its subjects, and that blur is what let
the two questions be confused.

Every consumer now asks the service: notification targeting, per-class teacher
counts, the class roster, the timetable generator's period-one priority, the
class-teacher picker, and branch scoping — which had been unioning three tables
and was the clearest evidence of what the ambiguity cost.

Time is part of every question. Asking about a past date deliberately ignores
whether an assignment is active today, because that flag describes standing
now, not standing then.

**Remaining risk.** The service is new and has one week of use. Its API shape
is the thing every future academic module will depend on.

**Debt.** None created. The drop carried nothing because every row was already
recorded by an owner — verified by the migration rather than assumed, and it
earned that: it refused the drop locally when the fixture had created
assignments the owners did not have.

**Blocking:** none.

---

# GraphQL

**Completion: 20% of surface, 100% of the architectural property**

Little is exposed yet — the signed-in person and the transport query. What
matters is that the shape is right and now enforced:

```
REST     → Service → Repository
GraphQL  → Service → Repository
```

Neither transport imports an HTTP client that could reach the other. REST does
not depend on GraphQL. A resolver may name a model but may not run a query.
All three checked against planted violations.

**Remaining risk.** The property is easy to keep while the surface is small and
easy to lose while it grows. The guards exist for that reason.

**Blocking:** none.

---

# Migration Debt

**Status: every item has an exit, and three closed this milestone**

| Debt | Still required? | Removed by |
|---|---|---|
| Student family columns dual-written | **Yes** — the Expo app reads them | M2, with the mobile client |
| Account→person listener | **Yes** — 75 creation sites | Permanent by decision; relocated to Identity |
| Duplicate scan loads every person | **Yes** | M5 — and now urgent, see Performance |
| `students.person_id` alongside `user_id` | No | Closed |
| Identity reading v1 tables | No | Closed |
| Authority on both account and employment | No | Closed |
| `class_teachers` | **No — dropped this milestone** | ADR-014 / migration 092 |
| `classes.teacher_id`, `students.class_id` | Permanent **caches**, not debt | Never; guarded by test |

No temporary layer is without an exit. The two permanent caches are
deliberately not debt, and are now the only duplication of business information
in the system — proven not to drift.

---

# Performance

**Status: acceptable at production scale, with two named bottlenecks**

Measured on the committed fixture at 15,000 students / 45,600 people / 600
teachers / 4,000 riders / 20 campuses.

| Operation | Rows | Queries | Time |
|---|---|---|---|
| Students, page of 20 | 20 | 3 | 45 ms |
| Students, page of 100 | 100 | 3 | 45 ms |
| Teachers, page of 100 | 100 | 5 | 35 ms |
| Transport enrollments, paged | 20 | 4 | 58 ms |
| Classes list | 300 | 2 | 68 ms |
| **Transport buses** | 80 | **84** | 87 ms |
| **Transport dashboard** | — | **87** | 113 ms |
| **Duplicate suggestions** | 100 | 1 | **65 s** |

## Architectural bottlenecks

**B1 — duplicate detection is quadratic within a match bucket.** Not an
implementation slip: the algorithm is correct and the shape is the problem.
Migrated school data puts thousands of parents on one placeholder phone number,
producing one enormous bucket. 65 seconds is a request that times out.

**B2 — `_bus_operational_warning` runs once per bus.** 81 of the 84 queries
listing buses. Bounded by the fleet, but a twenty-campus trust's fleet is
eighty.

## Implementation bugs found and fixed

None outstanding. Both N+1s introduced during migration (the `family` key on
the student list, the teachers list re-fetching accounts) were found by
measurement and fixed, each with a guard.

**Recommendation.** B1 before the first customer import; B2 whenever transport
is next touched.

---

# Documentation Compliance

| ADR | Status |
|---|---|
| 001 person-centric | **Implemented** |
| 002 family relationship model | **Implemented** |
| 003 identity / auth separation | **Implemented** |
| 004 active context | **Deferred** — correctly; nothing to switch to yet |
| 005 teacher as participation of employment | **Implemented** |
| 006 business authority | **Partial** — holder yes, vocabulary no |
| 007 admission vs academic enrollment | **Implemented** |
| 008 teaching assignment | **Implemented** — this milestone |
| 009 academic year as operational context | **Implemented** |
| 010 incremental migration | **Implemented** |
| 011 family access | **Implemented** |
| 012 academic reconciliation | **Partial** — mapping honoured, no owner module |
| 013 authority belongs to the relationship | **Implemented** |
| 014 teaching single ownership | **Implemented** — this milestone |

## Deviations

**One, deliberate.** Milestone M3 says *retire* the account→person listener; it
was **relocated** to Identity instead. Retiring it means 75 creation sites each
repeating the same rule — more places to forget, not fewer. The same argument
justifies the tenant-scope listener nobody proposes removing. What was wrong
was the module it lived in.

**Recommendation: change the documentation.** M3's wording should say relocate.
The implementation is right.

**Two findings from this milestone were mine and are corrected in the record:**
AC2 claimed a student's class had two owners — it has one, and I raised it
without reading the service that maintains it. AC3 claimed three tables for one
concept — it was two concepts, one healthy and one genuinely duplicated. Both
withdrawn or corrected in the foundation review rather than left standing.

---

# Final Verdict

## Does every business concept have exactly one owner?

**Yes.** The last duplication — subject teaching — was closed this milestone.
The only remaining duplication of business *information* is the two caches,
which have declared owners and tests proving they cannot drift.

## Does every domain still respect its boundaries?

**Yes**, and four of them are enforced by tests that read imports rather than
exercise behaviour.

## Is Teaching Assignment the single abstraction?

**Yes.** Every consumer asks the service. No operational module queries the
teaching tables.

## Is migration debt documented, with exits?

**Yes.** Three items closed this milestone; every survivor names the milestone
that removes it or is a decided permanent cache.

## Is the business language consistent?

**Mostly.** Rename candidates, kept separate from migration work:

| Now | Should become | Why it matters eventually |
|---|---|---|
| `modules/rbac` | Authorization | The domain moved; the name says v1 |
| `has_permission("x.manage")` | Business Actions | 16 files; the largest naming gap |
| `aadhar_number` / `aadhaar_number` | one spelling | 7 files; cosmetic but confusing |

None should be renamed for cosmetic reasons alone. All three should move with
the Authorization vocabulary work, which touches those files anyway.

## Are GraphQL and REST sharing services?

**Yes**, and it is now enforced rather than observed.

## Are performance characteristics acceptable at production scale?

**Yes for every operational path.** Two bottlenecks named above, neither on a
path a school uses per lesson.

## Is the foundation stable enough to build on?

**Yes.** The architecture is internally consistent, every concept has an owner,
the boundaries are enforced by tests rather than intent, and the properties
that were previously true-by-luck are now true-by-test.

---

# Recommended Next Milestone

**M7 — Authorization Vocabulary**, then Examination.

Not because Authorization blocks Examination — it does not — but because every
module written before it lands accrues call sites in the old vocabulary, and
Examination is a large module. Doing it first means writing Examination once.

It also carries the three rename candidates, which touch the same files.

**Examination is now safe to build.** The two things it attaches to — a class
and a teaching assignment — each have exactly one owner, and the historical
question a report card depends on ("who taught this subject in November") can
be answered correctly. Before this milestone it could not.
