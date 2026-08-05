# Authorization Domain

## Purpose

The Authorization Domain defines how business authority is translated into actions that authenticated users may perform within Nexchool.

It does not authenticate users.

It does not define business relationships.

It does not determine academic participation.

Instead, it determines what an authenticated user is authorized to do based on their responsibilities within the school.

Authorization exists to ensure that every action performed within Nexchool reflects the organizational structure and operational policies of the school.

---

# Domain Philosophy

Authorization should represent business authority rather than technical permissions.

Schools do not think in terms of permissions.

They think in terms of responsibilities.

Examples include:

- Principal
- Vice Principal
- Teacher
- Receptionist
- Accountant
- Librarian
- Transport Manager

Each responsibility naturally carries authority.

The Authorization Domain converts that business authority into capabilities that the software can enforce.

Business authority always originates from the organization.

Technology merely implements it.

---

# Why Authorization is a Separate Domain

Authentication and Authorization solve different business problems.

Authentication answers:

> Who is using the platform?

Authorization answers:

> What is this authenticated user allowed to do?

These concerns must remain completely independent.

Authentication should never determine business authority.

Similarly, business authority should never determine identity.

Separating these responsibilities allows authentication, business relationships, and authorization to evolve independently without affecting one another.

---

# Responsibilities

The Authorization Domain is responsible for:

- Business Authority
- Authority Profiles
- Capabilities
- Business Actions
- Permission Keys
- Authorization Decisions
- Scope Evaluation
- Temporary Delegation

The Authorization Domain is not responsible for:

- Authentication
- User Management
- Business Relationships
- Academic Structure
- Module Workflows
- Business Validation

---

# Business Authority

Business Authority represents the authority granted to an individual by the organization.

Authority always originates from the school.

Examples include:

- Principal
- Teacher
- Receptionist
- Accountant
- Transport Manager

Authority is determined by the responsibilities assigned to a person rather than by their user account.

A User never owns authority.

Authority belongs to the business relationship.

---

# Why Business Authority Exists

Schools organize work through responsibilities rather than permissions.

For example:

A Principal does not manually receive hundreds of individual permissions.

Instead, the Principal holds organizational authority.

Likewise:

A Teacher is trusted to perform teaching responsibilities.

An Accountant is trusted to manage financial operations.

A Receptionist is trusted to manage admissions and visitor interactions.

These responsibilities naturally define what each person may perform within the system.

Authorization should model this business reality.

---

# Authority Profiles

Authority Profiles translate Business Authority into software capabilities.

They provide reusable authorization templates that can be assigned throughout the organization.

For example:

```
Teacher

        │

        ▼

Teacher Authority Profile
```

```
Principal

        │

        ▼

Principal Authority Profile
```

Authority Profiles should represent organizational responsibilities rather than individual users.

This allows authorization to remain consistent across the entire school.

---

# System Authority Profiles

Nexchool provides a collection of Authority Profiles out of the box.

Examples include:

- Principal
- Vice Principal
- Teacher
- Receptionist
- Accountant
- Librarian
- Driver
- Transport Manager
- Office Administrator

These profiles are maintained by the platform.

Most schools should be able to begin using Nexchool without configuring authorization from scratch.

---

# School Authority Profiles

Schools may customize authorization when required.

Examples include:

- Academic Coordinator
- Examination Coordinator
- STEM Coordinator
- Discipline Coordinator
- Olympiad Coordinator

Rather than creating permissions individually, schools create or customize Authority Profiles that reflect their organizational structure.

This customization should remain optional.

---

# Capabilities

Capabilities represent the business operations that an Authority Profile may perform.

Capabilities are expressed using business terminology rather than technical language.

Examples include:

Academic

- Student Attendance
- Homework
- Examination
- Report Cards

Finance

- Fee Collection
- Fee Refunds

Transport

- Route Management
- Vehicle Allocation

Communication

- Announcements
- Messaging

Capabilities should remain understandable to school administrators.

---

# Business Actions

Every Capability exposes one or more Business Actions.

Business Actions describe what may be performed within that capability.

Examples:

Student Attendance

- View Attendance
- Record Attendance
- Edit Attendance
- Lock Attendance
- Export Attendance

Homework

- Create Homework
- Publish Homework
- Edit Homework
- Archive Homework

Business Actions should use business language rather than technical CRUD terminology whenever practical.

Examples:

Prefer:

- Record Attendance
- Collect Fee
- Publish Report Card

Avoid:

- Create Attendance
- Update Fee
- Read Report Card

Authorization should reflect how schools describe their daily operations.

---

# Permission Keys

Permission Keys are internal identifiers used by the software to enforce authorization.

Unlike Business Authority, Authority Profiles, Capabilities, and Business Actions, Permission Keys are implementation details.

Examples include:

```
student_attendance.view

student_attendance.record

student_attendance.edit

fee.collect

report_card.publish
```

Permission Keys should never be exposed to school administrators.

They exist solely for backend authorization, middleware, APIs, and internal implementation.

The architecture should remain independent of these identifiers.

---

# Business Authority Flow

Authorization follows the flow below.

```
Business Authority

        │

        ▼

Authority Profile

        │

        ▼

Capability

        │

        ▼

Business Action

        │

        ▼

Permission Key

        │

        ▼

Authorization Decision
```

Each layer serves a distinct responsibility.

Business concepts remain separate from implementation details.

---

# Design Principles

The Authorization Domain follows the principles below.

## Business Before Technology

Business authority always originates from organizational responsibilities.

Technology simply enforces those responsibilities.

---

## Authority Before Permissions

Business Authority is the primary concept.

Permission Keys are implementation details.

The architecture should never revolve around permission strings.

---

## Business Language

Capabilities and Business Actions should use terminology familiar to schools.

Authorization should remain understandable to non-technical administrators.

---

## Reusable Authorization

Authority Profiles should be reusable across the organization.

Schools should rarely need to configure authorization from scratch.

---

## Platform Defaults

Nexchool should provide sensible default Authority Profiles.

Schools should only customize authorization when their organizational structure requires it.

---

# Summary

The Authorization Domain defines how business authority becomes software authorization.

Business Authority originates from the school.

Authority Profiles translate organizational responsibilities into reusable software capabilities.

Capabilities expose Business Actions.

Business Actions are enforced internally through Permission Keys.

By separating business authority from technical implementation, Nexchool provides an authorization model that remains understandable for school administrators while remaining scalable for developers as the platform grows.

# Authorization Flow

Authorization is evaluated after a user has been successfully authenticated.

Authentication confirms identity.

Authorization determines whether the authenticated user may perform a particular business action.

The Authorization flow is illustrated below.

```
Person

        │

        ▼

User

        │

        ▼

Authentication

        │

        ▼

Authenticated Session

        │

        ▼

Business Authority

        │

        ▼

Authority Profile

        │

        ▼

Capability

        │

        ▼

Business Action

        │

        ▼

Authorization Decision
```

Every authorization decision follows this sequence.

Each stage remains independent and owned by its respective domain.

---

# Authorization Evaluation

Authorization is evaluated whenever a business action is requested.

Examples include:

- Recording Attendance
- Publishing Homework
- Collecting Fees
- Approving Admissions
- Creating Timetables

The Authorization Domain determines whether the authenticated user possesses the required business authority to perform that action.

The business module remains responsible for validating business rules after authorization succeeds.

---

# Scope

Business authority alone is not always sufficient.

Authorization must also determine where that authority applies.

Scope defines the operational boundary of a Business Action.

Examples include:

Teacher

↓

Record Attendance

↓

Assigned Teaching Assignments

Principal

↓

Record Attendance

↓

Entire School

Receptionist

↓

View Student Information

↓

All Students

Scope is evaluated after determining that the user possesses the required Business Action.

---

# Why Scope Exists

Two users may possess the same Business Action while operating within different business boundaries.

Example:

Two Teachers both have the authority to:

```
Record Attendance
```

However:

Teacher A may record attendance only for:

- Grade 8A Mathematics

Teacher B may record attendance only for:

- Grade 9A Science

Their authority remains identical.

Their operational scope differs.

Separating Scope from Business Authority allows Nexchool to model real-world school operations without creating unnecessary Authority Profiles.

---

# Business Validation

Authorization does not replace business validation.

Authorization answers:

> Can this user perform this business action?

Business validation answers:

> Is this operation valid according to business rules?

Example:

Teacher

↓

Record Attendance

↓

Authorized

↓

Attendance already locked

↓

Operation rejected

The rejection occurs because of business rules rather than authorization.

Keeping these concerns separate simplifies both architecture and implementation.

---

# Active Context

Active Context exists solely to control the user experience.

It never grants or removes business authority.

Examples:

Teacher Context

↓

Teacher Dashboard

↓

Teacher Navigation

Parent Context

↓

Parent Dashboard

↓

Parent Navigation

Changing Active Context changes:

- Navigation
- Screens
- Shortcuts
- Default Workflows

It does not change authorization.

---

# Why Active Context Does Not Affect Authorization

A Person may simultaneously participate in multiple business relationships.

Example:

Rahul Sharma

↓

Teacher

↓

Parent

↓

Academic Coordinator

Regardless of the currently selected Active Context, Rahul continues to possess every business authority assigned by the organization.

The Active Context simply determines which experience is currently presented to the user.

Authorization remains unchanged.

---

# Context Switching

Context Switching allows a User to move between multiple business experiences without re-authentication.

Example:

Teacher Context

↓

Switch Context

↓

Parent Context

↓

Parent Dashboard

Authentication remains unchanged.

Authorization remains unchanged.

Only the active user experience changes.

This allows a single authenticated User to participate naturally across multiple responsibilities.

---

# Notifications Across Contexts

Notifications are independent of the currently selected Active Context.

Users receive notifications for every responsibility they possess.

Example:

Rahul is currently using:

Teacher Context

A Fee Reminder notification arrives for:

Parent Context

Rahul opens the notification.

Nexchool automatically:

- Opens the application.
- Switches to Parent Context.
- Navigates to the relevant screen.

The user never needs to manually change contexts before accessing the notification.

This behavior reflects how users naturally expect multi-context applications to behave.

---

# Temporary Delegation

Schools occasionally assign temporary authority.

Examples include:

- Principal on leave.
- Examination Coordinator absent.
- Vice Principal acting as Principal.
- Temporary Office Administrator.

Temporary Delegation allows one individual to temporarily perform another person's responsibilities.

Delegation should include:

- Delegated Authority
- Effective Date
- Expiration Date
- Optional Reason

Delegation automatically expires without requiring manual intervention.

Temporary Delegation should remain exceptional rather than becoming the primary authorization model.

---

# System Authority Profiles

Nexchool provides Authority Profiles for common organizational responsibilities.

Examples include:

- Principal
- Vice Principal
- Teacher
- Receptionist
- Accountant
- Librarian
- Driver
- Transport Manager

These profiles are maintained by Nexchool.

Platform updates may improve these profiles over time.

Schools should benefit from these improvements without rebuilding authorization from scratch.

---

# School Authority Profiles

Schools may customize authorization when necessary.

Examples include:

- Academic Coordinator
- Olympiad Coordinator
- Discipline Coordinator
- House Coordinator

Schools may:

- Create new Authority Profiles.
- Duplicate existing profiles.
- Customize Business Actions.
- Restrict Capabilities.

Customizations should remain independent from Nexchool's default profiles.

This allows future platform updates without overwriting school-specific changes.

---

# Authorization Inheritance

Authority should be inherited through business responsibilities rather than duplicated across users.

Example:

Teacher Designation

↓

Teacher Authority Profile

↓

Every Teacher

If the Teacher Authority Profile changes, every Teacher automatically receives the updated authorization.

This significantly reduces administrative effort while maintaining organizational consistency.

---

# Authorization Overrides

Occasionally a school may require authorization exceptions.

Examples include:

- Temporary examination authority.
- Temporary finance approval.
- Audit access.
- Investigation access.

Overrides should remain exceptional.

The normal authorization model should always rely upon Business Authority.

Excessive user-specific overrides indicate that the organizational structure should be reviewed rather than the authorization system.

---

# Business Rules

The Authorization Domain follows these principles.

## Authentication does not grant authority.

Authentication only establishes identity.

---

## Business Authority grants authorization.

Authority always originates from organizational responsibilities.

---

## Active Context never changes authorization.

Context changes user experience only.

---

## Scope limits authority.

Scope determines where a Business Action may be performed.

---

## Business validation remains separate.

Authorization never replaces business rules.

---

## Platform defaults first.

Schools should begin with Nexchool's Authority Profiles and customize only when necessary.

---

## Customization should be exceptional.

Schools should extend authorization rather than redesigning it.

---

# Summary

The Authorization Domain evaluates business authority after authentication has succeeded.

Authorization determines whether a user may perform a Business Action.

Scope determines where that action applies.

Business validation determines whether the operation is currently valid.

Active Context controls only the user experience.

Temporary Delegation supports short-term organizational changes without permanently modifying Business Authority.

Together these concepts create an authorization model that remains simple for schools, scalable for developers, and consistent with Nexchool's business-first architecture.

# Domain Ownership

The Authorization Domain owns every concept related to business authority and software authorization.

Specifically, it owns:

- Business Authority
- Authority Profiles
- Capabilities
- Business Actions
- Permission Keys
- Authorization Decisions
- Scope Evaluation
- Temporary Delegation

The Authorization Domain is the single source of truth for determining whether an authenticated user may perform a business action.

Other domains may define business concepts.

Only the Authorization Domain determines access to those concepts.

---

# Cross Domain Relationships

Authorization collaborates with every business domain while maintaining clear ownership boundaries.

---

## People Domain

The People Domain defines business relationships.

Examples include:

- Staff
- Student
- Family Member

These relationships establish who participates in the organization.

The Authorization Domain never creates or manages People.

Instead, it derives Business Authority from organizational responsibilities assigned within the People Domain.

```
Person

        │

        ▼

Staff

        │

        ▼

Business Authority
```

---

## Identity Domain

The Identity Domain authenticates Users.

Authentication confirms identity.

Authorization determines authority.

Authentication never grants permissions.

Authorization never authenticates users.

Both domains remain independent.

```
Identity Domain

↓

Authentication

↓

Authenticated Session

↓

Authorization Domain
```

---

## Academic Domain

The Academic Domain defines educational participation.

Examples include:

- Teacher
- Student
- Teaching Assignment
- Academic Enrollment

Authorization controls whether an authenticated user may perform academic actions.

The Academic Domain never evaluates permissions.

---

## Finance Domain

Finance owns:

- Fee Collection
- Refunds
- Financial Reports

Authorization determines who may perform these operations.

Finance determines whether the requested financial operation is valid.

---

## Communication Module

Communication owns messaging workflows.

Authorization determines:

- Who may publish announcements.
- Who may message parents.
- Who may send emergency notifications.

Communication never manages business authority.

---

## Every Future Module

Every future module should depend upon the Authorization Domain.

Examples include:

- Attendance
- Timetable
- Examination
- Homework
- Hostel
- Library
- Inventory
- Payroll
- AI

Authorization should remain centralized rather than allowing each module to create independent permission systems.

---

# Architectural Principles

The Authorization Domain follows these architectural principles.

## Business Authority Before Permissions

Business authority originates from organizational responsibilities.

Permission Keys exist only to implement those responsibilities.

The architecture should never revolve around permission strings.

---

## Authorization is Business Driven

Schools determine authority.

The software enforces it.

Authorization should always reflect how schools operate rather than how software frameworks implement security.

---

## One Authorization Model

Every module should use the same authorization architecture.

Modules must never implement independent permission systems.

This ensures consistent behavior throughout Nexchool.

---

## Platform Before Configuration

Nexchool should provide sensible default Authority Profiles.

Schools should begin using the system immediately.

Customization should be optional rather than mandatory.

---

## Configuration Before Custom Development

When schools require organizational differences, they should customize Authority Profiles rather than modifying software behavior.

Authorization should evolve through configuration whenever possible.

---

## Reusable Authorization

Authority Profiles should be reusable.

Business Actions should be reusable.

Capabilities should be reusable.

Authorization should minimize duplication throughout the organization.

---

## Separation of Concerns

Authentication.

Authorization.

Business Validation.

Business Workflow.

Each represents an independent architectural responsibility.

These concerns should never become tightly coupled.

---

## Stable Business Language

Capabilities and Business Actions should use business terminology.

Examples:

Prefer:

- Record Attendance
- Collect Fee
- Publish Homework
- Approve Admission

Avoid:

- Create Attendance
- Update Fees
- CRUD terminology

Authorization should remain understandable to school administrators.

---

# Common Scenarios

The Authorization Domain naturally supports common organizational workflows.

---

## New Teacher Joins

```
Person

↓

Staff

↓

Teacher Designation

↓

Teacher Authority Profile

↓

Authorization Ready
```

No manual permission assignment is required.

---

## Teacher Becomes Examination Coordinator

```
Teacher Authority

+

Examination Coordinator Authority

↓

Combined Authorization
```

The Teacher retains all existing teaching authority while receiving additional examination responsibilities.

---

## Temporary Principal

```
Principal

↓

Temporary Delegation

↓

Vice Principal

↓

Automatic Expiration
```

Business Authority returns automatically after the delegation period ends.

---

## School Creates New Designation

```
Academic Mentor

↓

Duplicate Existing Authority Profile

↓

Customize

↓

Assign
```

Schools extend the authorization model without redesigning it.

---

## Teacher Changes School

Authority does not belong to the User.

Authority belongs to the organization.

A Teacher joining another school receives authority according to the new school's organizational structure.

---

## Parent Context

Parent Context changes:

- Navigation
- Dashboard
- Notifications
- Shortcuts

It does not modify authorization.

---

# Future Evolution

The Authorization Domain is designed for long-term evolution.

Future capabilities may include:

- Multi-Campus Administration
- Campus-specific Authority
- Approval Workflows
- Delegation Chains
- Emergency Authority
- Time-based Authorization
- Approval Hierarchies
- Organization-wide Audit Policies

These features should extend the Authorization Domain rather than replacing its architecture.

The concepts defined in this document should remain stable as Nexchool evolves.

---

# Non Goals

The Authorization Domain intentionally does not manage:

- Authentication
- User Accounts
- Passwords
- Sessions
- Business Relationships
- Academic Structure
- Module Workflows
- Business Validation
- Database Design
- API Implementation
- Middleware Implementation

These concerns belong to their respective domains.

---

# Summary

The Authorization Domain defines how organizational responsibilities become software authorization.

Business Authority originates from the school's organizational structure.

Authority Profiles translate organizational responsibilities into reusable authorization models.

Capabilities represent business operations.

Business Actions define the operations users may perform.

Permission Keys provide internal identifiers for software implementation.

Scope determines where authorization applies.

Business Validation determines whether an authorized operation is currently valid.

By separating Business Authority, Authentication, Authorization, and Business Validation, Nexchool provides an authorization architecture that remains aligned with real-world school operations while supporting long-term product evolution.

The Authorization Domain establishes a single, consistent authorization model that every present and future module should adopt, ensuring that the platform grows without introducing fragmented permission systems or inconsistent access-control behavior.
