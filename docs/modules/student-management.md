# Student Management

## Purpose

The Student Management module manages the complete lifecycle of students within Nexchool.

It provides the business workflows required to admit, enroll, promote, transfer, withdraw, graduate, and maintain students throughout their relationship with the school.

Student Management does not redefine business concepts owned by the core architecture.

Instead, it orchestrates those concepts into workflows that reflect how schools actually manage students.

This module serves as the operational layer between the school's administrative processes and the underlying business domains.

---

# Business Responsibilities

The Student Management module is responsible for:

- Student Admission
- Student Profile Management
- Student Search
- Academic Enrollment
- Student Promotion
- Section Transfer
- Student Withdrawal
- Student Graduation
- Student Re-enrollment
- Student Timeline
- Student History

These responsibilities represent complete business workflows rather than individual database operations.

---

# Business Scope

Student Management begins when a prospective student applies to the school.

Its responsibility continues throughout the student's relationship with the organization.

Typical lifecycle:

```
Admission

↓

Student

↓

Academic Enrollment

↓

Promotion

↓

Transfer

↓

Graduation

↓

Alumni
```

The module supports the complete educational journey while preserving historical records at every stage.

---

# Module Ownership

The Student Management module owns the following business workflows.

## Admission

Managing the process through which a Person becomes a Student of the school.

---

## Student Profile

Managing student-specific information that evolves after admission.

---

## Student Search

Providing consistent mechanisms to locate students across Academic Years.

---

## Promotion

Managing academic progression between Academic Years.

---

## Section Transfer

Managing movement between Sections within the same Academic Year.

---

## Withdrawal

Managing students who leave before completing their education.

---

## Graduation

Managing successful completion of education.

---

## Student Timeline

Maintaining a chronological history of important student events throughout their journey.

---

# What This Module Does NOT Own

The Student Management module intentionally does not own several core business concepts.

These concepts already belong to architecture domains.

| Business Concept | Owner |
|------------------|-------|
| Person | People Domain |
| Student Relationship | People Domain |
| Family | People Domain |
| User | Identity Domain |
| Authentication | Identity Domain |
| Authorization | Authorization Domain |
| Academic Enrollment | Academic Domain |
| Academic Year | Academic Domain |
| Teaching Assignment | Academic Domain |

Student Management references these concepts but never redefines them.

---

# Dependencies

Student Management depends upon several architecture domains.

## People Domain

Provides:

- Person
- Student Relationship
- Family
- Family Members

---

## Identity Domain

Provides:

- User (Optional)
- Authentication
- Active Context

Student Management never authenticates users.

---

## Authorization Domain

Provides:

- Business Authority
- Authorization Decisions

Student Management requests authorization before executing business workflows.

---

## Academic Domain

Provides:

- Academic Year
- Academic Enrollment
- Academic Structure

Student Management orchestrates academic participation without owning academic concepts.

---

# Integration Matrix

| Domain / Module | Purpose |
|-----------------|---------|
| People | Person and Family information |
| Identity | Optional User access |
| Authorization | Business Authority evaluation |
| Academic | Academic Enrollment and Academic Structure |
| Communication | Admission notifications and parent communication |
| Finance | Fee assignment after admission |
| Transport | Route allocation |
| Examination | Student assessment |
| Attendance | Student attendance |
| AI | Student insights and academic recommendations |

Student Management acts as the central business workflow while collaborating with other modules through shared business concepts.

---

# Student Lifecycle

Every student follows a well-defined business lifecycle.

```
Prospective Student

        │

        ▼

Admission

        │

        ▼

Student Relationship

        │

        ▼

Academic Enrollment

        │

        ▼

Promotion

        │

        ▼

Promotion

        │

        ▼

Graduation

        │

        ▼

Alumni
```

Not every student follows the same path.

Some students may:

- Transfer
- Withdraw
- Repeat an Academic Year
- Re-enroll after withdrawal

The lifecycle supports these variations while preserving complete historical records.

---

# Student Status

Student status represents the student's current business state.

Suggested statuses include:

- Prospective
- Admission In Progress
- Admitted
- Enrolled
- Active
- Withdrawn
- Graduated
- Alumni

Each status represents a business milestone rather than a technical state.

Note: Prospective and Admission In Progress belong to the Admission workflow — the Student relationship does not exist yet at those stages. From Admitted onward, statuses map onto the Academic Domain's canonical Student states (Active, Suspended, Withdrawn, Transferred, Graduated).

Status changes should occur only through business workflows defined by this module.

---

# Student Information

Student Management is responsible for managing student-specific information.

Examples include:

- Admission Number
- Roll Number
- Date of Admission
- Previous School
- Admission Category
- Current Status

Personal identity information such as:

- Name
- Date of Birth
- Gender
- Contact Information
- Address

belongs to the Person within the People Domain.

Student Management references that information rather than owning it.

---

# Student Relationships

Every Student originates from a Person.

```
Person

        │

        ▼

Student Relationship

        │

        ▼

Student Management
```

A Student also participates within one or more Families.

```
Family

        │

        ▼

Family Member

        │

        ▼

Student
```

Student Management references these relationships when performing business workflows such as admissions, transfers, communication, and fee assignment.

---

# Business Principles

The Student Management module follows these principles.

## One Person

A student is always represented by one Person.

Duplicate student identities should never exist.

---

## One Student Relationship

Admission creates the Student relationship only once.

Subsequent academic progression should never create another Student.

---

## Academic Participation

Academic participation occurs through Academic Enrollment.

Student Management should never redefine academic structures.

---

## Preserve History

Historical student information should never be overwritten.

Every significant lifecycle event should remain traceable.

---

## Business Before Technology

Student workflows should reflect real school operations.

Implementation details should never influence business behavior.

---

# Summary

Student Management is responsible for orchestrating the complete lifecycle of students within Nexchool.

It owns business workflows such as admission, promotion, transfer, withdrawal, graduation, and student history while relying on the core architecture domains for identity, academic participation, authorization, and business relationships.

By separating workflows from foundational business concepts, the module remains aligned with Nexchool's business-first architecture while providing a stable foundation for every future module that interacts with students.

# Admission

Admission is the business workflow through which a Person becomes a Student of the school.

Admission is a one-time business event.

Successful admission establishes the Student relationship.

Admission does not determine academic participation.

```
Person

        │

        ▼

Admission

        │

        ▼

Student Relationship
```

Academic participation begins later through Academic Enrollment.

---

# Admission Objectives

The Admission workflow is responsible for:

- Registering a prospective student.
- Verifying required information.
- Collecting admission details.
- Creating the Student relationship.
- Preparing the student for Academic Enrollment.

Admission should never:

- Allocate Grade.
- Allocate Section.
- Assign Subjects.
- Create Teaching Assignments.

These belong to the Academic Domain.

---

# Admission Lifecycle

The admission process follows the lifecycle below.

```
Prospective Student

↓

Admission Application

↓

Verification

↓

Admission Approved

↓

Student Relationship Created

↓

Ready for Academic Enrollment
```

Each stage represents a business milestone.

---

# Admission Cancellation

Schools may cancel an admission before the Student relationship is created.

Examples include:

- Parent withdraws application.
- Required documents not submitted.
- Admission rejected.
- Student joins another school.

Cancelled admissions should remain visible in admission history for auditing purposes.

No Student relationship should be created.

---

# Academic Enrollment

Academic Enrollment determines where the admitted Student participates academically.

```
Student

↓

Academic Enrollment

↓

Academic Structure
```

Student Management initiates Academic Enrollment.

The Academic Domain owns Academic Enrollment.

---

# Initial Enrollment

Initial Enrollment generally includes:

- Academic Year
- Academic Division
- Grade
- Section

After Academic Enrollment, the student becomes academically active.

---

# Enrollment Lifecycle

A Student may have multiple Academic Enrollments throughout their educational journey.

Example:

```
2026–2027

↓

Grade 6A

↓

Promotion

↓

2027–2028

↓

Grade 7A

↓

Promotion

↓

2028–2029

↓

Grade 8B
```

Each Academic Enrollment represents one Academic Year.

Historical enrollments remain immutable.

---

# Promotion

Promotion advances a Student from one Academic Enrollment to the next.

Promotion never creates another Student.

```
Student

↓

Academic Enrollment

↓

Promotion

↓

Academic Enrollment
```

Promotion should preserve:

- Student identity.
- Admission information.
- Historical academic records.

Only academic participation changes.

---

# Promotion Outcomes

Promotion may result in:

- Promotion to next Grade.
- Promotion with Section change.
- Repeat Academic Year.

Each outcome creates the appropriate Academic Enrollment for the next Academic Year.

---

# Section Transfer

Students may transfer between Sections within the same Academic Year.

Example:

```
Grade 8A

↓

Transfer

↓

Grade 8B
```

Section Transfer updates Academic Enrollment.

Promotion is unaffected.

Student identity remains unchanged.

---

# School Transfer

A Student may leave the school before graduation.

Examples include:

- Family relocation.
- Transfer to another school.
- Personal reasons.

School Transfer ends the student's active participation within the organization.

Historical records remain available.

The Student relationship remains preserved.

---

# Withdrawal

Withdrawal represents students who discontinue education before graduation.

Examples include:

- Family relocation.
- Financial reasons.
- Personal circumstances.
- Long-term absence.

Withdrawal changes the student's operational status.

Historical records remain intact.

Withdrawal should never delete student information.

---

# Re-enrollment

A withdrawn Student may later return to the school.

Example:

```
Student

↓

Withdrawn

↓

Re-enrollment

↓

Academic Enrollment
```

The original Person.

The original Student relationship.

The original Admission history.

All remain unchanged.

Re-enrollment simply creates a new Academic Enrollment.

---

# Graduation

Graduation represents successful completion of the student's educational journey.

Example:

```
Student

↓

Graduated

↓

Alumni
```

Graduation ends active Academic Enrollment.

It does not remove:

- Person
- Student Relationship
- Admission History
- Academic History

Graduated students remain searchable.

---

# Academic History

Every Academic Enrollment contributes to the student's academic history.

History should preserve:

- Academic Year
- Grade
- Section
- Promotion History
- Transfer History
- Attendance
- Examination Results
- Report Cards

Historical records should never be modified after completion.

---

# Student Timeline

Student Management maintains a chronological timeline of significant lifecycle events.

Examples include:

- Admission Submitted
- Admission Approved
- Academic Enrollment
- Promotion
- Section Transfer
- Withdrawal
- Re-enrollment
- Graduation

The timeline provides a complete business history throughout the student's relationship with the school.

---

# Business Rules

The Student Management module follows these workflow rules.

## Admission occurs once.

Admission establishes the Student relationship.

It should never be repeated.

---

## Academic Enrollment may occur many times.

Each Academic Year creates a new Academic Enrollment.

---

## Promotion creates a new Academic Enrollment.

Promotion never creates another Student.

---

## Section Transfer modifies the current Academic Enrollment.

It does not affect previous Academic Years.

---

## Withdrawal preserves history.

Historical records remain searchable.

---

## Graduation preserves history.

Graduated students remain part of the school's permanent academic record.

---

## Re-enrollment continues the existing student journey.

Student identity is never recreated.

Only academic participation resumes.

# UI Responsibilities

The Student Management module provides the business interfaces required to manage the complete student lifecycle.

It is responsible for allowing authorized users to:

- Search Students
- View Student Profiles
- Admit Students
- Manage Admissions
- Create Academic Enrollments
- Promote Students
- Transfer Students
- Withdraw Students
- Re-enroll Students
- Graduate Students
- View Student Timeline
- View Academic History

The user interface should expose business workflows rather than technical operations.

---

# API Responsibilities

The Student Management module exposes business operations.

Typical operations include:

- Admit Student
- Approve Admission
- Cancel Admission
- Create Academic Enrollment
- Promote Student
- Transfer Student
- Withdraw Student
- Re-enroll Student
- Graduate Student
- Update Student Profile

These operations represent business actions rather than CRUD endpoints.

Implementation details remain independent of this document.

Student Management is the first module to move onto GraphQL, so the shape its
operations take there is the pattern the rest follow — see
`architecture/graphql-conventions.md`. The lifecycle operations above are
named on that surface as the school names the act (`withdrawStudent`,
`graduateStudent`, `reEnrollStudent`, `transferStudentToSection`,
`transferStudentOut`), never as a status being set. Their REST equivalents
remain only until the clients move, and are then deleted.

---

# Authorization

Student Management never performs authorization internally.

Every workflow must request authorization from the Authorization Domain.

Examples include:

Admission

↓

Authorization

↓

Execute Admission

Promotion

↓

Authorization

↓

Execute Promotion

Transfer

↓

Authorization

↓

Execute Transfer

Authorization policies remain outside this module.

---

# Business Rules

The following rules govern Student Management.

---

## One Person

Every Student originates from exactly one Person.

Duplicate student identities must never exist.

---

## One Student Relationship

Admission creates the Student relationship once.

Promotion, Transfer, Withdrawal, Re-enrollment and Graduation must never create another Student.

---

## Admission Number

Admission Number is the permanent business identifier of a Student.

It:

- Is generated once.
- Never changes.
- Is unique across the Organization.
- Is never reused.

Admission Number identifies the Student throughout their relationship with the school.

---

## Roll Number

Roll Number belongs to Academic Enrollment.

It:

- Is assigned during enrollment.
- May change every Academic Year.
- May change after Section Transfer.
- Is unique only within a Section for a specific Academic Year.
- May be reused in future Academic Years.

Roll Number represents classroom participation.

It does not identify the Student.

---

## Preserve History

Historical records must never be deleted because of operational changes.

Admission.

Promotion.

Transfer.

Withdrawal.

Graduation.

All remain part of the permanent student timeline.

---

## Workflow Driven Status

Student status changes only through business workflows.

Status should never be edited manually.

---

## Academic Participation

Academic participation always occurs through Academic Enrollment.

Student Management must never bypass the Academic Domain.

---

# Common Scenarios

## Mid-Year Admission

A Student joins after the Academic Year has already begun.

Admission remains unchanged.

Academic Enrollment begins immediately.

---

## Student Changes Section

The Student moves from Grade 8A to Grade 8B.

Academic Enrollment is updated.

Historical attendance remains unchanged.

---

## Student Withdraws

The Student leaves before completing education.

Status becomes Withdrawn.

Historical information remains searchable.

---

## Student Returns

The Student returns after withdrawal.

Re-enrollment creates a new Academic Enrollment.

Previous academic history remains unchanged.

---

## Student Graduates

The Student successfully completes education.

Status becomes Graduated.

Academic history becomes read-only.

The Student remains searchable.

---

## Former Student Joins as Staff

```
Person

↓

Student

↓

Graduated

↓

Staff
```

No new Person is created.

The original Person continues with a new business relationship.

---

# Future Integrations

Student Management is expected to integrate with future modules.

Examples include:

Academic

- Attendance
- Examination
- Homework
- Lesson Planning
- Timetable

Operations

- Transport
- Hostel
- Library

Finance

- Fee Management
- Scholarships

Communication

- Parent Notifications
- Announcements

AI

- Student Insights
- Performance Analysis
- Personalized Learning

Government

- Student Reports
- Regulatory Exports

Future modules should reference Student Management workflows rather than duplicating student lifecycle logic.

---

# Non Goals

Student Management does not own:

- Person Identity
- Authentication
- Authorization
- Academic Structure
- Teaching Assignment
- Attendance
- Examination
- Finance
- Transport
- Communication

These responsibilities belong to their respective domains or modules.

---

# Summary

Student Management orchestrates the complete lifecycle of students within Nexchool.

It owns business workflows including admission, academic enrollment initiation, promotion, transfer, withdrawal, graduation, re-enrollment, and student history.

The module does not redefine architectural concepts.

Instead, it coordinates the People, Academic, Identity, and Authorization domains to provide a complete business workflow that reflects how schools manage students throughout their educational journey.

By separating business workflows from business concepts, Student Management establishes a maintainable foundation for every future module that interacts with students.

