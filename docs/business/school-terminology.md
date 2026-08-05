# School Terminology

> Version: 1.0
> Status: Living Document
> Last Updated: 2026-08-03

---

# References

- product-vision.md
- ../architecture/engineering-principles.md
- ../architecture/naming-conventions.md

---

# Purpose

This document defines the official business terminology used throughout Nexchool.

Its purpose is to ensure that every developer, product owner, designer, tester, AI assistant, and customer uses the same language.

Whenever a new feature is introduced, this document should be referenced before introducing new terminology.

If a concept already exists here, reuse it.

Do not invent a different word.

---

# Important Note

This document is based on common terminology used across Indian schools.

Schools may use slightly different terminology depending on:

- CBSE
- ICSE
- State Board
- IB
- Cambridge

Our goal is to use terminology that feels natural to the majority of schools.

---

# Organization Structure

## Trust / Society

The legal organization responsible for operating one or more schools.

Examples

- Educational Trust
- Society
- Foundation

A trust may operate multiple schools.

---

## School

A single educational institution.

Examples

- ABC Public School
- XYZ International School

A school belongs to one Trust.

---

## Campus

A physical location where a school operates.

Some schools have one campus.

Some schools operate multiple campuses.

Campus should always represent a physical location.

---

# People

## Staff

Any person employed by the school.

Examples

- Teacher
- Principal
- Receptionist
- Accountant
- Librarian
- Driver
- Sports Coach
- Lab Assistant

Staff is the common business term used throughout Nexchool.

---

## Teacher

A Staff member responsible for teaching students.

Teachers are part of Staff.

Not every Staff member is a Teacher.

---

## Student

A learner enrolled in the school.

A Student belongs to a Family.

A Student may be assigned to:

- Class
- Section
- House
- Transport Route
- Hostel

---

## Family

The business unit responsible for one or more students.

A Family may contain:

- Father
- Mother
- Guardian

A Family may be linked with multiple students.

---

## Parent

A father or mother belonging to a Family.

A Parent is not necessarily the legal guardian.

---

## Guardian

A person legally responsible for the student.

A Guardian may be:

- Parent
- Relative
- Foster Parent
- Court-appointed Guardian

A Student always belongs to a Family.

A Guardian is optional.

---

# Academic Structure

## Academic Year

The official academic session.

Examples

2025–26

2026–27

---

## Programme

The educational curriculum followed.

Examples

CBSE

ICSE

GSEB

IB

Cambridge

---

## Grade / Standard

The academic level of the student.

Examples

Grade 1

Class 8

Standard 10

Different schools use different terminology.

Nexchool should allow configuration.

---

## Section

A subdivision of a Grade.

Examples

Class 8

↓

Section A

Section B

Section C

---

## Subject

An academic discipline.

Examples

Mathematics

Science

English

History

---

# Staff Responsibilities

## Principal

Head of the school.

Responsible for overall administration and academics.

---

## Vice Principal

Supports the Principal.

May act on behalf of the Principal when required.

---

## Academic Coordinator

Responsible for supervising a specific academic division.

Examples

Primary

Secondary

Higher Secondary

This is a responsibility, not necessarily a designation.

---

## Class Teacher

The primary teacher responsible for a particular class or section.

Usually one per section.

Responsibilities include:

- Attendance
- Parent communication
- Student discipline
- Leave approval (where applicable)

---

## Subject Teacher

A teacher responsible for teaching a subject.

A Subject Teacher may teach multiple classes.

---

## Head of Department (HoD)

Responsible for a subject department.

Examples

Mathematics

Science

Commerce

This role may not exist in every school.

---

# Administrative Staff

Examples

- Receptionist
- Office Assistant
- Clerk
- Accountant

These are Staff members.

They are not Teachers.

---

# Support Staff

Examples

- Librarian
- Lab Assistant
- Nurse
- Counsellor
- Sports Coach

---

# Auxiliary Staff

Examples

- Driver
- Transport Helper
- Hostel Warden
- Security
- Housekeeping

---

# Business Concepts

## Designation

The official job title assigned to a Staff member.

Examples

Teacher

Senior Teacher

Principal

Receptionist

Designation is generally long-term.

---

## Assignment

A responsibility assigned to a Staff member.

Assignments are usually temporary.

Examples

Class Teacher

Academic Coordinator

Exam Coordinator

Transport Manager

Assignments may change every academic year.

A Staff member may have multiple assignments.

---

## Role

Defines what a User is allowed to access inside the system.

Examples

Teacher Portal

Reception

Finance

Administrator

Roles control permissions.

Roles are not business responsibilities.

---

## Permission

A specific action allowed within the system.

Examples

View Students

Edit Attendance

Approve Leave

Manage Fees

Permissions are technical implementation of business access.

---

# Documents

## Student Documents

Documents belonging to Students.

Examples

Birth Certificate

Transfer Certificate

Aadhaar

APAAR

Medical Certificate

---

## Staff Documents

Documents belonging to Staff.

Examples

Appointment Letter

Degree Certificate

PAN

Aadhaar

Police Verification

Medical Certificate

Driving Licence

---

# Attendance

## Student Attendance

Attendance recorded for students.

---

## Staff Attendance

Attendance recorded for staff.

---

# Leave

Leave is applicable to Staff.

Students submit Leave Requests.

Teachers or authorized Staff approve them.

---

# Status

Status values should always represent meaningful business events.

Avoid generic values like:

- Active
- Inactive

Prefer values that explain the actual state.

Examples

Employment

- Working
- Suspended
- Notice Period
- Left
- Retired

Admission

- Pending
- Approved
- Rejected

Student

- Active
- Graduated
- Transferred
- Left

---

# Golden Rules

1. One business concept should have one official name.

2. Do not introduce synonyms.

3. Business terminology always wins over technical terminology.

4. Architecture should model school operations.

5. If a school administrator naturally uses a term, prefer that term.

6. If uncertain, update this document before introducing new terminology.

---

# Future Updates

This document will evolve as Nexchool introduces new domains, including:

- Payroll
- Library
- Hostel
- Transport
- Inventory
- Communication
- Finance
- Analytics

Every new business term should be added here before implementation.

---

# Final Principle

The language of Nexchool should be the language of schools.

Developers should learn the school's vocabulary.

Schools should never have to learn the software's vocabulary.