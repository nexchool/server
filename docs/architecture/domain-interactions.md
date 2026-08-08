# Domain Interactions

## Purpose

The Domain Interactions document defines how business domains within Nexchool collaborate while preserving clear ownership boundaries.

Each domain exists to solve a specific business problem.

No domain should duplicate responsibilities already owned by another domain.

Instead, domains communicate through well-defined business concepts.

This document establishes the interaction rules that every current and future module must follow.

It acts as the architectural map of Nexchool.

---

# Why Domains Exist

Nexchool is organized around business domains rather than technical modules.

Each domain owns a specific business responsibility.

Examples include:

- People
- Identity
- Authorization
- Academics

Modules build upon these domains.

Domains should remain stable over time.

Modules may evolve as business requirements change.

This separation allows the platform to grow without repeatedly restructuring its architecture.

---

# Domain Responsibilities

Every domain answers a different business question.

| Domain | Business Question |
|---------|-------------------|
| People | Who is this person? |
| Identity | How does this person access the platform? |
| Authorization | What may this authenticated user do? |
| Academics | How does this person participate in education? |

These questions are intentionally independent.

A change in one domain should rarely require changes in another.

---

# Domain Ownership

Every business concept must have exactly one owner.

Ownership determines:

- Where the concept is defined.
- Which domain controls its lifecycle.
- Which domain is responsible for business rules.
- Which domain may modify it.

Other domains may reference the concept.

They must never duplicate or redefine it.

---

# Ownership Matrix

The following table defines the owner of the major business concepts within Nexchool.

| Business Concept | Owner Domain |
|------------------|--------------|
| Person | People |
| Staff | People |
| Student Relationship | People |
| Family | People |
| Family Member | People |
| Account | Identity |
| Authentication | Identity |
| Session | Identity |
| Active Context | Identity |
| Business Authority | Authorization |
| Authority Profile | Authorization |
| Capability | Authorization |
| Business Action | Authorization |
| Permission Key | Authorization |
| Programme | Academic |
| Academic Year | Academic |
| Academic Division | Academic |
| Grade | Academic |
| Section | Academic |
| Medium | Academic |
| Subject | Academic |
| Teacher | Academic |
| Academic Enrollment | Academic |
| Teaching Assignment | Academic |
| Class Teacher | Academic |
| Promotion | Academic |
| Graduation | Academic |

Campus (Trust → School → Campus) belongs to the organization structure managed during Organization Setup. Academic concepts reference Campus; they do not own it.

Ownership is exclusive.

A business concept should never belong to multiple domains simultaneously.

---

# Referencing vs Owning

Domains frequently reference concepts owned by other domains.

Referencing is encouraged.

Ownership duplication is not.

Example:

Attendance references:

- Student
- Academic Enrollment
- Teaching Assignment

Attendance does not own these concepts.

Similarly,

Finance references:

- Student
- Family
- Academic Year

Finance does not redefine student identity or academic participation.

This distinction is fundamental to maintaining architectural consistency.

---

# Domain Hierarchy

The core business domains form the foundation of Nexchool.

```
People

        │

        ▼

Identity

        │

        ▼

Authorization

──────────────────────────

Academic

──────────────────────────

Business Modules
```

This hierarchy represents dependency rather than execution order.

Domains lower in the hierarchy provide business concepts used by higher layers.

Higher layers should not modify lower-layer responsibilities.

---

# Architectural Goal

The purpose of domain separation is not technical abstraction.

Its purpose is business clarity.

Every business concept should have:

- One owner.
- One lifecycle.
- One source of truth.

Every module should know exactly where to retrieve business information without redefining existing concepts.

This approach minimizes duplication, simplifies maintenance, and allows Nexchool to evolve through new modules rather than repeated architectural rewrites.


# Dependency Principles

Business domains should collaborate without becoming tightly coupled.

A dependency should exist only when one domain requires concepts owned by another domain.

Dependencies should always represent business relationships rather than implementation convenience.

Whenever possible:

- Reference business concepts.
- Avoid modifying concepts owned by another domain.
- Never duplicate ownership.

These principles allow each domain to evolve independently while maintaining a consistent business model.

---

# Dependency Direction

Dependencies should always flow toward foundational business domains.

The preferred dependency direction is illustrated below.

```
                Business Modules
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   Academic       Authorization    Communication
        │              │
        └───────┬──────┘
                ▼
            Identity
                │
                ▼
             People
```

The People Domain forms the foundation of the business architecture.

Higher-level domains may depend on lower-level domains.

Lower-level domains should never depend on higher-level domains.

---

# Allowed Dependencies

The following dependencies are considered valid.

## Identity → People

Identity references People.

Authentication requires a Person.

Identity never modifies business relationships.

---

## Authorization → Identity

Authorization depends upon authenticated users.

Identity provides authentication.

Authorization evaluates authority.

---

## Authorization → People

Authorization derives Business Authority from organizational responsibilities defined within the People Domain.

Authorization never owns People.

---

## Academic → People

Academic participation depends upon People.

Teacher and Student originate from People.

Academic never manages personal identity.

---

## Modules → Academic

Academic modules should depend upon the Academic Domain.

Examples include:

- Attendance
- Examination
- Homework
- Timetable
- Report Cards

These modules consume academic concepts rather than redefining them.

---

## Modules → Authorization

Every business module should rely upon the Authorization Domain when evaluating user authority.

Modules should never create independent permission systems.

---

## Modules → Identity

Modules may require information about the authenticated session.

They should never perform authentication themselves.

---

## Modules → People

Modules may reference People.

Examples include:

- Student Information
- Staff Information
- Family Information

Modules should never duplicate People records.

---

# Forbidden Dependencies

The following dependencies should never exist.

---

## People → Identity

The People Domain should never know whether someone has a User account.

Authentication is optional.

Business identity is not.

---

## People → Authorization

People defines business relationships.

It never evaluates permissions.

---

## Identity → Academic

Authentication should never know:

- Teacher
- Student
- Grade
- Section

Identity is completely independent of education.

---

## Academic → Authorization

The Academic Domain defines educational concepts.

It should never determine whether a user may perform academic actions.

Academic owns business concepts.

Authorization owns access decisions.

---

## Academic → Identity

Academic participation should never depend upon authentication.

Teachers and Students exist regardless of whether they receive User accounts.

---

## Module → Module

Business modules should avoid direct dependencies whenever possible.

Example:

Attendance should not depend directly upon Examination.

Instead, both should depend upon the Academic Domain.

This keeps modules loosely coupled.

---

# Cross-Domain Communication

Domains should communicate through owned business concepts.

Example:

Attendance requires Student information.

Correct:

```
Attendance

↓

Academic Enrollment
```

Incorrect:

```
Attendance

↓

Student Table

↓

Modify Student
```

Attendance references academic participation.

It does not own or modify students.

---

# Module Integration Rules

Every new module introduced into Nexchool should follow these rules.

## Reference Existing Domains

Modules should reuse business concepts already owned by existing domains.

Do not redefine:

- Person
- User
- Teacher
- Student
- Academic Year
- Teaching Assignment

---

## Own New Business Concepts

If a module introduces a genuinely new business concept, that concept should belong exclusively to that module.

Example:

Transport owns:

- Vehicle
- Route
- Trip

Library owns:

- Book
- Loan
- Reservation

Finance owns:

- Fee Structure
- Invoice
- Payment

Ownership should remain clear.

---

## Keep Modules Independent

Modules should communicate through domains rather than directly depending upon each other.

Poor example:

```
Homework

↓

Attendance

↓

Examination
```

Preferred:

```
Homework

↓

Academic
```

```
Attendance

↓

Academic
```

```
Examination

↓

Academic
```

Each module references the shared Academic Domain.

No module becomes responsible for another module's business logic.

---

# Shared Business Concepts

Some concepts are referenced throughout the platform.

Examples include:

- Person
- Academic Year
- Academic Enrollment
- Teaching Assignment
- Business Authority

These concepts should remain stable.

Changes to these concepts affect multiple domains.

Therefore they should evolve carefully.

---

# Architectural Review Checklist

Whenever a new feature is introduced, the following questions should be answered.

## Ownership

Which domain owns this business concept?

---

## Dependency

Which existing domain should this feature depend upon?

---

## Business Language

Does this feature use existing business terminology?

---

## Duplication

Is this concept already owned elsewhere?

---

## Business Rules

Which domain owns the lifecycle?

---

## Authorization

Should the Authorization Domain evaluate access?

---

## Academic Participation

Does this feature require Academic concepts?

---

## Identity

Does this feature require authentication?

---

# Examples

## Attendance

Depends upon:

- Academic
- Authorization
- Identity

References:

- Academic Enrollment
- Teaching Assignment

Owns:

- Attendance Records

---

## Examination

Depends upon:

- Academic
- Authorization

References:

- Subject
- Grade
- Section
- Teaching Assignment

Owns:

- Examination Schedule
- Marks
- Assessment Results

---

## Finance

Depends upon:

- People
- Authorization

References:

- Student
- Family

Owns:

- Fee Structures
- Payments
- Invoices

---

## Communication

Depends upon:

- Identity
- Authorization
- People

References:

- Students
- Staff
- Families

Owns:

- Announcements
- Messages
- Notification History

---

# Architectural Principles

The interaction between domains follows these principles.

## One Concept, One Owner

Every business concept should have exactly one owning domain.

---

## Reference Rather Than Duplicate

Reuse existing business concepts.

Avoid recreating them.

---

## Business Before Technology

Dependencies should reflect school operations rather than technical convenience.

---

## Stable Foundations

Foundational domains should remain stable while modules continue evolving.

---

## Loose Coupling

Modules should communicate through shared domains rather than direct dependencies.

---

## Long-Term Evolution

Adding new modules should require extending the architecture rather than restructuring existing domains.

The architecture should encourage growth through composition rather than duplication.

# Common Architectural Scenarios

The following scenarios illustrate how the Domain Interaction principles should be applied during product development.

---

## Scenario 1 — A Teacher Records Attendance

Business Flow

```
Person

↓

Staff

↓

Teacher

↓

Teaching Assignment

↓

Attendance Record
```

Domain Interaction

```
People
        │
        ▼
Academic
        │
        ▼
Authorization
        │
        ▼
Attendance Module
```

Responsibilities

People owns:

- Person
- Staff

Academic owns:

- Teacher
- Teaching Assignment

Authorization owns:

- Record Attendance authority

Attendance owns:

- Attendance Record

No domain violates another domain's ownership.

---

## Scenario 2 — Parent Views Child Attendance

Business Flow

```
Parent

↓

Family Relationship

↓

Student

↓

Attendance Record
```

Domain Interaction

```
People
        │
        ▼
Academic
        │
        ▼
Authorization
        │
        ▼
Attendance Module
```

Attendance does not determine family relationships.

People owns the relationship.

Authorization determines whether the parent may access that student's attendance.

Attendance simply retrieves the requested data.

---

## Scenario 3 — Examination Module

The Examination Module requires:

- Teacher
- Student
- Subject
- Grade
- Section
- Academic Year
- Teaching Assignment

These concepts already exist.

The Examination Module should reuse them.

The Examination Module owns:

- Examination
- Assessment
- Marks
- Result Publication

It should never redefine Teacher, Student, or Subject.

---

## Scenario 4 — Finance Module

Finance references:

- Student
- Family
- Academic Year

Finance owns:

- Fee Structures
- Invoices
- Payments
- Discounts
- Refunds

Finance should never own Student identity.

---

## Scenario 5 — AI Module

The AI Module should not duplicate business logic.

Instead, it consumes information from other domains.

Examples include:

People

↓

Person Information

Academic

↓

Teaching Assignment

Authorization

↓

User Authority

Finance

↓

Outstanding Fees

Communication

↓

Announcements

The AI Module owns:

- Conversations
- AI Context
- Prompt Orchestration
- Tool Execution

AI should remain a consumer of business domains rather than becoming another source of business truth.

---

# Domain Evolution

Business domains are expected to remain stable for many years.

New functionality should usually appear as new modules rather than new domains.

Examples:

Academic

↓

Attendance

↓

Homework

↓

Examination

↓

Lesson Planning

↓

Timetable

The Academic Domain remains unchanged.

Only new modules are introduced.

---

# When Should a New Domain Be Created?

Creating a new domain should be uncommon.

A new domain should be introduced only when:

- It represents a distinct business responsibility.
- It owns an independent lifecycle.
- Multiple future modules will depend upon it.
- Existing domains cannot reasonably own the concepts.

If these conditions are not satisfied, the feature should most likely become a module.

---

# When Should a New Module Be Created?

A module should be introduced when:

- It solves a specific business workflow.
- It builds upon one or more existing domains.
- It introduces its own business concepts.
- It does not redefine existing domain responsibilities.

Examples include:

- Attendance
- Examination
- Library
- Hostel
- Transport
- Payroll
- Inventory

---

# Anti-Patterns

The following architectural patterns should be avoided.

---

## Duplicate Ownership

Incorrect

```
People

↓

Student
```

```
Attendance

↓

Student
```

Only one domain should own Student.

---

## Cross Module Coupling

Incorrect

```
Attendance

↓

Homework

↓

Examination
```

Modules should not depend upon each other.

Instead:

```
Attendance

↓

Academic
```

```
Homework

↓

Academic
```

```
Examination

↓

Academic
```

---

## Authentication Inside Modules

Incorrect

```
Attendance

↓

Login Check
```

Modules should never authenticate users.

Identity owns authentication.

---

## Authorization Inside Modules

Incorrect

```
Finance

↓

Permission Logic
```

Authorization should remain centralized.

Modules request authorization.

They do not implement authorization.

---

## Business Logic Duplication

Incorrect

```
Transport

↓

Student Promotion
```

Promotion belongs to the Academic Domain.

Transport should consume academic information rather than implementing academic workflows.

---

# Architecture Decision Checklist

Before introducing any new feature, answer the following questions.

## Business Ownership

Which domain owns this business concept?

---

## Existing Concept

Does this concept already exist elsewhere?

---

## Business Responsibility

Which domain owns the lifecycle?

---

## Authorization

Does the feature require business authority?

---

## Academic Participation

Does it depend upon Teachers, Students, or Academic Structure?

---

## Identity

Does it require an authenticated user?

---

## Reuse

Can an existing domain or module solve this problem?

---

## Future Growth

Will this feature remain isolated, or is it likely to become the foundation for future modules?

---

# Future Architecture

As Nexchool evolves, additional domains may eventually emerge.

Possible future domains include:

- Finance
- Operations
- Communication

Each should follow the same principles defined within this document.

Every new domain should:

- Own unique business concepts.
- Expose reusable business capabilities.
- Collaborate through existing domains.
- Avoid duplicating responsibilities.

The interaction model established in this document should remain unchanged.

---

# Non Goals

This document intentionally does not define:

- Database design
- API contracts
- GraphQL schemas
- Folder structures
- Service implementations
- Repository patterns
- Framework-specific architecture

These concerns belong to implementation.

This document defines only business domain interactions.

---

# Summary

Nexchool is organized around business domains rather than technical modules.

Each domain owns a clearly defined business responsibility.

Every business concept has exactly one owner.

Domains collaborate through well-defined business concepts while preserving ownership boundaries.

Modules extend business domains instead of redefining them.

By following these interaction principles, Nexchool can continue growing through new modules and business capabilities without requiring repeated architectural restructuring.

This document serves as the architectural constitution for domain ownership, dependency management, and cross-domain collaboration across the entire Nexchool platform.
