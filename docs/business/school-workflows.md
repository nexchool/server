# School Workflows

## Purpose

This document describes the major business workflows performed within a school.

Unlike the module documentation, which explains the responsibilities of individual modules, this document explains how those modules collaborate to support real-world school operations.

The objective is to describe how schools function from a business perspective rather than from a software perspective.

Every workflow defined in this document should represent an actual business process performed by schools.

---

# Workflow Principles

All workflows within Nexchool follow the same principles.

## Business First

Every workflow should reflect how schools operate.

Software exists to support the workflow rather than redefine it.

---

## Workflow Over Modules

A business workflow may involve multiple modules.

No workflow should be artificially constrained by module boundaries.

---

## Single Source of Truth

Business concepts remain owned by architecture domains.

Workflows orchestrate those concepts.

They never redefine them.

---

## Preserve History

Business workflows should preserve historical information.

Operational changes must never overwrite completed history.

---

## Long-Term Evolution

Workflows should remain stable even as modules evolve.

Implementation may change.

Business processes should not.

---

# Workflow Categories

School operations can be grouped into several categories.

## Organizational Workflows

Responsible for preparing the school for operation.

Examples include:

- Organization Setup
- Academic Year Setup
- Academic Structure Setup
- Staff Onboarding

---

## Student Workflows

Responsible for the student's educational journey.

Examples include:

- Admission
- Academic Enrollment
- Promotion
- Transfer
- Withdrawal
- Graduation
- Re-enrollment

---

## Academic Workflows

Responsible for education.

Examples include:

- Teaching Assignment
- Attendance
- Homework
- Examination
- Report Cards

---

## Operational Workflows

Responsible for day-to-day administration.

Examples include:

- Fee Collection
- Transport
- Library
- Hostel
- Inventory
- Payroll

---

## Communication Workflows

Responsible for communication between the school and stakeholders.

Examples include:

- Announcements
- Parent Notifications
- Emergency Alerts
- Academic Notifications

---

# Business Lifecycle Overview

A school continuously operates through recurring business cycles.

```
Organization Setup

↓

Academic Year Setup

↓

Admissions

↓

Academic Participation

↓

Assessment

↓

Promotion

↓

Graduation

↓

Academic Year Rollover

↓

Next Academic Year
```

Every Academic Year repeats this cycle.

Historical information remains preserved.

---

# Organization Setup

Organization Setup occurs once when a school begins using Nexchool.

Typical activities include:

- Organization Registration
- Campus Configuration
- Academic Divisions
- Numbering Policies
- Branding
- Initial Staff Setup
- Academic Calendar

Organization Setup creates the foundation for all future workflows.

---

# Academic Year Setup

Before students begin learning, the school prepares the new Academic Year.

Typical activities include:

- Create Academic Year
- Define Terms
- Configure Holidays
- Create Grades
- Create Sections
- Assign Class Teachers
- Configure Subjects
- Prepare Timetable

Academic Year Setup establishes the academic environment before students are enrolled.

---

# Student Journey

The student journey represents the primary workflow within Nexchool.

```
Prospective Student

↓

Admission

↓

Student

↓

Academic Enrollment

↓

Attendance

↓

Assessment

↓

Promotion

↓

Promotion

↓

Graduation

↓

Alumni
```

Not every student follows the same path.

Alternative journeys include:

- Withdrawal
- School Transfer
- Repeat Academic Year
- Re-enrollment

These workflows are described later in this document.

---

# Teacher Journey

The teacher journey begins after employment.

```
Person

↓

Staff

↓

Teacher

↓

Teaching Assignment

↓

Teaching

↓

Assessment

↓

Academic Completion
```

Throughout this journey the Teacher may receive:

- New Teaching Assignments
- Additional Responsibilities
- Class Teacher Assignments
- Academic Coordination Responsibilities

Teaching responsibilities evolve independently of employment.

---

# Relationship Between Workflows

Business workflows frequently interact.

Example:

Admission

↓

Student Management

↓

Academic Enrollment

↓

Fee Assignment

↓

Transport Allocation

↓

Parent Notification

↓

Student Ready

One business workflow may coordinate multiple modules while maintaining clear ownership boundaries.

---

# Summary

School workflows describe how real schools operate.

They provide the bridge between business architecture and software modules.

Architecture defines business concepts.

Modules implement business capabilities.

Workflows orchestrate both into complete business processes that accurately represent the day-to-day operation of a school.

# Student Admission Workflow

## Purpose

The Student Admission Workflow is responsible for converting a prospective student into a Student of the school.

Admission represents the beginning of the student's relationship with the organization.

It establishes the Student relationship but does not begin academic participation.

---

## Participants

Primary participants include:

- Admission Office
- Administrative Staff
- Principal
- Parent / Guardian

Supporting modules include:

- Student Management
- People Domain
- Authorization
- Communication

---

## Workflow

```
Prospective Student

↓

Admission Application

↓

Information Verification

↓

Admission Approval

↓

Student Relationship Created

↓

Admission Number Generated

↓

Ready for Academic Enrollment
```

At this stage the student belongs to the school.

Academic participation has not yet begun.

---

## Business Outcome

Successful completion results in:

- Person exists.
- Student relationship exists.
- Admission Number assigned.
- Student profile created.

Academic Enrollment is performed separately.

---

# Academic Enrollment Workflow

## Purpose

Academic Enrollment establishes where the student participates academically.

Unlike Admission, Academic Enrollment occurs repeatedly throughout the student's educational journey.

---

## Participants

Primary participants include:

- Administrative Staff
- Principal

Supporting modules include:

- Academic Domain
- Student Management

---

## Workflow

```
Student

↓

Select Academic Year

↓

Assign Academic Division

↓

Assign Grade

↓

Assign Section

↓

Generate Roll Number

↓

Academic Enrollment Created

↓

Student Becomes Academically Active
```

Enrollment establishes the student's academic participation for one Academic Year.

---

## Business Outcome

Successful enrollment creates:

- Academic Enrollment
- Roll Number
- Grade Assignment
- Section Assignment

The Student remains unchanged.

---

# Attendance Workflow

## Purpose

Attendance records a student's participation during academic activities.

Attendance is recorded against the current Academic Enrollment.

---

## Participants

Primary participants include:

- Teacher

Supporting modules include:

- Attendance
- Academic
- Authorization

---

## Workflow

```
Teaching Assignment

↓

Open Attendance

↓

Mark Attendance

↓

Submit Attendance

↓

Attendance Locked

↓

Parents Notified (Optional)
```

Attendance belongs to a Teaching Assignment.

Not directly to a Teacher.

---

## Business Outcome

Attendance history becomes part of the student's academic record.

---

# Assessment Workflow

## Purpose

Assessment measures student learning throughout the Academic Year.

Assessment includes examinations, quizzes, assignments, projects and future evaluation methods.

---

## Participants

Primary participants include:

- Teacher
- Examination Office

Supporting modules include:

- Examination
- Academic

---

## Workflow

```
Teaching Assignment

↓

Assessment Created

↓

Students Evaluated

↓

Marks Recorded

↓

Results Published

↓

Academic Record Updated
```

---

## Business Outcome

Assessment contributes to:

- Academic Progress
- Report Cards
- Student Performance
- AI Insights

---

# Promotion Workflow

## Purpose

Promotion advances students into the next Academic Year.

Promotion never creates another Student.

Only Academic Enrollment changes.

---

## Participants

Primary participants include:

- Principal
- Administrative Staff

Supporting modules include:

- Student Management
- Academic

---

## Workflow

```
Academic Year Completed

↓

Promotion Process

↓

Next Academic Year

↓

Create Academic Enrollment

↓

Assign Grade

↓

Assign Section

↓

Generate Roll Number
```

Promotion creates a new Academic Enrollment.

Historical records remain unchanged.

---

## Business Outcome

Student identity remains unchanged.

Academic participation continues.

---

# Graduation Workflow

## Purpose

Graduation marks successful completion of education.

Graduation concludes the student's active academic journey.

---

## Workflow

```
Final Academic Enrollment

↓

Graduation

↓

Student Status Updated

↓

Academic History Preserved

↓

Alumni
```

Graduation ends academic participation.

It never removes the Student relationship.

---

## Business Outcome

The student becomes an alumnus while remaining permanently searchable within the organization.

---

# Withdrawal Workflow

## Purpose

Withdrawal records students who discontinue education before graduation.

Withdrawal should preserve all historical information.

---

## Workflow

```
Academic Enrollment

↓

Withdrawal Request

↓

Approval

↓

Status Updated

↓

Enrollment Closed
```

Withdrawal ends the current Academic Enrollment.

It does not delete:

- Person
- Student
- Admission
- Academic History

---

## Business Outcome

The student may later return through Re-enrollment.

---

# Re-enrollment Workflow

## Purpose

Re-enrollment resumes the education of a previously withdrawn student.

The student's identity and history are preserved.

---

## Workflow

```
Withdrawn Student

↓

Re-enrollment

↓

Create Academic Enrollment

↓

Assign Grade

↓

Assign Section

↓

Generate Roll Number

↓

Student Active
```

No new Admission occurs.

No new Student relationship is created.

---

## Business Outcome

The student's educational journey continues from the existing business identity.

---

# Workflow Relationships

The major student workflows relate to one another as follows.

```
Admission

↓

Academic Enrollment

↓

Attendance

↓

Assessment

↓

Promotion

↓

Academic Enrollment

↓

Graduation

↓

Alumni
```

Alternative paths include:

```
Admission

↓

Academic Enrollment

↓

Withdrawal

↓

Re-enrollment

↓

Academic Enrollment
```

All workflows preserve the same Person and Student relationship throughout the student's lifecycle.
