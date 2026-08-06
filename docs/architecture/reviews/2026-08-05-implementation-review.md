# Implementation Review — Architecture Compliance

**Date:** 2026-08-05
**Scope:** the whole v2 implementation to date, reviewed against `server/docs`.
**Method:** the code and the database, not recollection. Performance measured on
a generated trust of **15,000 students, 45,600 people, 15,000 households, 600
teachers, 4,000 bus riders, 20 campuses, 300 classes** — not the 278-student
demo tenant, which hid two of the findings below.

---

# 1. Ownership

## Concepts with exactly one owner

| Concept | Owner | Verified |
|---|---|---|
| A human | `persons` | 0 duplicates by construction; merge records combinations |
| Household | `families` + `family_members` | relationship is a value (ADR-002) |
| The adult to call | `family_members.is_primary_contact` | one per household, partial unique index |
| Employment | `staff` | one per person, `uq_staff_tenant_person` |
| Employment history | `staff_employment_periods` | joining date = earliest period |
| Authority | `staff_authorities` | `user_roles` dropped (migration 089) |
| Class placement | `student_class_enrollments` | declared in `class_enrollment_service` |
| Class-teacher responsibility | `class_teacher_assignments` | declared in `academics/backbone/helpers` |

## Duplicated concepts remaining

**One, and it is real.** Subject teaching is recorded in both `class_teachers`
and `class_subject_teachers`, and until ADR-014 was written nothing declared an
owner. On the demo tenant: 51 rows identical in both, 4 present only in
`class_subject_teachers`. **ADR-014 settles ownership; the implementation has
not yet followed.**

`class_teachers.is_class_teacher` additionally stores *class-teacher
responsibility* on a *subject* row — a third home for that concept. ADR-014
removes it.

## Caches vs owners

Correctly separated, and now documented as such by ADR-014:

- `students.class_id` / `students.academic_year_id` — maintained by
  `assign_student_to_class`, which every placement path calls. On real data:
  0 students with a class and no enrollment, 0 with an enrollment and no class,
  0 disagreements across 278.
- `classes.teacher_id` — declared legacy compat in `academics/backbone/helpers`.

**Gap:** no automated guard proves either cache stays in step with its owner.
Both are correct today by inspection, not by test.

---

# 2. Domain Boundaries

**Enforced, and enforced by tests that read imports rather than behaviour.**

| Boundary | State |
|---|---|
| People → anything | Clean. `tests/test_people_knows_no_identity.py` passes; verified to fail when a violation is planted. |
| Identity → Academic | Clean. `available_contexts` asks `people/relationships.py`. |
| Academic → Identity | Clean. |
| Authorization → employment | Clean. Authority resolves from `staff_authorities` only. |

No module has started owning another domain's concepts. The one exception
worth naming is that **Academic has no owner module** (finding AC1): the domain
is spread across `classes`, `academics`, `grades`, `mediums`,
`academic_programmes` and `subjects`. Ownership is documented but not visible in
the layout — a navigability problem rather than a correctness one.

---

# 3. Business Language

**Model and service names match the documented vocabulary** for everything
built in v2: Person, Family, FamilyMember, Staff, StaffEmploymentPeriod,
StaffAuthority, AuthorityDelegation, StudentClassEnrollment,
ClassTeacherAssignment, ClassSubjectTeacher.

**Deliberate, documented divergence — not drift:**

- **Class vs Section.** ADR-012 ratifies `Class` as the code and API word,
  keeps Section as the domain word, and explicitly forbids a `sections` table.
  The implementation complies.

**Legacy terminology that should eventually be renamed:**

| Now | Should be | Why it has not moved |
|---|---|---|
| `modules/rbac` | Authorization | The domain moved (authority is on employment); the module name did not. Misleads a reader into thinking v1 RBAC is the model. |
| `has_permission(user, "x.manage")` | Business Actions / Capabilities | ADR-006 vocabulary is not implemented. Largest naming gap. |
| `class_teachers` | — (deleted) | ADR-014. |
| `students.aadhar_number` → `persons.aadhaar_number` | consistent spelling | Both spellings exist across the codebase. Cosmetic. |
| `modules/timetable` vs `academics/services/timetable_v2` | one timetable | Two live implementations; the old one is still mounted at `/api/timetable`. |

GraphQL exposes very little so far — `SignedInPerson` and the transport query —
and what exists uses domain vocabulary.

---

# 4. Teaching Assignment

| Question | Single owner? |
|---|---|
| Who teaches a subject in a class? | **No — two tables.** ADR-014 names `class_subject_teachers`; not yet implemented. |
| Who is responsible for a class? | **Partly.** `class_teacher_assignments` is the owner, but `class_teachers.is_class_teacher` is a second store (12 rows on demo data, all already in the owner) and `classes.teacher_id` is a declared cache. |
| Do operational modules consume an abstraction? | **No.** There is no Teaching Assignment service. Every consumer queries tables directly. |

**Consumers today:**

- `class_teachers` — 5 modules: `classes/services`, `classes/models`,
  `teachers/services`, `notifications/notification_targeting_service`,
  `timetable/generator`.
- `class_subject_teachers` — 12 modules across academics, dashboards, subjects
  and timetable v2.

The cost is already visible: `core/branch_scope.py::_allowed_teacher_id_subquery`
must union three tables to answer "is this teacher at this campus", because no
one place can answer it.

**Migration is unusually cheap.** Every `class_teachers` row is already recorded
elsewhere — 51 subject rows in `class_subject_teachers`, all 12
`is_class_teacher` rows in `class_teacher_assignments`, and all 51 subject rows
have a matching `class_subjects` parent. **No data migration is required**; the
work is five reader modules, one writer, and a table drop.

---

# 5. Migration Debt

| # | Debt | Why it exists | Removed by | Still required? |
|---|---|---|---|---|
| 1 | Student family columns (`father_*`, `mother_*`, `guardian_*`) dual-written | The Expo app reads them | M2, with the mobile client | **Yes** — the client has not moved |
| 2 | `students.person_id` alongside `user_id` | Two paths to a person | M1 | **No** — resolved; `person_id` is the single path |
| 3 | Account→person listener | 75 creation sites cannot each be trusted to remember | M3 | **Yes**, and correctly relocated to Identity |
| 4 | Identity reading v1 tables for contexts | Relationships were new | M1 | **No** — closed |
| 5 | Duplicate scan loads every person | Written for correctness first | M5 | **Yes** — see §6, it degrades badly on migrated data |
| 6 | Authority on both account and employment | — | M4 | **No** — closed, `user_roles` dropped |
| 7 | `class_teachers` | v1 subject teaching | ADR-014 (new) | **No** — redundant on every row |
| 8 | `classes.teacher_id`, `students.class_id` | Read performance | Never — permanent by ADR-014 | **Yes**, as caches; need drift guards |

---

# 6. Performance

Measured on the realistic trust. Query counts are per call.

| Operation | Rows | Queries | Time | Verdict |
|---|---|---|---|---|
| Students, page of 20 | 20 | 3 | 44 ms | Constant |
| Students, page of 100 | 100 | 3 | 44 ms | Constant |
| Students, searched | 20 | 3 | 54 ms | Constant |
| Teachers, page of 100 | 100 | 5 | 34 ms | Constant |
| Transport enrollments, paged | 20 | 4 | 49 ms | Constant |
| Transport enrollments, unpaged | 4,000 | 3 | 272 ms | Constant queries, unbounded rows |
| Transport dashboard | — | **87** | 148 ms | **One query per bus** |
| Transport buses | 80 | **84** | 117 ms | **One query per bus** |

## Findings

**F1 — `_bus_operational_warning` is one query per bus.** 81 of the 84 queries
listing buses, and 80 of the dashboard's 87. I previously dismissed this as
"bounded by the fleet" after measuring a 4-bus tenant. A 20-campus trust runs
80 buses, so the bound is 80 queries, not 2. Batchable the same way the rest of
transport was.

**F2 — `suggest_duplicates` degrades quadratically inside a bucket.**

| Data shape | People | Time |
|---|---|---|
| Realistic name variety, unique phones | 45,600 | **1.3 s** |
| Same, plus 6,027 people sharing one placeholder phone | 45,600 | **64 s** |

The scan buckets by name and phone, then compares every pair *within* a bucket.
With ordinary data that is fine. Migrated v1 data is not ordinary: schools
routinely enter one office number or `0000000000` for many students, which
creates a single enormous bucket. 6,027 sharing a number costs 64 seconds — a
request that times out.

Worth stating plainly: my first measurement of this said **199 seconds**, which
was wrong. My generated names all normalised to the same word, so every person
landed in one bucket. The number above is after fixing the data.

**F3 — unpaged reads remain the default.** `list_enrollments()` with no page
returns all 4,000 riders in 272 ms. Constant queries, but the payload grows with
the school, and three admin-web screens still call it that way for counts.

## Not found

No N+1 in students, teachers or paged transport at 15,000 students. The
eager-loading and page-reference work holds at scale.

---

# 7. Documentation Compliance

| ADR | Implemented? | Notes |
|---|---|---|
| 001 person-centric | **Yes** | One record per human; identity columns dropped from students/teachers |
| 002 family relationship model | **Yes** | Relationship is a value; households shared between siblings |
| 003 identity / auth separation | **Yes** | Authentication once, in `core/authentication.py` |
| 004 active context | **No — deliberately** | Nothing to switch to while households share a login (ADR-011). Correct to defer. |
| 005 teacher as participation of employment | **Yes** | `teachers.staff_id` NOT NULL; employment columns dropped |
| 006 business authority | **Partial** | Holder moved to employment. Capabilities / Business Actions / Authority Profiles not built; `has_permission` strings remain. |
| 007 admission vs academic enrollment | **Yes** | `student_class_enrollments` is the owner; `students.class_id` is a maintained cache, now ratified by ADR-014 |
| 008 teaching assignment | **Partial** | Class-teacher responsibility has an owner; subject teaching does not yet |
| 009 academic year as operational context | **Yes** | Year on enrollments, assignments, transport, fees |
| 010 incremental migration | **Yes** | Every cutover followed read → write → drop with equivalence proven on real data |
| 011 family access | **Yes** | Household shares the student's login |
| 012 academic reconciliation | **Partial** | Mapping honoured, `sections` table correctly never created; no owner module (AC1) |
| 013 authority belongs to the relationship | **Yes** | `staff_authorities`; ending employment ends authority |
| 014 teaching single ownership | **No — just decided** | Nothing implemented |

## Deviations

**One deviation, deliberate, documented:** the account→person consistency
listener was **relocated to Identity** rather than **retired**, against the
letter of milestone M3. Reason: retiring it means 75 creation sites each
repeating the same two lines, which is more places to forget rather than more
readable — the same argument that justifies the tenant-scope listener nobody
proposes removing. What was wrong was the module it lived in, and that is fixed.
Recorded in the foundation review.

**Recommendation:** amend M3 in the documentation to say *relocate*, not
*retire*. The implementation is right; the milestone wording is not.

---

# 8. Final Verdict

## Completed architectural capabilities

- **A person is recorded once**, and every path that learns something about them
  writes it there — including the bulk importers and self-service profile edits.
- **Households** with a named contact, expressible for single parents,
  grandparents and guardians alike.
- **Employment is the holder of authority.** Ending it ends authority, with no
  second flag to remember. Temporary delegation exists. `user_roles` is gone.
- **Domain boundaries are enforced by tests that read imports**, not by
  convention.
- **The migration chain runs on an empty database** — verified end to end, and
  previously it could not.
- **Campus isolation** across students, classes, attendance, fees, teachers,
  transport and hostel.
- **Scale holds** for students, teachers and paged transport at 15,000 students.

## Remaining architectural gaps

1. **Subject teaching has two owners** — ADR-014 decided, not implemented. *High.*
2. **No Teaching Assignment service** — every consumer reads tables. *High, and it is what prevents the next duplication.*
3. **Authorization vocabulary is still v1** — permission strings, not Business Actions. *Medium; mechanical to change, but every module written meanwhile uses the old vocabulary.*
4. **`suggest_duplicates` is unusable on migrated data with placeholder phones** — 64 s. *Medium-high; it will be hit the first time a real school is imported.*
5. **`_bus_operational_warning` is one query per bus** — 80 on a real fleet. *Low-medium.*
6. **No drift guards on the two permanent caches.** *Low, but cheap to fix.*
7. **Academic has no owner module** (AC1), and two live timetable implementations. *Medium, navigability.*
8. **Student family columns still dual-written**, blocked on the Expo client. *Known.*

## Recommended next milestone

**M6 — Teaching Assignment Ownership.** Implement ADR-014: introduce the
Teaching Assignment service, move the five reader modules onto it, remove
`is_class_teacher`, drop `class_teachers`, and add drift guards for the two
caches.

It is recommended before the Examination module for a specific reason:
**examinations attach to a class and to subject teaching**, and marks must be
attributable to whoever taught the subject *at the time*. ADR-014's historical /
current distinction is a prerequisite for a correct report card, not a
refinement of one. Building Examination first would bake today's ambiguity into
a new domain and make the eventual cleanup twice the size.

Recommended order after that: Authorization vocabulary (so new modules stop
accruing the old one), then Examination.
