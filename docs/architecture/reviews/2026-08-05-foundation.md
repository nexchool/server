# Architecture Review — Foundation

> Date: 2026-08-05
> Scope: everything on `develop` since the v2 rebuild began (13 commits)
> Verdict: **foundation is not yet complete — do not begin client migration**

---

# Why This Review Exists

The architecture requires a review before client migration begins: every domain
walked, ownership confirmed, documentation checked against implementation, and
migration debt made visible with an exit. This is that review.

It is deliberately not a code review. It asks whether the *architecture* holds,
not whether the code is tidy.

---

# Domain Walk

## People

**Owns:** Person, Family, Family Member, Staff, Employment Period, Person Merge.

**Ownership: correct.** Person is the single record for a human. Staff is
employment. Family participation is a relationship value, not a column per role.
Nothing else creates these concepts.

**Boundary: clean.** People imports nothing from Academic or Identity. It reads
`modules.auth.models.User` in two places — the account-person guarantee and the
backfill — which is a dependency in the wrong direction (People should not know
Identity exists).

> **Finding P1 (medium).** People reads Identity. It is confined to the backfill
> and the consistency listener, both migration-era code, but it is a boundary
> violation and should not be copied into new People code.
>
> **Fixed 2026-08-05.** The listener moved to `modules/auth/person_link.py`:
> deciding that an account implies a person is a fact about *accounts*, and
> deriving a name from an email address is a rule about email addresses. People
> now offers `record_person(tenant_id, full_name, ...)`, which takes what it is
> told rather than an object to read it off. `merge.py` asks the person what
> they hold (`accounts`, `employments`, `student_relationships`) instead of
> importing three modules — Identity declares its backref onto Person like
> everyone else. Only the backfill still walks accounts, which is its job, and
> it takes the rule from Identity rather than keeping a copy. Enforced by
> `tests/test_people_knows_no_identity.py`, verified to fail on a violation.

**Documentation: incomplete.**

> **Finding P2 (medium).** There is no People module document. Students, staff,
> academics, attendance and identity all have one; the domain everything now
> depends on has only architecture docs and ADRs. A reader cannot find the
> workflows in one place.
>
> **Fixed 2026-08-05.** `docs/modules/people.md`, following the shape the other
> five use: what the module owns, what it deliberately does not, the rule that
> it depends on nothing, and the workflows — recording someone, correcting what
> is known, recognising a parent already recorded, households, employment. The
> match-key gap (same name, same role, different phone) is written down as a
> known gap rather than left to be rediscovered.

---

## Identity

**Owns:** User, Session, Active Context (designed, not yet stored), credentials.

**Ownership: correct.** Authentication is implemented once, in
`core/authentication.py`, and consumed by both transports.

**Boundary: one leak.** `available_contexts()` in the Identity module reads
`modules.students.models.Student`, `modules.teachers.models.Teacher` and
`modules.people.employment.Staff` directly to derive contexts.

> **Finding I1 (high).** Identity reads Academic. The architecture explicitly
> forbids this: "Identity should never know Academic". Contexts are derived from
> business relationships, so the derivation belongs behind a People/Academic
> service that answers "what relationships does this person hold?", with Identity
> only presenting the answer.

**Not yet built:** Active Context is designed (ADR-004) but nothing stores or
switches it. Correct for now — no second context exists to switch to while
households share a login (ADR-011).

---

## Authorization

**Not started.** Business Authority, Authority Profiles, Capabilities, Business
Actions and Scope exist only as documents. v1 RBAC — roles and permission
strings — is still the live implementation.

> **Finding A1 (high, sequencing).** Authorization is the third domain in the
> dependency order and it has not been touched. Every module built before it
> lands will be written against v1 RBAC and will need revisiting. This is the
> largest remaining foundation gap.

---

## Academic

**Owns:** Programme, Academic Year, Division, Grade, Section, Medium, Subject,
Teacher, Academic Enrollment, Teaching Assignment, Class Teacher.

**Ownership: correct but under a different vocabulary.** ADR-012 records the
binding mapping — most of the domain already existed in v1 tables, and a Section
is what the code calls a Class. Teacher is now correctly an academic
participation of Staff.

**Boundary: acceptable.** Academic does not import Identity. It shares tables
with modules that consume it, which is the pre-existing structure rather than
something introduced here.

> **Finding AC1 (medium).** Academic concepts are spread across `modules/classes`,
> `modules/academics`, `modules/grades`, `modules/mediums`,
> `modules/academic_programmes` and `modules/subjects` with no single owner
> module. Ownership is documented; it is not visible in the code layout.

---

# Duplicated Concepts

| Concept | Stored in | Status |
|---------|-----------|--------|
| Student identity (dob, gender, phone, address, Aadhaar) | `students.*` **and** `persons.*` | **Duplicated — written to both** |
| Parent / guardian details | `students.father_*`/`mother_*`/`guardian_*` **and** Family | **Duplicated — written to both** |
| Employment (employee number, designation, department, joining, status) | `teachers.*` **and** `staff.*` | **Duplicated — written to both** |
| Class teacher | `classes.teacher_id` **and** `class_teacher_assignments` | Pre-existing v1 duplication |

> **Finding D1 (high).** Three concepts are actively written to two places. This
> is migration debt, and it is currently unbounded: nothing fails, nothing warns,
> and the two copies can silently disagree. See *Migration Debt* below for the
> exit.

---

# Migration Debt Register

Every entry answers: why it exists, when it goes, and what removes it.

### 1. Dual-written identity, family and employment — **closed except family**

- **Why:** the API and three clients read the v1 columns. Writing only to the new
  model would break them; writing only to the old would abandon the new one.
- **Goes when:** serializers read from Person / Family / Staff while emitting the
  same JSON keys, and the clients write through the new model.
- **Removed by:** Milestone **M1 — Read Path Cutover**, then **M2 — Column Drop**.
- **Scope note, learned the hard way:** cutting a field over means moving the
  serializer, the **query layer** (filter, sort, search, facet) and **every
  writer** — single, bulk, import, self-service and platform. Moving only the
  serializer leaves the concept with two owners: a teacher displayed as inactive
  while the status filter still counted them active, and bulk-imported students
  showing blank details the school had just supplied. Both were found and fixed
  the same day (`9bc71a3`, `5018e21`).
- **Done 2026-08-05:** teacher payloads read the Person and the employment
  (verified identical for all 435); student identity reads the Person (identical
  for all 1,524). Both edit paths now reach People — until then the dual write
  was only a dual write on *create*, so every record drifted from the day it was
  edited. That was the unbounded part of this debt, and it is closed.
- **Closed 2026-08-05 (migration 090):** the identity and employment columns
  are dropped. No concept is written to two places any more except the family.
- **Still open — the student's family keys.** `father_*`, `mother_*` and
  `guardian_*` still read the v1 columns. This is not a like-for-like switch:
  where a school recorded the guardian's relationship as "father" there is one
  adult in the household, so the guardian keys empty and the father keys fill (5
  of 1,524 locally). And where two students share a household, a role lookup can
  return a different adult than the one that student's record named (2 of 1,524).
  Showing a parent the wrong name for a child is not a cosmetic regression, so
  this moves with the client work that teaches the UI to speak in household
  roles — **M2**, not before.

### 2. `students.person_id` alongside `students.user_id`

- **Why:** a student's human is reachable both directly and through the account,
  and nothing keeps them in agreement.
- **Goes when:** one path is chosen. **Corrected 2026-08-05:** the earlier answer
  here — resolve through the account — is backwards for a person-centric model.
  The account is a login, not the subject; ADR-011 already has a household
  sharing the student's credentials, so the person behind the account is not
  reliably the student. `students.person_id` is the truth, and nothing may
  derive a student's human from their login. At admission the two are the same
  human, which is why creation seeds one from the other; that is the only place
  it is legitimate.
- **Removed by:** Milestone **M1** — no reader outside creation now resolves a
  student's person through the account.

### 3. Consistency listener — **relocated, not retired**

- **Why:** accounts and student relationships are created from many places
  (services, two bulk importers, two seed scripts, test fixtures), and the NOT
  NULL constraints require every one of them to be correct.
- **Goes when:** account and student creation funnel through People services, so
  the link is set where a reader can see it.
- **Removed by:** Milestone **M3 — Creation Through Services**.
- **Note:** employment was removed from this listener on 2026-08-05 — creating
  employment is a business event and now lives in `employ()`. What remains is
  pure derivation with no business decision in it.
- **Revised 2026-08-05.** The plan said retire it. On inspection the listener's
  own argument is the right one: seventy-five creation sites each repeating the
  same two lines is not more readable than one rule, it is more places to
  forget — and the same argument already justifies the tenant scoping. What was
  actually wrong is that a rule about *accounts* lived in People, which is why
  People imported Identity. It now lives in `modules/auth/person_link.py`,
  registered in `app.py` rather than left to import order. Making the eleven
  production creation sites call an account service explicitly is still worth
  doing — the listener then guards test fixtures and anything missed — but it
  is no longer load-bearing.

### 4. v1 tables read by Identity to derive contexts

- **Why:** the Staff and Student relationships were only recently populated.
- **Goes when:** Finding I1 is fixed and derivation moves behind a service.
- **Removed by:** Milestone **M1**. **Done 2026-08-05:** `available_contexts`
  asks `people/relationships.py`; each owning module declares its relationship
  back onto Person or Staff, so People answers without importing Academic. The
  boundary has an import-level test.

### 5. Duplicate-suggestion scan loads every person

- **Why:** written for correctness first, on tenants of a few thousand people.
- **Goes when:** the model stabilises. Documented, not yet optimised, per the
  principle that architecture precedes optimisation.
- **Removed by:** Milestone **M4 — Scale Pass**.

### 6. Authority held by both the account and the employment — **CLOSED**

- **Why:** every reader and writer in the system asked `user_roles`; moving them
  in one commit would have been a blind cutover of the thing that decides who
  can do anything.
- **Went when:** readers, writers, bulk importers, platform and sub-admin
  services, scripts and fixtures had each been moved and proven equivalent
  across all 4,419 accounts.
- **Removed by:** migration 089, 2026-08-05. The move now happens on upgrade in
  every environment rather than depending on a script being run first.

---

# Shortcuts Taken

Honest list, including ones that were fixed.

1. **Employment created inside an ORM hook** — a business event hidden in a
   lifecycle callback. **Fixed** 2026-08-05: it is now `employ()`.
2. **`docs-new/` was never updated** despite the hook prompting on nearly every
   edit. The reasoning — that `docs-new/` documents v1 and the canon moved to
   `server/docs/` — was never stated or agreed. **Open: needs an explicit
   decision, not silence.**
3. **Merge has no API surface.** CLI only. Deliberate — there is no consumer —
   but it means the admin screen will need one built.
4. **One intermittent test error** in the departments suite, pre-dating this
   work, not reproducible across a dozen full runs. Not fixed, not claimed fixed.

---

# Milestones to Complete the Foundation

```
M1  Read Path Cutover                                    MOSTLY DONE
    serializers read Person / Family / Staff, same JSON keys
      teachers: done, all 435 identical
      student identity: done, all 1,524 identical
      student family keys: deferred to M2 with the client (see debt 1)
    Identity stops reading Academic (I1)                  done
    students.person_id is the single path                 done

M2  Column Drop                                          SERVER DONE
    v1 identity and employment columns removed (migration 090)
      students: date_of_birth, gender, phone, address, aadhar_number
      teachers: employee_id, designation, department_id, phone,
                address, date_of_joining, status
    parent/guardian columns remain — they move with the client

M3  Creation Through Services                            PARTLY DONE
    consistency listener moved to Identity (P1 closed)
    People offers record_person(); knows nothing of accounts
    boundary enforced by an import-level test
    remaining: 11 production sites call an account service explicitly

M4  Authorization Domain                                          DONE
    Business Authority replaces RBAC (A1)
    account-held roles retired, user_roles dropped

M5  Scale Pass                                           MOSTLY DONE
    every list endpoint measured against the demo tenant
    students 403->3, teachers 30->5 (audit)
    transport enrollments 493->4, buses 18->12, routes 9->3
    duplicate detection: recognition is household-aware
    transport lists paginate (opt-in; clients read arrays today)
    remaining: admin-web + Expo adopt the page, then the array goes

M5  Scale Pass (original scope)
    duplicate detection, N+1s, query counts
```

Client migration begins **after M2**. Modules beyond the foundation —
Attendance, Examination, Parent Portal — begin **after M4**, which is now
complete: authority is held by employment, and `user_roles` is gone
(migration 089).

---

# Verdict

The implementation follows the documented architecture rather than inventing its
own, and where documentation and reality disagreed the disagreements were
recorded as decisions (ADR-010, ADR-011, ADR-012) rather than resolved silently.

But the foundation is **not complete**:

- Authorization has not been started, and it is a foundation domain.
- Identity reads Academic, which the architecture forbids.
- Three business concepts are written to two places, unbounded.

Client migration should not begin. The next work is M1, and the next
architectural decision to take is A1 — Authorization — because everything built
before it will otherwise be written against a model that is being replaced.
