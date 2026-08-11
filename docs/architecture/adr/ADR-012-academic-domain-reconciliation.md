# ADR-012 — The Academic Domain Is Reconciled, Not Rebuilt

## Status

Accepted

---

## Date

2026-08-05

---

# Context

The Academic Domain documents describe Programme, Academic Year, Academic
Division, Grade, Section, Medium, Subject, Teacher, Academic Enrollment,
Teaching Assignment and Class Teacher. Read on their own they suggest a domain
waiting to be built.

Reading the v1 code shows otherwise. Almost all of it already exists, and in
places the implementation is better than the specification.

`class_subject_teachers` records which teacher teaches which subject to which
class, with effective dates, a primary/assistant role and a partial unique index
allowing exactly one active primary. That is the Teaching Assignment of ADR-008,
including the effective dating ADR-008 lists only as a future extension and the
teacher-changed-mid-year history it describes.

`student_class_enrollments` records a student in a class for an academic year,
with status, current-row marking, start and end dates, and
`promoted_from_enrollment_id`. That is the Academic Enrollment of ADR-007,
including the promotion chain.

`class_teacher_assignments` records the class teacher, again with roles and one
active primary per class.

The risk this creates is concrete. A reader who takes the domain documents
literally would create `sections`, `teaching_assignments` and
`academic_enrollments` tables beside the ones already doing that job, producing
exactly the duplicate ownership the architecture forbids — and doing it in the
name of following the architecture.

---

# Decision

The Academic Domain is **reconciled with the existing tables, not rebuilt on new
ones**.

The concepts in the domain documents map onto v1 tables as follows. These
mappings are binding: a new table must not be created for a concept that already
has one.

| Business concept | Table |
|------------------|-------|
| Programme | `academic_programmes` |
| Academic Year | `academic_years` |
| Academic Division | `departments` where `type = 'academic_division'` |
| Grade | `grades` |
| **Section** | **`classes`** |
| Medium | `mediums` |
| Subject | `subjects`, offered to a section through `class_subjects` |
| Academic Enrollment | `student_class_enrollments` |
| Teaching Assignment | `class_subject_teachers` |
| Class Teacher | `class_teacher_assignments` |

Where the implementation and the documents disagree, each difference is settled
deliberately rather than by assuming the documents are right.

---

# Section is what the code calls a Class

The domain documents call the group of students within a Grade a **Section**. The
code calls it a **Class**, and keeps `section` as the label on it — "A" in
"Class 8A".

Both words are real school vocabulary. A parent asks which class their child is
in; a teacher asks which section. Renaming `classes` across the schema, the API
and three clients would touch nearly everything and would be a mass rename of
working code, which is not something this project does.

So `classes` remains the table and Class remains the name in code and API.
Section stays the word the domain documents use for the concept, and this record
is the bridge between them. A `sections` table must never be created.

---

# Academic Year belongs to the organization, not to a Programme

`academic-management.md` stated that every Academic Year belongs to one
Programme. The implementation gives each organization its own academic years,
shared across programmes. The implementation is right.

A trust running CBSE and GSEB on one campus does not have two 2026–27s. It has
one academic year, in which each programme follows its own terms, examination
schedule and promotion rules. Making the year belong to a programme would force
that trust to maintain three identical-looking "2026–27" records and choose
between them on every screen, for no business gain.

Academic Year is therefore an organizational period. Programme-specific academic
configuration — terms, promotion rules, subject structure — attaches to the
combination of Programme and Academic Year. The documents have been corrected.

---

# The genuine gap: Teacher

One concept is materially different from its specification.

ADR-005 defines Teacher as an academic specialization of Staff: employment
belongs to the People Domain, academic participation to the Academic Domain, and
they evolve independently.

The v1 `teachers` table instead holds employment — employee number, designation,
department, joining date, employment status — alongside academic identity, and
links to a user account rather than to a person's employment.

Now that the Staff relationship owns employment (ADR-001), `teachers` becomes
what ADR-005 always described: the record that a member of staff participates in
teaching. It points at Staff, and its employment columns are dropped once
nothing reads them, following the additive sequence in ADR-010.

---

# Consequences

## Positive

- No duplicate tables are created for concepts that already exist.
- The academic modules already built on these tables keep working untouched.
- The remaining work is small and specific instead of a rewrite.
- The Class and Section vocabulary difference is recorded once instead of being
  rediscovered by everyone who reads the domain documents.

## Trade-offs

- The domain documents and the schema use different words for the same concept,
  and this record is what keeps them reconciled. It must be read alongside them.
- Some v1 tables carry columns the v2 model places elsewhere, until the cleanup
  migrations run.
- `classes.teacher_id` remains beside `class_teacher_assignments`. Its fate
  was settled later by ADR-014: it stays permanently as a performance cache,
  never a business owner, guarded against drift by test — it is no longer
  scheduled for removal.

---

# Related Documents

- academics/academic-domain.md
- academics/domain-ownership.md
- ADR-005-teacher-academic-participation.md
- ADR-007-admission-vs-academic-enrollment.md
- ADR-008-teaching-assignment.md
- ADR-010-incremental-v1-to-v2-migration.md
