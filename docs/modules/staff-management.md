# Staff Management

## Purpose

The Staff Management module manages the complete employment lifecycle of staff members within Nexchool.

It provides the business workflows required to onboard, employ, manage, transfer, resign, retire, and maintain staff throughout their relationship with the organization.

Staff Management does not redefine business concepts owned by the core architecture.

Instead, it orchestrates those concepts into workflows that accurately represent how schools manage their workforce.

This module serves as the operational layer between organizational administration and the underlying business domains.

---

# Business Responsibilities

The Staff Management module is responsible for:

- Staff Recruitment
- Staff Onboarding
- Employment Creation
- Staff Profile Management
- Staff Search
- Employment Status Management
- Staff Separation
- Staff Retirement
- Staff Rejoining
- Employment Timeline
- Staff Directory

These responsibilities represent complete business workflows rather than technical operations.

---

# Business Scope

Staff Management begins when a person is recruited or appointed by the organization.

Its responsibility continues throughout the person's employment.

Typical lifecycle:

```
Candidate

↓

Recruitment

↓

Staff

↓

Employment

↓

Role Changes

↓

Resignation

↓

Retirement

↓

Former Staff
```

Not every staff member follows the same journey.

Some may:

- Join on Contract
- Become Permanent
- Resign
- Return Later
- Retire

The module supports all employment journeys while preserving complete employment history.

---

# Module Ownership

Staff Management owns the following workflows.

## Recruitment

Managing candidates before they become Staff.

---

## Staff Onboarding

Creating the employment relationship.

---

## Employment Management

Managing staff throughout active employment.

---

## Staff Profile

Managing employment-specific information.

---

## Staff Search

Searching and locating staff members.

---

## Staff Separation

Managing resignation, termination and retirement.

---

## Employment Timeline

Maintaining chronological employment history.

---

# What This Module Does NOT Own

The following business concepts belong to architecture domains.

| Business Concept | Owner |
|------------------|-------|
| Person | People Domain |
| Staff Relationship | People Domain |
| User | Identity Domain |
| Authentication | Identity Domain |
| Business Authority | Authorization Domain |
| Teacher | Academic Domain |
| Teaching Assignment | Academic Domain |

Staff Management references these concepts.

It never owns or redefines them.

---

# Dependencies

Staff Management depends upon several architecture domains.

## People Domain

Provides:

- Person
- Staff Relationship

---

## Identity Domain

Provides:

- User (Optional)
- Authentication
- Active Context

Some Staff members may never receive a User account.

Authentication remains optional.

---

## Authorization Domain

Provides:

- Business Authority
- Authority Profiles

Staff Management requests authorization before executing employment workflows.

---

## Academic Domain

Provides:

- Teacher
- Teaching Assignment

Staff Management never determines whether a Staff member teaches.

Academic participation belongs to the Academic Domain.

---

# Integration Matrix

| Domain / Module | Purpose |
|-----------------|---------|
| People | Person and Staff relationship |
| Identity | User account (optional) |
| Authorization | Business Authority |
| Academic | Teacher participation |
| Payroll | Salary processing |
| Attendance | Staff Attendance |
| Communication | Internal communication |
| Inventory | Asset allocation |
| AI | Staff insights |

Staff Management acts as the central employment workflow while collaborating with the rest of the platform.

---

# Staff Lifecycle

Every Staff member follows a business lifecycle.

```
Candidate

↓

Recruitment

↓

Staff Relationship

↓

Employment

↓

Active Staff

↓

Role Changes

↓

Resignation / Retirement

↓

Former Staff
```

Throughout this lifecycle the Person remains unchanged.

Only the employment relationship evolves.

---

# Employment Status

Employment Status represents the staff member's organizational state.

Suggested statuses include:

- Candidate
- Joining
- Active
- Probation
- Contract
- Permanent
- On Leave
- Resigned
- Retired
- Terminated

Status changes occur only through business workflows.

---

# Staff Information

Staff Management owns employment-specific information.

Examples include:

- Employee ID
- Joining Date
- Employment Type
- Employment Status
- Date of Confirmation
- Date of Leaving
- Organization Joining Details

Personal identity information including:

- Name
- Date of Birth
- Address
- Contact Details
- Email

belongs to Person within the People Domain.

---

# Employment Relationship

Every Staff member originates from a Person.

```
Person

↓

Staff Relationship

↓

Staff Management
```

Academic participation occurs independently.

```
Person

↓

Staff

↓

Teacher

↓

Teaching Assignment
```

Teacher participation never replaces the employment relationship.

---

# Business Principles

The Staff Management module follows these principles.

## One Person

Every Staff member originates from exactly one Person.

Duplicate staff identities should never exist.

---

## One Staff Relationship

Employment creates the Staff relationship once.

Future employment events modify the relationship.

They never create another Staff relationship.

---

## Employment Before Teaching

Teaching is an academic responsibility.

Employment always precedes academic participation.

---

## Preserve History

Employment history should never be deleted.

Every employment event should remain traceable.

---

## Business Before Technology

Employment workflows should reflect how schools manage staff.

Implementation details should never influence business behavior.

---

# Summary

Staff Management orchestrates the complete employment lifecycle of staff members within Nexchool.

It owns business workflows including recruitment, onboarding, employment, separation, retirement and employment history while relying on the People, Identity, Authorization and Academic domains for foundational business concepts.

By separating employment workflows from business concepts, the module establishes a stable foundation for every future module that interacts with staff.


# Staff Onboarding

## Purpose

Staff Onboarding prepares a selected person to join the organization.

It collects the required employment information and ensures that the individual is ready to become a Staff member.

Staff Onboarding does not create academic participation.

---

## Participants

Primary participants include:

- Principal
- Administrative Staff

Supporting modules include:

- Staff Management
- People Domain
- Authorization

---

## Workflow

```
Selected Candidate

↓

Collect Employment Information

↓

Verify Required Documents

↓

Confirm Joining Date

↓

Ready for Employment
```

The onboarding workflow prepares the organization to establish the employment relationship.

---

## Business Outcome

Successful onboarding prepares:

- Personal Information
- Employment Information
- Required Documents
- Joining Details

The Staff relationship is created during Joining.

---

# Joining Workflow

## Purpose

Joining establishes the Staff relationship between a Person and the organization.

Joining marks the official beginning of employment.

This is the only workflow that creates the Staff relationship.

---

## Participants

Primary participants include:

- Principal
- Administrative Staff

Supporting modules include:

- People Domain
- Identity Domain
- Authorization Domain

---

## Workflow

```
Joining Date

↓

Create Person

↓

Create Staff Relationship

↓

Generate Employee ID

↓

Employment Period Started

↓

Staff Active
```

Joining establishes the employment relationship.

Teaching responsibilities are assigned separately by the Academic Domain.

---

## Business Outcome

Successful joining creates:

- Person
- Staff Relationship
- Employee ID
- Employment Period

The staff member is now part of the organization.

---

# Employment Lifecycle

Employment evolves through organizational events.

```
Joining

↓

Active Employment

↓

Designation Changes

↓

Employment Changes

↓

Leave

↓

Resignation / Retirement
```

The Person remains unchanged throughout the lifecycle.

---

# Designation Change

## Purpose

Designation Change updates the organizational role of a Staff member.

Examples include:

- Teacher
- Principal
- Receptionist
- Accountant
- Driver
- Librarian

Designation reflects employment responsibility.

It does not determine academic participation.

---

## Workflow

```
Active Staff

↓

Designation Updated

↓

Employment Updated
```

The Staff relationship remains unchanged.

---

# Employment Changes

Employment information may change throughout the staff member's career.

Examples include:

- Employment Type
- Salary
- Reporting Manager
- Working Hours
- Employment Status
- Campus Assignment

Employment changes update the current Employment Period.

---

# Leave Workflow

## Purpose

Leave temporarily suspends active work without ending employment.

Examples include:

- Casual Leave
- Sick Leave
- Earned Leave
- Maternity Leave
- Study Leave

The Staff relationship remains active.

---

## Workflow

```
Active Staff

↓

Leave Approved

↓

On Leave

↓

Return

↓

Active Staff
```

Leave never creates a new employment period.

---

# Resignation Workflow

## Purpose

Resignation records voluntary separation from the organization.

Employment ends while preserving complete employment history.

---

## Workflow

```
Active Staff

↓

Resignation

↓

Notice Period

↓

Employment Closed

↓

Former Staff
```

Teaching participation automatically ends when active employment ends.

---

## Business Outcome

Employment Period is completed.

The Person and Staff relationship remain part of the organization's history.

---

# Retirement Workflow

## Purpose

Retirement marks the completion of a staff member's career with the organization.

Employment ends while preserving historical records.

---

## Workflow

```
Active Staff

↓

Retirement

↓

Employment Closed

↓

Former Staff
```

Retirement concludes active employment.

---

# Rejoining Workflow

## Purpose

Former Staff members may later return to the organization.

Rejoining starts a new Employment Period while reusing the existing Person and Staff relationship.

---

## Workflow

```
Former Staff

↓

Rejoin

↓

New Employment Period

↓

Active Staff
```

No new Person is created.

No new Staff relationship is created.

Only a new Employment Period begins.

---

# Employment History

Every Employment Period contributes to the staff member's employment history.

Employment History includes:

- Joining
- Designation Changes
- Employment Changes
- Leave
- Resignation
- Retirement
- Rejoining

Historical employment information should never be modified after completion.

---

# Employment Timeline

Staff Management maintains a chronological timeline of employment events.

Examples include:

- Joined Organization
- Designation Changed
- Employment Updated
- Leave Approved
- Returned From Leave
- Resigned
- Rejoined
- Retired

The timeline provides a complete employment history throughout the staff member's relationship with the organization.

---

# Business Rules

## Joining creates the Staff relationship.

A Person becomes Staff only after joining the organization.

---

## One Person

Every Staff member references one Person.

Duplicate staff identities must never exist.

---

## One Staff Relationship

Joining creates the Staff relationship once.

Future employment events update the existing relationship.

---

## Employment Periods

A Staff member may have multiple Employment Periods during their relationship with the organization.

Each Employment Period represents one continuous period of employment.

---

## Employment Before Teaching

Teaching participation requires an active Staff relationship.

Teaching is established separately by the Academic Domain.

---

## Preserve Employment History

Employment history must never be deleted.

Every Employment Period remains permanently available.

---

## Designation does not imply Teaching

Having the designation **Teacher** does not automatically create academic participation.

Academic participation begins only after Teacher participation and Teaching Assignments are created by the Academic Domain.

---

## Rejoining continues the existing identity

Rejoining never creates another Person.

Rejoining never creates another Staff relationship.

Only a new Employment Period is created.