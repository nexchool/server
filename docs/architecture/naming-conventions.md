# Naming Conventions

> Version: 1.0
> Status: Living Document
> Last Updated: 2026-08-03

---

# References

- ../business/product-vision.md
- engineering-principles.md

---

# Purpose

This document defines the naming standards used throughout the Nexchool platform.

These standards apply to:

- Database
- Backend
- Frontend
- GraphQL
- REST APIs
- Services
- Models
- DTOs
- Events
- Documentation
- Jira Stories

The objective is simple:

> Every business concept should have exactly one name throughout the entire platform.

---

# Core Rule

Business terminology always takes priority over technical terminology.

If schools naturally use a term,
we should use the same term whenever possible.

---

# Rule 1 — Use School Language

Prefer terminology that schools already understand.

Good

- Staff
- Student
- Parent
- Teacher
- Principal
- Academic Year
- Class
- Section
- Subject
- Timetable
- Leave
- Attendance

Avoid

- Resource
- Entity
- Lifecycle
- Personnel
- Human Resource
- Organizational Unit
- Generic Status

---

# Rule 2 — One Business Concept = One Name

A concept should never have multiple names.

Example

Correct

Staff

Database

staff

Backend

Staff

API

Staff

Frontend

Staff

Documentation

Staff

Incorrect

Database

employees

Backend

Staff

API

Personnel

Frontend

Employee

---

# Rule 3 — Business First

Database names should represent the business.

Good

staff

students

teachers

subjects

designations

departments

families

documents

Avoid

person_resource

entity_master

resource_table

generic_object

---

# Rule 4 — Avoid Generic Names

Never create generic abstractions unless absolutely necessary.

Avoid

Data

Info

Object

Item

Entity

Record

Master

Model

Resource

Instead describe the business.

Example

Good

TeacherAssignment

StaffDocument

StudentAttendance

ClassTeacherAssignment

---

# Rule 5 — Services Should Describe Business Actions

Good

TeacherService

StudentService

AttendanceService

PayrollService

LeaveService

Bad

CommonService

UtilityService

GeneralService

ManagerService

ProcessorService

HelperService

---

# Rule 6 — Methods Should Read Like Business Operations

Good

assignClassTeacher()

approveLeave()

promoteStudent()

publishResults()

calculatePayroll()

Bad

processData()

execute()

handle()

updateInfo()

manage()

---

# Rule 7 — Status Values

Status values should describe real business states.

Avoid

Active

Inactive

Enabled

Disabled

GenericStatus

Prefer

Teacher

ACTIVE

SUSPENDED

LEFT

RETIRED

Student

ACTIVE

GRADUATED

TRANSFERRED

LEFT

Admission

PENDING

APPROVED

REJECTED

CANCELLED

Every status should represent a real-world event.

---

# Rule 8 — Avoid Boolean Explosion

Avoid

isDeleted

isActive

isInactive

isEnabled

isVerified

isLocked

Prefer

status

accountStatus

employmentStatus

verificationStatus

Use enums when the business has multiple states.

---

# Rule 9 — IDs

Every identifier should describe what it identifies.

Good

teacherId

studentId

staffId

familyId

subjectId

Avoid

id1

entityId

masterId

resourceId

objectId

---

# Rule 10 — Relationship Tables

Relationship tables should explain the relationship.

Good

staff_assignments

teacher_subjects

student_documents

family_students

class_subject_teachers

Avoid

mapping

links

relations

bridge_table

xref

---

# Rule 11 — UI Labels

UI terminology should match what schools naturally say.

Example

Good

Staff

Class Teacher

Leave Balance

Joining Date

Documents

Avoid

Human Resources

Resource Allocation

Entity Status

Lifecycle

Personnel

---

# Rule 12 — API Endpoints

REST endpoints should represent business resources.

Good

/api/staff

/api/students

/api/classes

/api/attendance

/api/leave

Avoid

/api/resource

/api/entity

/api/common

/api/data

---

# Rule 13 — GraphQL Types

GraphQL types should represent business objects.

Good

Staff

Teacher

Student

LeaveRequest

AttendanceRecord

Avoid

EntityNode

BaseResource

GenericObject

---

# Rule 14 — Events

Events should describe business events.

Good

StaffJoined

TeacherAssigned

StudentPromoted

LeaveApproved

PayrollGenerated

Bad

DataUpdated

ObjectChanged

RecordModified

EntityProcessed

---

# Rule 15 — Database Columns

Column names should be explicit.

Good

joining_date

leaving_date

staff_code

employment_status

phone_number

Avoid

status_flag

flag

code

type

data

info

---

# Rule 16 — Avoid Abbreviations

Prefer

designation

qualification

attendance

department

Instead of

desig

qual

att

dept

Exceptions

ID

OTP

API

URL

UUID

GST

PAN

Aadhaar

---

# Rule 17 — Shared Vocabulary

The following words have official meanings.

Staff

A person employed by the school.

Teacher

A staff member responsible for teaching.

Student

A learner enrolled in the school.

Family

A group responsible for one or more students.

Parent

A family member.

Guardian

A legally responsible person for a student.

Designation

A job title.

Assignment

A temporary or permanent responsibility.

Role

Permission grouping for system access.

Permission

An action a user is allowed to perform.

User

An authentication account.

Never interchange these words.

---

# Rule 18 — Documentation

Every document should use the same terminology.

Avoid inventing new names.

If a business concept already exists,

reuse it.

---

# Rule 19 — AI Generated Code

Any AI-generated implementation must follow this document.

If AI introduces different terminology,

rename it before merging.

Architecture documents always take precedence over AI output.

---

# Rule 20 — The Naming Test

Before introducing any new name ask:

1. Would a school administrator understand it?
2. Is this term already used elsewhere?
3. Does this represent a real business concept?
4. Will another developer immediately understand it?
5. Will this still make sense five years from now?

If the answer is "No",

choose a better name.

---

# Final Principle

Every line of code should read like the story of a school.

If someone who understands school operations reads our models, services, APIs, or documentation, they should immediately recognize the business process being represented.

Consistency in language creates consistency in architecture.

Consistency in architecture creates maintainable software.