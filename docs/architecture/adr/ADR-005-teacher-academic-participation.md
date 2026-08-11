# ADR-005 — Teacher as Academic Participation

## Status

Accepted

---

## Date

2026-08-04

---

# Context

The initial architecture modeled Teachers directly within the People Domain.

Typical structure:

```
People

├── Staff

├── Teacher

└── Student
```

Under this approach, Teacher represented both:

- Employment within the organization.
- Academic participation.

Initially this appeared straightforward.

However, as the product evolved, several business scenarios exposed limitations.

Examples included:

- Staff members who never teach.
- Teachers who later stop teaching but remain employed.
- Principals who continue teaching one subject.
- Visiting Faculty.
- Contract Teachers.
- Academic Coordinators who may or may not teach.

These scenarios demonstrated that employment and teaching represent different business concepts.

The architecture incorrectly combined two independent responsibilities.

---

# Decision

Teacher is no longer part of the People Domain.

Teacher belongs exclusively to the Academic Domain.

A Teacher is an academic specialization of an existing Staff member.

```
Person

        │

        ▼

Staff

        │

        ▼

Teacher
```

Teaching represents participation in academic activities.

Employment remains owned by the Staff relationship.

---

# Rationale

Schools employ Staff.

Schools conduct education through Teachers.

Although every Teacher must be a Staff member, not every Staff member participates in teaching.

Examples include:

- Receptionist
- Accountant
- Driver
- Librarian
- Office Administrator
- Maintenance Staff

These individuals are essential Staff members but do not participate in academic instruction.

Separating Staff from Teacher allows employment and academic participation to evolve independently while accurately reflecting real-world school operations.

---

# Alternatives Considered

## Option 1

Teacher as a People entity.

```
People

├── Staff

├── Teacher

└── Student
```

### Advantages

- Simple implementation.
- Fewer entities.

### Disadvantages

- Combines employment with academic participation.
- Difficult to model changing teaching responsibilities.
- Weak separation of concerns.
- Poor scalability.

Decision:

Rejected.

---

## Option 2

Teacher as a Designation.

```
Staff

↓

Designation

↓

Teacher
```

### Advantages

- Small data model.
- Easy implementation.

### Disadvantages

- Designation describes employment.
- Teaching describes academic participation.
- Unable to represent Staff members who temporarily stop teaching.
- Difficult to model future academic workflows.

Decision:

Rejected.

---

## Option 3

Teacher as an Academic specialization.

```
Person

↓

Staff

↓

Teacher
```

### Advantages

- Correct business separation.
- Independent employment lifecycle.
- Independent academic lifecycle.
- Supports future academic modules.
- Stable architecture.

Decision:

Accepted.

---

# Consequences

## Positive

- Employment remains independent.
- Academic participation becomes explicit.
- Supports future academic modules.
- Cleaner domain boundaries.
- Simplifies authorization.
- Supports organizational changes without affecting academic history.

---

## Trade-offs

Developers must distinguish between:

- Staff
- Teacher
- Designation
- Teaching Assignment

Although this introduces additional concepts, each represents a distinct business responsibility.

---

# Teaching Responsibilities

Teacher owns academic responsibilities including:

- Teaching Subjects
- Teaching Assignments
- Lesson Planning
- Student Evaluation
- Homework
- Attendance
- Examination
- Academic Guidance

These responsibilities belong exclusively to the Academic Domain.

---

# Staff Responsibilities

Staff owns organizational responsibilities including:

- Employment
- Joining Date
- Employment Status
- Payroll
- Contract Information
- Department Assignment
- Leave Management

Staff does not own teaching activities.

---

# Designation vs Teaching

Designation represents organizational employment.

Examples include:

- Teacher
- Principal
- Receptionist
- Accountant
- Driver

Teaching represents academic participation.

A Staff member with the Teacher designation becomes academically active only after participating within the Academic Domain.

Teaching should never be inferred solely from employment designation.

---

# Academic Participation

Academic participation begins after becoming a Teacher within the Academic Domain.

Teaching responsibilities are further organized through Teaching Assignments.

```
Person

↓

Staff

↓

Teacher

↓

Teaching Assignment
```

Teaching Assignment represents actual academic responsibility.

Teacher alone does not define what is being taught.

---

# Business Examples

## Receptionist

```
Person

↓

Staff

↓

Receptionist
```

No Teacher participation exists.

---

## Mathematics Teacher

```
Person

↓

Staff

↓

Teacher

↓

Teaching Assignment

↓

Mathematics

↓

Grade 8A
```

Academic participation is explicit.

---

## Principal Teaching Mathematics

```
Person

↓

Staff

↓

Principal

↓

Teacher

↓

Teaching Assignment
```

Employment and teaching remain independent.

---

## Visiting Faculty

```
Person

↓

Staff

↓

Visiting Status

↓

Teacher

↓

Teaching Assignment
```

Employment type does not affect academic participation.

---

## Teacher Stops Teaching

```
Person

↓

Staff

↓

Teacher

↓

Inactive Academic Participation
```

Employment continues.

Academic participation changes.

No employment information is lost.

---

# Architectural Impact

Moving Teacher into the Academic Domain establishes a clear separation between organizational employment and educational participation.

This decision enables:

- Teaching Assignments.
- Academic ownership.
- Independent employment lifecycle.
- Future academic modules.
- Cleaner authorization.
- Better reporting.
- Long-term maintainability.

Without this separation, employment concepts and academic concepts would continue becoming tightly coupled as the platform evolved.

---

# Related Documents

- people-domain.md
- academic-domain.md
- authorization-domain.md
- domain-interactions.md
