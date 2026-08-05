# People

## Purpose

The People module holds the humans a school deals with, once each.

A school does not deal with "a student record" and "a parent record" and "an
employee record" — it deals with people, who happen to be those things. The
same woman may teach Std 7, be the mother of a child in Std 2, and be the
person the office rings when a bus is late. Recorded three times, she has three
phone numbers that disagree, and correcting one corrects nothing.

This module is where a human is written down. Everything a person *is to the
school* — a student, an employee, a parent — is a relationship recorded by the
module that owns it, pointing back here.

It is the module every other module depends on, which is why it depends on
none.

---

# Business Responsibilities

The People module is responsible for:

- Recording a Person
- Correcting what is known about a Person
- Recognising a Person already recorded
- Merging two records of the same human
- Recording a Household
- Naming the adult the school should call
- Recording Employment
- Recording an Employment Period
- Answering what relationships a Person holds

---

# Module Ownership

## Person

One human. Carries only what is true of the human themselves — their name,
date of birth, gender, how to reach them, their Aadhaar number, their
photograph.

It carries nothing about what they do here. A teacher's designation is a fact
about their employment, not about them; a student's roll number is a fact about
their studentship. Those live with the relationships that own them.

## Family

A household. It has no name and no head — it is simply the group of people a
school treats as belonging together, so that a father recorded for one child is
the same father when his second child is admitted.

## Family Member

How one Person participates in one Family: father, mother, guardian,
grandmother, uncle, brother, sister, child.

The relationship is a **value, not a column per role** (ADR-002). A school with
a child raised by their grandmother, or by a court-appointed guardian, or by
one parent, records all of them the same way. A schema with `father_name` and
`mother_name` columns cannot.

One member of each household is the **primary contact** — the adult the school
rings first. This is a separate fact from being the father: it is what lets a
household hold both parents and still say which one to call.

## Staff

That a Person is employed by the organization. Created once per person: someone
who already works here and starts teaching keeps the employment they had.

Carries the employee number, designation, department, employment status and
employment type.

## Staff Employment Period

One continuous stretch of employment. Somebody who resigns and is later
re-appointed has two — which is why "date of joining" means the first of them,
and why a re-appointment is a business event rather than an edited field.

## Person Merge

The record of two records having been recognised as one human, and what was
combined. Merging is not deletion: the school must be able to see afterwards
what happened.

---

# What This Module Does NOT Own

- **Sign-in, accounts, sessions, passwords** — Identity Management. A person
  may have no account at all and still be fully recorded here.
- **What a person may do** — the Authorization Domain. Authority is held by
  employment, not by a person and not by a login (ADR-013).
- **Studentship** — Student Management: admission number, class, roll number,
  house, previous school.
- **Teaching** — Staff/Academic Management: subjects, qualifications,
  timetable. Teaching is an academic participation of an employment (ADR-005),
  not a kind of person.

---

# Dependencies

**People depends on nothing.**

That is a rule, not an observation. Every other domain depends on People, so a
dependency in the other direction would be a cycle through the middle of the
system.

It follows that People never imports Identity or Academic. When it needs to
know whether a person signs in, works here or studies here, it reads the
relationship that module has declared **back onto Person** — `accounts`,
`employments`, `student_relationships`, `family_memberships`. Each owning
module declares its own; People reads what has been declared.

Enforced by `tests/test_people_knows_no_identity.py`, which reads imports
rather than behaviour, because a boundary tested only by what the code happens
to do today is not a boundary.

---

# Recording a Person

A person is recorded by whoever first learns of them:

| The school does this | And a Person is recorded for |
|---|---|
| Opens an account | The account holder |
| Admits a student | The student |
| Names a parent on the admission form | That parent |
| Appoints a member of staff | The employee |

An account always belongs to a person. That rule is enforced in one place —
Identity, since it is a fact about accounts — rather than asked of the dozen
places that open accounts.

Only what the informer actually knows is recorded. A student's date of birth is
not invented at account creation; it is filled in by admission, which is where
the school learns it.

---

# Correcting what is known

Two different things arrive through the same form, and they are not the same:

**Discovering** a fact nobody had recorded fills a blank and never overwrites.
Admission learning a phone number the account never had is a discovery.

**Correcting** a fact says the one on record is wrong, and overwrites it — but
only the fields it was given. A form that omits a field is silent about it, not
clearing it.

Because a person is held once, correcting a father's phone number corrects it
for **every one of his children**. That is the point of holding people once,
and it is what a school expects: they fixed it, once.

Changing a *name* is a different statement. The household's membership moves to
the new person rather than renaming the one on record, who may have other
children whose records must not silently change.

---

# Recognising someone already recorded

A parent enrolling a second child must not become a second person.

Recognition uses the rules of ADR-010: the database narrows the candidates by
role and by the stable part of a phone number, and a match key decides. Two
adults with the same name in the same role are the same human if the evidence
says so, and different humans if it does not.

A household is checked first, and on the name alone. Naming the father of a
child who already has a father of that name is correcting his details or
repeating them — not introducing a second father — so a retyped phone number
must not split him in two. Only within the one household: two families may each
have a Rajesh Patel, and they are different men.

---

# Households

The school records who is responsible for a child at admission, not later by a
migration. A sibling admitted afterwards finds the adult already recorded and
joins the household holding them — which is how two children come to share one
father rather than one each.

A household submitted by a form is submitted **whole**: an adult it no longer
lists has left the household. The Person survives that. They may still be a
parent in another family, and forgetting a human because one form stopped
mentioning them would be wrong.

---

# Employment

Employing somebody is a business event, so it is an explicit action —
`employ()` — and deliberately *not* an ORM hook. An ORM hook is the wrong place
for a reader to learn that the organization hired someone.

Employment status says what actually happened: working, on probation, on leave,
serving notice, suspended, resigned, retired, terminated. Records migrated from
systems that stored only "active" carry `left`, which says exactly what is
known — they have gone, and the reason was never recorded.

Being employed and being able to act are different questions. A suspended
employee is still employed and keeps their record, but holds no authority while
suspended. Someone on maternity leave is absent, not distrusted, and keeps
theirs.

---

# Business Rules

## One human, one record.

The same person is recorded once, however many relationships they hold with the
school.

## A Person may hold any number of relationships, or none.

A parent with no account and no employment is fully recorded.

## A Person is never deleted while anything points at them.

Merging retires a duplicate and writes down what was combined. Deletion would
destroy history the school may need.

## Employment is created once per person.

Leaving and returning opens a new period against the same employment, so the
history reads as it happened.

## A household has one primary contact, not several.

Naming a new one stands the previous one down.

## A relationship is a value, not a column.

Adding "step-father" or "legal guardian" is data, never a schema change and
never a code branch.

## People depends on nothing.

If People needs to import another module to answer a question, the question is
being asked in the wrong direction.

---

# Related Documents

- `docs/architecture/adr/` — ADR-001 (a person is recorded once), ADR-002
  (relationship as a value), ADR-005 (teaching is a participation of
  employment), ADR-010 (incremental migration — carries the rules for recognising the same human), ADR-013 (authority is held
  by employment)
- `docs/modules/identity-management.md` — accounts, sessions, active context
- `docs/modules/staff-management.md` — what employment is used for
- `docs/modules/student-management.md` — studentship
- `docs/architecture/reviews/2026-08-05-foundation.md` — migration debt and its
  removal milestones
