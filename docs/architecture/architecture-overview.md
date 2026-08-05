# Nexchool Architecture Overview

## Purpose

This document provides a high-level overview of the Nexchool architecture.

It serves as the entry point for understanding the platform's business architecture before reading the individual domain documents.

Rather than describing implementation details, this document explains how the major architectural domains relate to one another and how business concepts flow throughout the system.

Every developer, architect, and AI assistant should begin here before exploring individual architecture documents.

---

# Architecture Philosophy

Nexchool is designed around business domains rather than technical modules.

The architecture reflects how schools operate in the real world.

Business decisions drive technical decisions.

Technology should adapt to school workflows rather than requiring schools to adapt to software.

The architecture emphasizes:

- Business correctness
- Clear ownership
- Long-term maintainability
- Consistent terminology
- Separation of responsibilities
- Future scalability

---

# Documentation Structure

The documentation is organized into four layers.

```
Business

↓

Architecture

↓

Architectural Decisions (ADR)

↓

Modules
```

Each layer builds upon the previous one.

---

# Business Layer

The Business layer defines the philosophy of the product.

It explains:

- Why Nexchool exists.
- How schools operate.
- Product vision.
- Business terminology.
- Product principles.

Business documents should be read before architecture documents.

```
server/docs/business/

├── product-vision.md
├── business-principles.md
├── school-terminology.md
└── school-workflows.md
```

---

# Architecture Layer

The Architecture layer defines the core business domains of Nexchool.

These domains remain relatively stable over time.

Current domains include:

- People
- Identity
- Authorization
- Academic

Supporting architecture documents define:

- Engineering Principles
- Naming Conventions
- Domain Interactions

```
server/docs/architecture/

├── engineering-principles.md
├── naming-conventions.md
├── people-domain.md
├── identity-domain.md
├── authorization-domain.md
├── academic-domain.md
└── domain-interactions.md
```

---

# Architectural Decision Records (ADR)

ADRs capture significant architectural decisions.

An ADR records:

- The problem.
- The decision.
- Alternatives considered.
- Long-term consequences.

ADRs explain *why* architectural decisions were made.

They do not replace the architecture documents.

Current ADRs include:

```
ADR-001 Person-Centric Architecture

ADR-002 Family Relationship Model

ADR-003 Identity and Authentication Separation

ADR-004 Active Context

ADR-005 Teacher as Academic Participation

ADR-006 Business Authority Driven Authorization

ADR-007 Admission and Academic Enrollment Separation

ADR-008 Teaching Assignment

ADR-009 Academic Year as Operational Context
```

---

# Module Documentation

Modules implement business workflows using concepts defined by the architecture.

Modules should never redefine business concepts already owned by architecture domains.

Examples include:

- Students
- Teachers
- Attendance
- Examination
- Finance
- Library
- Hostel
- Inventory
- Transport

Every module depends upon one or more architecture domains.

---

# Core Business Domains

The current architecture consists of four foundational domains.

```
People

↓

Identity

↓

Authorization

────────────────────────

Academic
```

Each domain answers a different business question.

| Domain | Question |
|----------|----------|
| People | Who is this person? |
| Identity | How does this person access Nexchool? |
| Authorization | What may this authenticated user do? |
| Academic | How does this person participate in education? |

Together these domains establish the business foundation of the platform.

---

# Domain Responsibilities

## People

Owns:

- Person
- Staff
- Student Relationship
- Family
- Family Member

People represents real human beings known to the school.

---

## Identity

Owns:

- User
- Authentication
- Session
- Active Context

Identity manages access to the platform.

---

## Authorization

Owns:

- Business Authority
- Authority Profiles
- Capabilities
- Business Actions
- Permission Keys

Authorization determines what authenticated users may perform.

---

## Academic

Owns:

- Teacher
- Academic Year
- Academic Structure
- Academic Enrollment
- Teaching Assignment

Academic models educational participation.

---

# Domain Interaction

Business domains collaborate while preserving ownership boundaries.

```
Business Modules

        │

        ▼

Academic

Authorization

        │

        ▼

Identity

        │

        ▼

People
```

Every business concept has exactly one owner.

Modules reference concepts.

They never redefine them.

---

# Development Workflow

Every new feature should follow the same workflow.

```
Business Discussion

↓

Architecture

↓

ADR (if required)

↓

Module Design

↓

Implementation

↓

Code Review

↓

Documentation Update
```

Architecture always precedes implementation.

---

# Reading Order

New developers should read the documentation in the following order.

## Business

1. Product Vision
2. Business Principles
3. School Terminology

---

## Architecture

4. Engineering Principles
5. Naming Conventions
6. People Domain
7. Identity Domain
8. Authorization Domain
9. Academic Domain
10. Domain Interactions

---

## ADRs

Read all ADRs in numerical order.

They explain the architectural reasoning behind the platform.

---

## Modules

Read only the modules relevant to the current feature being implemented.

---

# Architecture Principles

The entire platform follows several guiding principles.

## Business Before Technology

Architecture represents school operations.

Technology implements architecture.

---

## One Business Concept

Every business concept has exactly one owner.

---

## Clear Responsibilities

Each domain owns one business responsibility.

---

## Reuse Before Creation

Reference existing concepts before introducing new ones.

---

## Stable Domains

Business domains should remain stable over time.

Modules evolve around them.

---

## Long-Term Thinking

Architecture decisions should optimize for years of evolution rather than immediate implementation convenience.

---

# Future Evolution

As Nexchool grows, new functionality should generally be introduced as modules.

New business domains should be created only when they represent independent business responsibilities with their own lifecycle and multiple future consumers.

The current architecture is intended to remain stable while supporting long-term platform evolution.

---

# Summary

The Nexchool architecture is organized around business domains rather than technical modules.

Business documents define product philosophy.

Architecture documents define business responsibilities.

ADRs explain architectural decisions.

Modules implement business workflows.

Together these layers establish a consistent foundation that enables Nexchool to evolve without repeated architectural restructuring.
