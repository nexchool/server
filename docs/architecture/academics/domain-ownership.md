# Domain Ownership

The Academic Domain owns the concepts that define how education is structured and delivered within the school.

Specifically, it owns:

- Academic Year
- Academic Structure
- Academic Division
- Grade
- Section
- Subject
- Teacher
- Student Academic Participation
- Academic Enrollment
- Teaching Assignment
- Class Teacher
- Promotion
- Graduation

The Academic Domain is the authoritative source for these concepts.

Other domains and modules may reference them but must never duplicate or redefine them.

---

# Cross Domain Relationships

The Academic Domain collaborates with other business domains while maintaining clear ownership boundaries.

## People Domain

The People Domain provides the individuals who participate in education.

```
Person

├── Staff
│     │
│     ▼
│   Teacher
│
└── Student Relationship
```

The Academic Domain never creates or modifies Person records.

---

## Identity Domain

The Identity Domain authenticates Users.

Authentication is independent of academic participation.

Teachers and Students continue to exist academically even if they never receive a User account.

The Academic Domain never depends on authentication to determine academic participation.

---

## Permissions Domain

Permissions determine what a User may perform inside academic modules.

Examples include:

- Record Attendance
- Publish Homework
- Schedule Examination
- View Academic Reports

The Academic Domain defines academic responsibilities.

The Permissions Domain controls access to those responsibilities.

---

## Communication Module

The Communication Module communicates with People.

It may use academic information to identify recipients.

Examples include:

- Students of Grade 8A
- Parents of Grade 10
- Mathematics Teachers

Communication never owns academic concepts.

---

## Examination Module

The Examination Module depends upon the Academic Domain.

It uses:

- Academic Year
- Grade
- Section
- Subject
- Teaching Assignment
- Academic Enrollment

The Examination Module owns examination workflows.

It does not redefine academic structure.

---

## Attendance Module

Attendance depends upon the Academic Domain.

It references:

- Academic Enrollment
- Teaching Assignment
- Academic Year

Attendance owns attendance records.

The Academic Domain owns academic participation.

---

## Timetable Module

The Timetable Module references:

- Teacher
- Subject
- Section
- Academic Year
- Teaching Assignment

Timetable owns scheduling.

Academic owns educational structure.

---

# Module Dependencies

The following modules depend directly upon the Academic Domain.

Core Academic Modules

- Attendance
- Timetable
- Homework
- Examination
- Lesson Planning
- Report Cards
- Academic Analytics

Supporting Modules

- Communication
- AI Assistant
- Transport
- Hostel
- Library

These modules consume academic information.

They do not redefine it.

---

# Academic Status

Academic participation changes throughout a student's educational journey.

The Academic Domain owns these lifecycle concepts.

## Student Status

Typical business states include:

- Active
- Inactive
- Suspended
- Graduated
- Transferred

These represent the student's long-term relationship with the school.

---

## Academic Enrollment Status

Enrollment has its own independent lifecycle.

Examples include:

- Pending
- Active
- Completed
- Cancelled

Enrollment status describes participation within a specific Academic Year.

It does not modify the Student relationship.

---

# Architectural Principles

The following principles define the Academic Domain.

## Education before Technology

The Academic Domain should model how schools educate students rather than how software stores information.

Business operations always determine architecture.

---

## Academic Structure is the Foundation

Every academic module must depend upon the shared Academic Structure.

No module should introduce its own interpretation of:

- Grades
- Sections
- Subjects
- Academic Years

---

## One Academic Structure

The school should have one consistent academic structure.

Attendance.

Timetable.

Homework.

Examinations.

Reports.

AI.

Every module references the same academic hierarchy.

---

## Academic Year is Mandatory

Every academic operation occurs within an Academic Year.

Academic Year is never optional.

Historical records should always remain associated with the Academic Year in which they occurred.

---

## Participation is Independent

Admission.

Academic Enrollment.

Teaching Assignment.

Promotion.

Graduation.

These are independent business concepts.

Each has its own lifecycle.

---

## No Duplication

Academic concepts should exist only once.

Grades.

Sections.

Subjects.

Academic Years.

Teaching Assignments.

Academic Enrollments.

Every module should reference these concepts rather than recreating them.

---

# Common Scenarios

The architecture naturally supports common school operations.

## Teacher teaches multiple Sections.

```
Teacher

↓

Teaching Assignments

├── Grade 8A Mathematics

├── Grade 8B Mathematics

└── Grade 9A Mathematics
```

---

## Student promoted.

```
Academic Year

2026–2027

↓

Grade 8A

↓

Promotion

↓

Academic Year

2027–2028

↓

Grade 9A
```

---

## Student repeats an Academic Year.

The Student relationship remains unchanged.

A new Academic Enrollment is created.

---

## Student changes Section.

Only the Academic Enrollment changes.

The Student relationship remains unchanged.

---

## Teacher becomes Class Teacher.

A new academic responsibility is assigned.

Employment information remains unchanged.

---

## Visiting Teacher joins the school.

The individual becomes:

Person

↓

Staff

↓

Teacher

Academic participation remains identical regardless of employment type.

---

## Student graduates.

The Student relationship remains.

Student Status becomes:

```
Graduated
```

Historical Academic Enrollments remain available.

---

# Future Evolution

The Academic Domain is designed to evolve without architectural restructuring.

Future capabilities may include:

- Multiple Campuses
- Multiple Curricula
- Elective Subjects
- Clubs
- Academic Houses
- Learning Paths
- Skill-based Education
- AI Learning Recommendations

These features should extend the Academic Structure rather than replacing it.

The core concepts defined within this document should remain stable.

---

# Non Goals

The Academic Domain intentionally does not model:

- Authentication
- Authorization
- Employment
- Payroll
- Finance
- Inventory
- Communication workflows
- Attendance records
- Examination workflows
- Homework workflows
- Timetable generation
- AI implementation

These concerns belong to their respective domains and modules.

---

# Summary

The Academic Domain defines how education is organized and delivered within Nexchool.

It establishes a shared Academic Structure that every educational activity depends upon.

Teachers participate through Teaching Assignments.

Students participate through Academic Enrollment.

Academic Years preserve historical continuity.

Promotion and Graduation manage academic progression.

Every academic module—including Attendance, Timetable, Homework, Examination, Report Cards, Analytics, and AI—builds upon the concepts defined by this domain rather than redefining them independently.

By separating academic participation from employment, authentication, and personal identity, Nexchool models school operations in a way that is both business-correct and architecturally sustainable for long-term growth.