# ADR-015 — A Document Belongs to the Person, Not the Relationship

## Status

Proposed — 2026-08-12

---

## Date

2026-08-12

---

# Context

Documents exist for students and nowhere else. `student_documents` carries a
foreign key to `students.id`, a student-shaped vocabulary (birth certificate,
leaving certificate, transfer certificate, Aadhar, passport, other), REST
routes under `/api/students/{id}/documents`, and the file itself in S3.

Teachers have nothing. The school collects their papers the same way it
collects a student's, and has nowhere to put them.

The obvious move is to copy the table across as `teacher_documents`. It is
symmetric with what exists and would take an afternoon. It is also the exact
shape the v2 rebuild spent its length removing: identity and employment were
lifted out of the student and teacher records precisely because a fact about a
human was being stored once per relationship the human happened to hold.

An Aadhar card is a fact about a person. It does not become a different
document because the person holding it teaches Standard 8 rather than studies
in it. Schools are small worlds — a teacher's child studies where the teacher
teaches, a former student returns as staff — and under `teacher_documents` that
person uploads the same Aadhar twice, into two tables, where the two copies can
disagree and neither is authoritative.

The canon already answers this. `docs/README.md`: *"Business concepts should
have exactly one owner… Person belongs to the People Domain. Modules consume
these concepts. They do not redefine them."* And: *"No duplicate business
concepts. If a business concept already exists within another domain,
reference it."*

What the canon does not do is say anything about documents at all. The word
appears in `people-domain.md` only as "this document". The concept was never
placed, which is why copying the table looked reasonable.

---

# Decision

**A document belongs to a Person.** One table, `person_documents`, keyed to
`persons.id`. The student profile and the teacher profile show the same
person's documents; they are two views, not two stores. `student_documents` is
migrated into it and dropped.

**The type vocabulary is data, tagged by context.** `document_types` rows,
seeded from a code catalogue in the manner of `modules/rbac/catalog.py`. Each
type declares the contexts it belongs to:

- `identity` — Aadhar, PAN, passport, birth certificate
- `student` — transfer certificate, leaving certificate
- `staff` — degree, experience letter, appointment letter, contract, police
  verification, medical fitness

A profile offers `identity` plus its own context. A school that needs a new
type gets a catalogue line and a reseed, not a migration and a deploy — the
"configuration, not forks" rule applied to paperwork.

**Completeness is a property of the person, counted in distinct types.** A
person is document-complete at two *different* types; two photographs of one
Aadhar are one type and do not satisfy it. The threshold is a named constant,
not tenant configuration, until a school asks for something else.

The signal is informational. It does not gate admission, activation,
employment, or anything else. It reports; it does not refuse.

**Metadata is business, file bytes are infrastructure.** Listing, the
catalogue, deletion and the completeness field are GraphQL. Multipart upload
and the authenticated file stream stay REST, which is what
`graphql-conventions.md` means by REST keeping infrastructure. The student
metadata routes GraphQL replaces are deleted; the student file route stays.

---

# Consequences

`student_leaves.document_id` references `student_documents.id`
(`modules/student_leaves/models.py:48`). The migration repoints it at
`person_documents.id` before the old table is dropped. This is the one place
where the change is not additive.

Every student has a person — migration `084_student_and_teacher_require_people`
made `students.person_id` NOT NULL — so the copy across has no orphan case and
needs no fallback.

Documents outlive the relationship that prompted them. A student who leaves
keeps their person record, and their documents go with it rather than being
cascaded away with a studentship. This is the behaviour the Preserve History
principle asks for, and it arrives as a side effect of getting the owner right.

The cost is a data migration on a table that already holds real files, in
exchange for a model where a person who is both a parent and a teacher uploads
their Aadhar once. A copy of the table would have been faster today and would
have been the thing the next rebuild had to undo.

`uploaded_by` records a person rather than an account, so the trail survives
an account being removed — consistent with migration `094_login_is_optional`,
where holding a relationship stopped requiring the ability to sign in.
