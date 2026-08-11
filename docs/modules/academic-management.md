# Academic Management

## Purpose

The Academic Management module manages the complete academic structure of the organization.

It provides the business workflows required to prepare, organize, and maintain the school's academic environment before and throughout every Academic Year.

Academic Management does not redefine business concepts owned by the Academic Domain.

Instead, it orchestrates those concepts into workflows that allow the school to conduct education in a structured and consistent manner.

This module serves as the operational layer between school administration and the Academic Domain.

---

# Business Responsibilities

The Academic Management module is responsible for:

- Academic Year Management
- Academic Calendar Management
- Academic Division Management
- Grade Management
- Section Management
- Subject Management
- Subject Group Management
- Class Teacher Assignment
- Teaching Assignment
- Academic Year Rollover
- Academic Structure Maintenance

These responsibilities represent complete business workflows rather than individual database operations.

---

# Business Scope

Academic Management begins before a new Academic Year starts.

Its responsibility continues until the Academic Year is completed and the next Academic Year is prepared.

Typical lifecycle:

```
Academic Year

↓

Academic Calendar

↓

Academic Structure

↓

Subject Planning

↓

Teacher Assignment

↓

Academic Operations

↓

Academic Year Completion

↓

Academic Year Rollover
```

This module prepares the academic environment for every educational activity performed by the school.

---

# Module Ownership

The Academic Management module owns the following business workflows.

## Academic Year Setup

Preparing new Academic Years.

---

## Academic Calendar

Managing working days, holidays and academic events.

---

## Academic Structure

Managing:

- Academic Divisions
- Grades
- Sections

---

## Subject Management

Managing subjects offered by the school.

---

## Subject Group Management

Managing grouped subjects where applicable.

---

## Class Teacher Assignment

Assigning Class Teachers for an Academic Year.

---

## Teaching Assignment

Assigning teachers to teach subjects.

---

## Academic Year Rollover

Preparing the next Academic Year.

---

# What This Module Does NOT Own

The following business concepts belong to architecture domains.

| Business Concept | Owner |
|------------------|-------|
| Academic Year | Academic Domain |
| Academic Enrollment | Academic Domain |
| Teacher | Academic Domain |
| Teaching Assignment | Academic Domain |
| Student | People Domain |
| Staff | People Domain |
| Person | People Domain |
| Authorization | Authorization Domain |

Academic Management orchestrates these concepts through business workflows.

It never redefines them.

---

# Dependencies

Academic Management depends upon several architecture domains.

## Academic Domain

Provides:

- Academic Year
- Teacher
- Teaching Assignment
- Academic Enrollment

---

## People Domain

Provides:

- Staff
- Student

---

## Authorization Domain

Provides:

- Business Authority

---

## Identity Domain

Provides:

- Active Context

---

# Integration Matrix

| Domain / Module | Purpose |
|-----------------|---------|
| Academic | Academic concepts |
| People | Teachers and Students |
| Student Management | Student Enrollment |
| Staff Management | Staff information |
| Attendance | Teaching Assignments |
| Examination | Academic Structure |
| Homework | Teaching Assignments |
| Timetable | Academic Structure |
| AI | Academic Insights |

Academic Management prepares the foundation upon which every academic module operates.

---

# Academic Lifecycle

Every Academic Year follows a predictable lifecycle.

```
Create Academic Year

↓

Configure Calendar

↓

Prepare Academic Structure

↓

Assign Teachers

↓

Academic Session Begins

↓

Academic Activities

↓

Academic Year Completed

↓

Academic Year Rollover
```

Every academic workflow depends upon this lifecycle.

---

# Academic Structure

Academic Management organizes education through a hierarchical academic structure.

```
Academic Year

↓

Academic Division

↓

Grade

↓

Section
```

Each level has a clearly defined responsibility.

---

## Academic Year

Defines the operational context for all academic activities.

Only one Academic Year should normally be active at a time.

---

## Academic Division

Academic Divisions group Grades into educational stages.

Examples include:

- Primary
- Upper Primary
- Secondary
- Higher Secondary

Divisions help organize curriculum and administration.

---

## Grade

A Grade represents an educational level within an Academic Division.

Examples include:

- Grade 1
- Grade 5
- Grade 8
- Grade 12

Grades define academic progression.

---

## Section

A Section represents one classroom within a Grade.

Examples:

- Grade 8A
- Grade 8B
- Grade 8C

Students participate academically through Sections.

---

# Subject Structure

Subjects define what students study.

Examples include:

- Mathematics
- Science
- English
- Gujarati
- Hindi
- Social Science
- Computer Science

Subjects are managed independently of Teachers.

Teachers participate through Teaching Assignments.

---

# Business Principles

The Academic Management module follows these principles.

## Academic Year First

Every academic activity belongs to an Academic Year.

---

## One Academic Structure

Academic Structure should remain consistent throughout an Academic Year.

---

## Subjects belong to the Academic Structure

Teachers do not own subjects.

Teaching Assignments connect Teachers with Subjects.

---

## Preserve History

Academic structures should never overwrite previous Academic Years.

Each Academic Year preserves its own academic configuration.

---

## Business Before Technology

Academic workflows should reflect real school administration.

Implementation details should never influence business behavior.

---

# Summary

Academic Management orchestrates the complete academic preparation and organization of the school.

It owns workflows including Academic Year setup, Academic Calendar management, Academic Structure management, Subject management, Teacher assignment and Academic Year rollover while relying on the Academic Domain for foundational business concepts.

This module establishes the operational foundation for every academic activity performed within Nexchool.

# Programme Management

## Purpose

A Programme defines how education is delivered within the organization.

Programmes allow a single organization to support multiple educational systems without changing the overall architecture.

Examples include:

- State Board
- CBSE
- ICSE
- Cambridge
- IB

Each Programme defines its own academic structure, progression rules and educational policies.

---

## Participants

Primary participants include:

- Principal
- Academic Administrator

Supporting modules include:

- Academic Domain
- Authorization

---

## Workflow

```
Create Programme

↓

Configure Academic Structure

↓

Configure Promotion Rules

↓

Configure Subject Structure

↓

Programme Ready
```

Programmes are generally created once and evolve over time.

---

## Business Outcome

A Programme becomes the academic foundation upon which Academic Years are created.

---

# Academic Year Workflow

## Purpose

Academic Year defines the operational period during which all academic activities occur.

It belongs to the organization and is shared by every Programme it runs; the
Programme decides what happens inside it (ADR-012).

Only one Academic Year should normally remain Active.

Historical Academic Years remain available for reporting and historical navigation.

---

## Workflow

```
Programme

↓

Create Academic Year

↓

Configure Dates

↓

Draft

↓

Review

↓

Activate
```

Activation makes the Academic Year available across the platform.

---

## Business Outcome

A new operational context becomes available for:

- Students
- Teachers
- Attendance
- Examination
- Homework
- Reports
- AI

---

# Academic Calendar Workflow

## Purpose

Academic Calendar defines the schedule of the Academic Year.

It represents the official calendar followed by the school.

---

## Workflow

```
Academic Year

↓

Configure Working Days

↓

Configure Holidays

↓

Configure Academic Events

↓

Publish Calendar
```

Examples of Academic Events include:

- Examination Period
- Parent Meeting
- Sports Day
- Annual Function
- Result Declaration

---

## Business Outcome

The Academic Calendar becomes available throughout the platform.

---

# Academic Structure Workflow

## Purpose

Academic Structure organizes students into educational groups.

```
Programme

↓

Academic Year

↓

Academic Division

↓

Grade

↓

Section
```

Academic Structure is prepared before students are enrolled.

---

## Workflow

```
Create Academic Divisions

↓

Create Grades

↓

Create Sections

↓

Academic Structure Ready
```

Student enrollment begins only after the Academic Structure is available.

---

# Subject Management Workflow

## Purpose

Subject Management defines the subjects offered within a Programme.

Subjects exist independently of Teachers.

Teaching responsibilities are assigned separately.

---

## Workflow

```
Create Subject

↓

Assign Subject Type

↓

Assign Tags

↓

Publish Subject
```

---

## Subject Types

Every Subject belongs to one of the following categories.

- Core
- Elective

Future subject types may include:

- Practical
- Laboratory
- Activity
- Vocational

---

## Subject Tags

Subjects may be tagged for organizational purposes.

Examples include:

- Language
- STEM
- Commerce
- Science
- Arts

Tags provide flexible categorization without introducing additional hierarchy.

---

# Grade Subject Assignment

## Purpose

Grades define which Subjects are taught during an Academic Year.

Subjects belong to the organization.

Grades determine which subjects participate academically.

---

## Workflow

```
Grade

↓

Select Subjects

↓

Core Subjects

↓

Elective Subjects

↓

Publish Subject Structure
```

Students inherit the subject structure through Academic Enrollment.

---

# Class Teacher Assignment Workflow

## Purpose

Every Section should normally have one Class Teacher responsible for overall classroom administration.

Although the system allows multiple Class Teacher assignments, this should be treated as an exceptional situation.

---

## Workflow

```
Section

↓

Assign Teacher

↓

Validate Existing Assignment

↓

Warning (If Required)

↓

Assignment Created
```

If the selected Teacher is already assigned as Class Teacher for another Section, the system should display a warning.

The school may still continue if required.

---

## Business Outcome

Each Section receives its primary academic coordinator.

---

# Teaching Assignment Workflow

## Purpose

Teaching Assignment connects Teachers with Subjects and Sections during an Academic Year.

Teaching Assignment represents academic responsibility.

It does not represent employment.

---

## Workflow

```
Teacher

↓

Select Subject

↓

Select Grade

↓

Select Section

↓

Create Teaching Assignment
```

One Teacher may receive multiple Teaching Assignments.

One Subject may also have multiple Teachers.

---

## Teaching Assignment Changes

Teaching responsibilities may change during the Academic Year.

Examples include:

- Teacher Replacement
- Additional Teacher
- Redistribution of Subjects

Historical Teaching Assignments should remain preserved.

Future academic activities should reference the updated Teaching Assignment.

---

# Academic Year Rollover Workflow

## Purpose

Academic Year Rollover prepares the next Academic Year using the previous year's academic structure.

Rollover reduces repetitive administrative work while preserving historical records.

---

## Workflow

```
Completed Academic Year

↓

Create New Academic Year

↓

Copy Academic Structure

↓

Copy Subjects

↓

Copy Sections

↓

Copy Class Teacher Assignments (Optional)

↓

Create Draft Promotions

↓

Review

↓

Publish
```

Historical Academic Years remain unchanged.

---

## Promotion Rules

Draft Promotions are generated using the Programme's Promotion Rules.

Examples include:

- Minimum Passing Percentage
- Subject-wise Passing Rules
- Manual Review Required
- Highest Grade Graduation

Draft Promotions should always be reviewable before final confirmation.

---

## Graduation During Rollover

Students belonging to the highest Grade supported by the Programme should automatically be prepared for Graduation.

Example:

```
Highest Grade

↓

Grade 10

↓

Promotion

↓

Graduate
```

Graduation remains a reviewable draft until confirmed.

---

## Section Generation

During Academic Year Rollover, existing Sections should be copied into the new Academic Year.

Schools may:

- Keep existing Sections
- Add new Sections
- Remove unused Sections
- Merge Sections

Section changes affect only the new Academic Year.

Historical Sections remain unchanged.

---

# Section Merge Workflow

## Purpose

Schools may merge Sections during an Academic Year when operational requirements change.

Examples include:

- Low Student Strength
- Teacher Availability
- Administrative Decisions

---

## Workflow

```
Section A

+

Section B

↓

Merge

↓

Future Activities Continue
```

Historical Attendance, Examination, Homework and Reports remain associated with their original Sections.

Only future academic activities occur within the merged Section.

---

# Business Rules

## Programmes define educational policies.

A Programme owns its academic structure, its subjects and its promotion rules.

---

## Academic Years belong to the organization.

An organization running two Programmes has one 2026–27, not two. Each Programme
follows its own terms, examinations and promotion rules within that shared year
(ADR-012).

---

## Only one Active Academic Year.

An organization should normally have only one Active Academic Year.

---

## Academic Structure belongs to an Academic Year.

Grades and Sections should never be shared across Academic Years.

---

## Subjects belong to Programmes.

Grades decide which subjects are taught.

Teachers never own Subjects.

---

## Class Teacher is normally one per Section.

The system allows exceptions but warns administrators before assignment.

---

## Teaching Assignments preserve history.

Changing Teachers should never overwrite historical academic records.

---

## Academic Year Rollover never modifies history.

It prepares the next Academic Year while preserving completed Academic Years.

---

## Promotion creates Drafts.

Promotion decisions should always be reviewable before becoming final.

---

## Graduation is determined by Programme rules.

Students completing the highest Grade supported by the Programme become Graduation candidates.

---

## Section Merge preserves history.

Historical records remain associated with their original Sections.

Only future activities use the merged Section.