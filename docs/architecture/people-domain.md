# People Domain

> **Status:** Approved
>
> **Owner:** Product Architecture
>
> **Last Updated:** August 2026

---

# Purpose

The People Domain defines how Nexchool represents every real human being known to the school.

It establishes the foundation upon which every other business domain is built.

Rather than modelling teachers, students, parents, or staff as completely independent entities, the People Domain recognizes that a single individual may participate in multiple roles throughout their relationship with the school.

The purpose of this domain is to provide a single, consistent representation of each person while allowing multiple business relationships to coexist without duplication.

This document serves as the architectural source of truth for all person-related concepts throughout the platform.

---

# Domain Philosophy

Schools interact with people.

Not records.

Not accounts.

Not employees.

Not students.

People.

A person's relationship with the school may change over time, but the person remains the same.

For example:

- A parent may later become a teacher.
- A student may graduate and return as a staff member.
- A teacher may also be the parent of a student.
- A principal may have two children enrolled in the school.
- A guardian may never become a staff member.

These are not exceptional scenarios.

They are normal school operations.

The architecture should naturally support these scenarios instead of treating them as edge cases.

---

# Why This Domain Exists

The People Domain exists because schools maintain information about real individuals.

It does **not** exist because of Domain Driven Design, Object-Oriented Design, or generic enterprise modelling.

Its purpose is purely business-driven.

The school should never create duplicate records simply because one person performs multiple roles.

Every individual should have a single identity within the school's business records.

---

# Scope

The People Domain is responsible for:

- Representing every real person known to the school.
- Maintaining person identity information.
- Managing relationships between people and the school.
- Preventing duplication of person records.
- Providing a consistent reference for other business domains.

The People Domain is **not** responsible for:

- Authentication
- Authorization
- Teaching
- Academic assignments
- Payroll
- Attendance
- Examination
- Fee management

Those responsibilities belong to their respective domains.

---

# Core Concept

The People Domain revolves around a single business concept.

**Person**

A Person represents a real human being known to the school.

Nothing more.

Nothing less.

A Person is not defined by employment.

A Person is not defined by admission.

A Person is not defined by authentication.

A Person simply represents the individual.

---

# Person

Every person exists exactly once within the school.

Examples include:

- Teacher
- Student
- Parent
- Guardian
- Receptionist
- Principal
- Driver
- Accountant
- Librarian
- Visitor (if managed by the school)

The same individual should never be represented by multiple Person records.

---

# Business Relationships

A Person becomes meaningful through business relationships.

The school establishes relationships with people.

It does not create new people.

Examples of business relationships include:

- Staff
- Student
- Family Member

A Person may have:

- No relationships
- One relationship
- Multiple simultaneous relationships

Relationships may be created, updated, or removed independently throughout the person's lifecycle.

---

# Relationship Model

```
Person
    │
    ├── Staff
    │
    ├── Student
    │
    └── Family Member
```

The Person remains constant.

Relationships evolve.

---

# Staff Relationship

A Staff relationship represents employment between the school and a Person.

It contains employment-related information such as:

- Employee number
- Joining date
- Employment status
- Department
- Designation
- Employment history

Staff does **not** contain teaching-specific information.

Teaching belongs to the Academic Domain.

---

# Student Relationship

A Student relationship represents enrolment within the school.

It contains student-specific information such as:

- Admission number
- Admission date
- Academic status
- Enrollment information

A Student relationship does not own personal identity information.

Identity remains part of the Person.

---

# Family Member Relationship

A Family Member relationship represents a person's participation within a family associated with the school.

It allows the same person to participate in one or more families when business rules permit.

Family membership is relationship-based rather than assumption-based.

Examples of roles include:

- Father
- Mother
- Guardian
- Grandparent
- Relative

The architecture intentionally avoids hardcoding biological assumptions.

---

# Relationship Combinations

The architecture supports any valid combination of business relationships.

Examples include:

### Teacher who is also a parent

```
Person
    ├── Staff
    └── Family Member
```

---

### Principal with children studying in the school

```
Person
    ├── Staff
    └── Family Member
```

---

### Student

```
Person
    └── Student
```

---

### Student who later joins as teacher

```
Person
    ├── Student (Historical)
    └── Staff
```

---

### Receptionist who is also a parent

```
Person
    ├── Staff
    └── Family Member
```

---

### Guardian

```
Person
    └── Family Member
```

---

# Data Ownership

Person owns information that belongs to the human being.

Examples include:

- Full name
- Date of birth
- Gender
- Phone number
- Email
- Address
- Government identification
- Emergency contact

Business relationships must never duplicate this information.

---

# Single Source of Truth

Person information should exist only once.

Examples:

One phone number.

One address.

One email.

One Aadhaar.

One PAN.

One date of birth.

One emergency contact.

Every business relationship references the same Person.

Updating personal information automatically benefits every relationship.

---

# Identity Integration

Authentication is intentionally separated from business identity.

```
Person
    │
    └── User (Optional)
```

A Person may exist without a User account.

Examples include:

- Young students
- Parents without portal access
- Drivers
- Temporary workers
- Visitors

Likewise, authentication never determines who a person is within the business.

Business identity always comes first.

---

# Academic Integration

Teaching is not part of the People Domain.

Teaching belongs to the Academic Domain.

The Academic Domain extends the Staff relationship.

```
Person
    │
    └── Staff
            │
            └── Teacher
```

This separation keeps employment and academic responsibilities independent.

---

# Lifecycle

A Person may experience multiple transitions throughout their relationship with the school.

Examples include:

- Parent becomes teacher.
- Student graduates.
- Student joins as staff.
- Teacher resigns.
- Parent changes address.
- Guardian changes.
- Staff member retires.

These transitions should update business relationships rather than creating new Person records.

---

# Business Rules

The following principles apply throughout the platform.

## One Person

Every real individual should have exactly one Person record.

---

## Multiple Relationships

A Person may participate in multiple business relationships simultaneously.

---

## Relationship Independence

Relationships may evolve independently without affecting other relationships.

---

## No Duplication

Identity information should never be copied into relationship records.

---

## Business First

The architecture should represent real school operations before technical implementation concerns.

---

# Examples

## Example 1

Rahul Sharma teaches Mathematics.

His son studies in Grade 5.

```
Person

├── Staff
│     └── Teacher
│
├── Family Member
│
└── User
```

---

## Example 2

Ananya Patel is admitted as a student.

```
Person

├── Student
│
└── User (Optional)
```

---

## Example 3

Mr. Shah is the grandfather and legal guardian of a student.

```
Person

└── Family Member
```

---

## Example 4

Rakesh Patel graduated five years ago and later joined as a Physics teacher.

```
Person

├── Student (Historical)

└── Staff
      └── Teacher
```

---

# Non Goals

The People Domain does not attempt to model:

- Authentication
- Permissions
- Academic responsibilities
- Payroll
- Timetable
- Attendance
- Examination
- Fee collection

Those concerns belong to dedicated business domains.

---

# Future Evolution

The architecture intentionally supports future expansion without structural changes.

Potential future relationships include:

- Alumni
- Volunteer
- Consultant
- Medical Professional
- External Examiner
- Coach

These additions should introduce new business relationships rather than new person identities.

---

# Summary

The People Domain represents every real human known to the school.

It establishes a single source of truth for person identity while allowing multiple business relationships to coexist naturally.

This architecture eliminates duplication, reflects real-world school operations, and provides a stable foundation for every other business domain within Nexchool.