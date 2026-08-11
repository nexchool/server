# ADR-008 — Teaching Assignment as the Academic Responsibility

## Status

Accepted

---

## Date

2026-08-04

---

# Context

Early versions of Nexchool connected academic modules directly to Teachers.

Typical implementations followed relationships similar to:

```
Teacher

↓

Subject

↓

Grade

↓

Section
```

Every academic module recreated these same relationships independently.

Examples included:

- Attendance
- Homework
- Examination
- Lesson Planning
- Timetable
- Report Cards

Although each module solved its own business problem, they all required the same academic information.

This resulted in duplicated business logic and inconsistent academic relationships across modules.

---

# Decision

Nexchool introduces Teaching Assignment as a dedicated academic business concept.

Teaching Assignment represents the academic responsibility assigned to a Teacher during an Academic Year.

```
Teacher

        │

        ▼

Teaching Assignment

        │

        ▼

Academic Structure
```

Teaching Assignment becomes the shared academic reference used throughout the platform.

Academic modules reference Teaching Assignment rather than reconstructing teacher relationships independently.

---

# Rationale

Teaching is more than assigning a Teacher to a Subject.

A Teacher participates academically within a specific educational context.

That context includes:

- Academic Year
- Subject
- Grade
- Section

These concepts always appear together.

Rather than recreating these relationships throughout the system, Nexchool models them as a single business concept.

This establishes one source of truth for academic teaching responsibilities.

---

# Alternatives Considered

## Option 1

Direct Teacher references.

```
Attendance

↓

Teacher

↓

Subject

↓

Section

↓

Academic Year
```

### Advantages

- Simple implementation.
- Easy initial development.

### Disadvantages

- Repeated business logic.
- Duplicate relationships.
- Difficult maintenance.
- Inconsistent academic behavior.
- Every module recreates identical structures.

Decision:

Rejected.

---

## Option 2

Teaching Assignment.

```
Teacher

↓

Teaching Assignment

↓

Academic Structure
```

### Advantages

- Single source of truth.
- Shared academic responsibility.
- Cleaner module boundaries.
- Easier future expansion.
- Eliminates duplicated relationships.

Decision:

Accepted.

---

# Consequences

## Positive

- Academic modules become simpler.
- One teaching model for the entire platform.
- Reduced duplication.
- Consistent academic reporting.
- Easier long-term maintenance.
- Stable foundation for future academic modules.

---

## Trade-offs

Developers must understand that a Teacher does not directly teach a Section.

Teaching occurs through a Teaching Assignment.

Although this introduces another business concept, it significantly simplifies every academic module built upon it.

---

# Teaching Assignment

Teaching Assignment defines the academic responsibility of a Teacher.

It typically includes:

- Teacher
- Academic Year
- Subject
- Grade
- Section

Future extensions may also include:

- Teaching Load
- Classroom
- Timetable References
- Academic Calendar
- Curriculum
- Teaching Medium

Teaching Assignment owns the relationship between a Teacher and the Academic Structure.

---

# What Teaching Assignment Is Not

Teaching Assignment is not:

- Employment
- Designation
- Permission
- Timetable
- Lesson Plan
- Attendance Record
- Examination

These concepts belong to their respective domains or modules.

Teaching Assignment simply establishes academic responsibility.

---

# Module Integration

The following modules should reference Teaching Assignment.

Academic Modules

- Attendance
- Homework
- Examination
- Lesson Planning
- Timetable
- Report Cards
- Academic Analytics

AI Features

- AI Teacher Assistant
- Lesson Recommendations
- Student Performance Analysis

Future Modules

- Curriculum Planning
- Academic Insights
- Teacher Workload Analysis

Teaching Assignment should become the shared academic reference for every educational workflow.

---

# Business Examples

## Mathematics Teacher

```
Teacher

↓

Teaching Assignment

↓

Mathematics

↓

Grade 8A

↓

Academic Year
```

---

## One Teacher, Multiple Classes

```
Teacher

↓

Teaching Assignment

├── Grade 8A Mathematics

├── Grade 8B Mathematics

└── Grade 9A Mathematics
```

Each Teaching Assignment represents an independent academic responsibility.

---

## Multiple Teachers, One Subject

```
Mathematics

│

├── Grade 8A

│      ↓

│   Teacher A

│

└── Grade 8B

       ↓

    Teacher B
```

Each relationship is represented by its own Teaching Assignment.

---

## Teacher Changes During the Academic Year

```
Teaching Assignment

↓

Teacher Changed
```

Historical Attendance.

Homework.

Examinations.

Reports.

All remain associated with the Teaching Assignment active during that period.

Academic history remains accurate.

---

# Architectural Impact

Teaching Assignment becomes the shared academic contract between the Academic Domain and every academic module.

This decision enables:

- Consistent academic relationships.
- Shared academic references.
- Simpler module implementation.
- Stable reporting.
- Better AI context.
- Future analytics.
- Long-term scalability.

Without Teaching Assignment, every academic module would independently recreate teacher participation, leading to duplicated business logic and inconsistent architecture.

---

# Related Documents

- academic-domain.md
- people-domain.md
- authorization-domain.md
- domain-interactions.md
