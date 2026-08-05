# Academic Domain

> **Status:** Approved
>
> **Owner:** Product Architecture
>
> **Last Updated:** August 2026

---

# Purpose

The Academic Domain defines how education is structured and delivered within Nexchool.

It provides the architectural foundation for every academic activity performed by a school.

Unlike the People Domain, which represents individuals, the Academic Domain represents the educational structure in which those individuals participate.

Every academic module within Nexchool depends on this domain.

Examples include:

- Student Enrollment
- Teacher Assignments
- Attendance
- Timetable
- Homework
- Examination
- Report Cards
- Academic Analytics
- AI Academic Assistance

This document establishes the business architecture upon which these modules are built.

---

# Domain Philosophy

A school exists to educate students.

Everything else supports that objective.

Teachers teach.

Students learn.

Subjects define what is taught.

Academic Years define when education occurs.

Grades and Sections organize students.

Assignments connect teachers with students.

The Academic Domain exists to model this educational structure as it operates within real schools.

Its responsibility is not to manage employment or authentication.

Its responsibility is to define how education is organized.

---

# Why This Domain Exists

The People Domain answers:

> Who is this person?

The Identity Domain answers:

> How does this person access the system?

The Academic Domain answers:

> How does this person participate in education?

These are fundamentally different questions.

A Staff member becomes a Teacher only by participating in academic activities.

A Student participates academically through enrollment.

Neither concept belongs within the People Domain.

---

# Responsibilities

The Academic Domain is responsible for:

- Academic Structure
- Academic Years
- Academic Divisions
- Grades
- Sections
- Subjects
- Teacher participation
- Student participation
- Academic Enrollment
- Teaching Assignments
- Class Teacher assignments
- Academic lifecycle

---

The Academic Domain is NOT responsible for:

- Authentication
- Person information
- Staff employment
- Family relationships
- Payroll
- Attendance records
- Timetable generation
- Examination records
- Homework
- Communication
- Notifications

Those responsibilities belong to dedicated domains or modules.

---

# Core Philosophy

Education is delivered through academic participation.

Academic participation requires structure.

Without structure there is:

- no teaching
- no classrooms
- no student grouping
- no academic progression

Therefore the Academic Domain is centered around the educational structure of the school rather than a single business entity.

Unlike the People Domain, this domain intentionally does not have a single root object.

Instead, it consists of several closely related business concepts that together represent the school's academic operations.

---

# Core Concepts

The Academic Domain consists of the following primary concepts.

- Academic Year
- Academic Structure
- Academic Division
- Grade
- Section
- Subject
- Teacher
- Student Enrollment
- Teaching Assignment

Each concept has a distinct business responsibility.

Together they define how education is delivered.

---

# Academic Structure

Academic Structure represents the organizational hierarchy through which education is delivered.

It is a business concept rather than a database entity.

Every academic activity occurs within this structure.

```
Academic Year

        │

        ▼

Academic Division

        │

        ▼

Grade

        │

        ▼

Section

        │

        ▼

Subjects
```

Modules such as Attendance, Timetable, Homework, Examination, and Analytics all depend upon this structure.

The Academic Structure serves as the common language shared by every academic module.

---

# Academic Year

The Academic Year represents the operational period during which the school conducts academic activities.

It acts as the temporal boundary for educational operations.

Every academic record should belong to an Academic Year.

Examples include:

- Student Enrollment
- Teaching Assignments
- Class Teacher Assignment
- Attendance
- Homework
- Timetable
- Examination
- Promotion
- Academic Reports

Historical data should remain associated with the Academic Year in which it occurred.

---

# Why Academic Year Matters

Schools continuously evolve.

Teachers change.

Students graduate.

Sections are reorganized.

Subjects change.

Without Academic Years, historical information becomes difficult to understand.

By explicitly associating academic records with an Academic Year, Nexchool preserves a complete academic history without duplicating data.

---

# Academic Year as Application Context

Academic Year is more than a reporting filter.

It represents the active academic context of the application.

Users interact with Nexchool within a selected Academic Year.

For example:

```
Current Academic Year

2026–2027
```

Changing the Academic Year changes the academic data displayed throughout the application.

Examples include:

- Student lists
- Sections
- Teaching Assignments
- Attendance
- Homework
- Examination
- Reports

This allows users to navigate historical academic data naturally without changing modules or URLs.

---

# Historical Access

Suppose a teacher wants to review a student who graduated several years ago.

Instead of searching archived systems, the user simply changes the active Academic Year.

Example:

```
Academic Year

2019–2020
```

The entire application automatically displays the academic information relevant to that year.

This approach provides consistent historical navigation across the platform.

---

# Academic Division

Academic Division represents the highest educational grouping within an Academic Year.

Examples include:

- Primary
- Upper Primary
- Secondary
- Higher Secondary

Academic Divisions organize grades according to the educational system followed by the school.

They should reflect educational structure rather than administrative departments.

---

# Academic Division vs Administrative Department

These concepts are intentionally different.

Academic Division exists to organize education.

Examples:

- Primary
- Secondary
- Higher Secondary

Administrative Departments organize school operations.

Examples:

- Accounts
- Administration
- Transport

Administrative Departments do not belong to the Academic Domain.

---

# Grade

A Grade represents a level of education within an Academic Division.

Examples include:

- Grade 1
- Grade 5
- Grade 8
- Grade 10
- Grade 12

Grades define academic progression.

They do not represent physical classrooms.

Students progress between Grades throughout their academic journey.

---

# Grade Responsibilities

A Grade defines:

- Curriculum level
- Subjects offered
- Academic progression
- Promotion path

A Grade does not define:

- Teachers
- Students
- Timetable
- Attendance

Those concepts depend upon the Grade but are not owned by it.

---

# Section

A Section represents an operational grouping of students within a Grade.

Examples include:

- Grade 8A
- Grade 8B
- Grade 8C

Sections exist to organize teaching and classroom management.

Teaching Assignments, Attendance, Timetables, Homework, and Examinations are all performed at the Section level.

---

# Section Responsibilities

A Section owns:

- Student grouping
- Teaching Assignments
- Class Teacher assignment
- Classroom identity

A Section does not own:

- Student identity
- Teacher employment
- Subject definitions

---

# Subject

A Subject represents an area of academic instruction delivered by the school.

Examples include:

- Mathematics
- Science
- English
- Gujarati
- Hindi
- Social Science
- Computer Science

Subjects belong entirely to the Academic Domain.

They define what students learn rather than who teaches it.

---

# Subject Responsibilities

Subjects define:

- Academic discipline
- Curriculum classification
- Teaching requirements

Subjects do not own:

- Teachers
- Students
- Timetable
- Homework
- Examination

These concepts reference Subjects but remain independent.

---

# Academic Structure Relationships

The relationship between core academic concepts is illustrated below.

```
Academic Year

        │

        ▼

Academic Division

        │

        ▼

Grade

        │

        ▼

Section

        │

        ▼

Teaching

Students

Subjects
```

Every academic module builds upon this hierarchy.

This hierarchy should remain stable throughout the lifetime of Nexchool.

---

# Domain Ownership

The Academic Domain owns:

- Academic Structure
- Academic Year
- Academic Division
- Grade
- Section
- Subject
- Student Participation
- Teacher Participation
- Academic Enrollment
- Teaching Assignments

The Academic Domain references:

- Person
- Staff
- Student Relationship

The Academic Domain never owns:

- Authentication
- Employment
- Person identity
- Permissions

Those responsibilities remain within their respective domains.

---

# Cross Domain Relationships

The Academic Domain depends upon the People Domain.

```
Person

        │

        ▼

Staff

        │

        ▼

Teacher

        │

        ▼

Teaching Assignment
```

Likewise,

```
Person

        │

        ▼

Student Relationship

        │

        ▼

Academic Enrollment
```

The Academic Domain never duplicates information already owned by the People Domain.

---

# Architectural Principles

The following principles define the Academic Domain.

## Education before Implementation

The architecture should represent how schools educate students rather than how software stores data.

---

## Academic Structure is Shared

Every academic module should rely upon the same Academic Structure.

No module should create its own interpretation of Grades, Sections, or Subjects.

---

## Historical Accuracy

Academic history should be preserved through Academic Years rather than duplicated records.

---

## Separation of Concerns

Employment belongs to the People Domain.

Authentication belongs to the Identity Domain.

Education belongs to the Academic Domain.

---

## Single Source of Truth

Academic concepts should exist only once within the platform.

Grades, Sections, Subjects, and Academic Years should never be duplicated between modules.

---

# Summary

The Academic Domain defines how education is structured within Nexchool.

Rather than focusing on a single entity, it establishes the complete academic framework through which teachers educate students.

Academic Years provide historical boundaries.

Academic Divisions organize educational stages.

Grades define progression.

Sections organize classrooms.

Subjects define instruction.

Together these concepts form the Academic Structure that every academic module within Nexchool depends upon.

This shared foundation ensures consistency, scalability, and long-term maintainability as the platform evolves.

