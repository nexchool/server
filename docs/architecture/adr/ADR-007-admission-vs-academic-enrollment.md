# ADR-007 — Admission and Academic Enrollment Separation

## Status

Accepted

---

## Date

2026-08-04

---

# Context

Early versions of Nexchool treated student admission and academic participation as a single business process.

Typical implementations assumed:

```
Admission

↓

Student

↓

Grade

↓

Section
```

Under this approach, admitting a student immediately determined where the student participated academically.

As the product evolved, several real-world school scenarios exposed limitations.

Examples included:

- A student completes admission before the academic year begins.
- Section allocation is performed weeks after admission.
- Grade allocation changes before classes start.
- A student transfers between sections.
- A student repeats an academic year.
- A student temporarily pauses studies.
- A student graduates but remains part of the school's history.

These scenarios demonstrated that admission and academic participation solve different business problems.

---

# Decision

Nexchool separates Admission from Academic Enrollment.

Admission establishes that a Person becomes a Student of the school.

Academic Enrollment establishes where and how that Student participates during a particular Academic Year.

```
Person

        │

        ▼

Student Relationship

        │

        ▼

Admission

────────────────────────

Academic Enrollment

        │

        ▼

Academic Structure
```

These two concepts evolve independently.

---

# Rationale

Admission answers:

> Has this person become a student of this school?

Academic Enrollment answers:

> Where is this student studying during this Academic Year?

These questions have different lifecycles.

A student is admitted only once.

Academic Enrollment changes throughout the student's educational journey.

Separating these concepts more accurately reflects real-world school administration while simplifying long-term academic management.

---

# Alternatives Considered

## Option 1

Admission and Enrollment combined.

```
Admission

↓

Student

↓

Grade

↓

Section
```

### Advantages

- Simple implementation.
- Fewer business concepts.

### Disadvantages

- Difficult to model delayed admissions.
- Difficult to support transfers.
- Difficult to support repeated academic years.
- Couples student identity with academic participation.
- Poor long-term flexibility.

Decision:

Rejected.

---

## Option 2

Admission and Academic Enrollment separated.

```
Admission

↓

Student Relationship

↓

Academic Enrollment
```

### Advantages

- Independent business lifecycles.
- Cleaner academic history.
- Supports transfers.
- Supports promotions.
- Supports repeated academic years.
- Supports future academic workflows.

Decision:

Accepted.

---

# Consequences

## Positive

- Admission becomes a one-time business event.
- Academic participation evolves independently.
- Historical academic records remain accurate.
- Promotion becomes an enrollment change.
- Graduation preserves student history.
- Cleaner reporting across academic years.

---

## Trade-offs

Developers must distinguish between:

- Student Relationship
- Admission
- Academic Enrollment

Although additional concepts are introduced, each represents a distinct business responsibility.

---

# Admission

Admission establishes the Student relationship.

Example:

```
Person

↓

Student Relationship
```

Admission does not determine:

- Academic Year
- Grade
- Section
- Subjects
- Teaching Assignments

These decisions belong to Academic Enrollment.

---

# Academic Enrollment

Academic Enrollment connects a Student to the Academic Structure.

Examples include:

- Academic Year
- Academic Division
- Grade
- Section

```
Student

↓

Academic Enrollment

↓

Academic Structure
```

Enrollment represents the student's academic participation during a specific Academic Year.

---

# Promotion

Promotion modifies Academic Enrollment.

Example:

```
2026–2027

↓

Grade 8A

↓

Promotion

↓

2027–2028

↓

Grade 9A
```

Promotion never creates another Student.

Promotion never changes the Person.

Only Academic Enrollment changes.

---

# Section Transfer

Students may move between sections during the same Academic Year.

Example:

```
Academic Year

2026–2027

↓

Grade 8A

↓

Transfer

↓

Grade 8B
```

This changes Academic Enrollment only.

Admission remains unchanged.

---

# Repeat Academic Year

Students may repeat an Academic Year.

Example:

```
Academic Year

2026–2027

↓

Grade 8

↓

Repeat

↓

Academic Year

2027–2028

↓

Grade 8
```

The Student relationship remains unchanged.

Only Academic Enrollment changes.

---

# Graduation

Graduation completes Academic participation.

Example:

```
Student

↓

Graduated
```

Graduation does not remove:

- Person
- Student Relationship
- Admission History

Historical academic records remain available.

---

# Business Examples

## Student Admitted Before Classes Begin

```
Person

↓

Admission

↓

Student Relationship
```

Academic Enrollment is created later.

---

## Student Transfers Section

```
Academic Enrollment

↓

Section Changed
```

Admission remains unchanged.

---

## Student Graduates

```
Person

↓

Student

↓

Graduated
```

The student remains part of the school's historical records.

---

## Former Student Becomes Teacher

```
Person

↓

Student

↓

Graduated

↓

Staff

↓

Teacher
```

The Person remains the same throughout.

Academic participation evolves over time.

---

# Architectural Impact

Separating Admission from Academic Enrollment establishes independent business lifecycles for student identity and academic participation.

This decision enables:

- Accurate academic history.
- Promotion workflows.
- Section transfers.
- Academic year progression.
- Graduation.
- Student re-enrollment.
- Long-term reporting.
- Future academic modules.

Without this separation, every academic change would unnecessarily affect student identity.

---

# Related Documents

- people-domain.md
- academic-domain.md
- domain-interactions.md
