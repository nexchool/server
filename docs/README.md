# Nexchool Documentation

Welcome to the Nexchool architecture documentation.

This documentation is the single source of truth for the product, business rules, architecture and engineering decisions that define Nexchool.

Every implementation decision should originate from these documents.

Code follows documentation.

Documentation does not follow code.

---

# Documentation Philosophy

Nexchool is designed as a long-term School ERP platform.

The objective is not to build software that works today.

The objective is to build a platform that continues evolving over the next decade without repeated architectural rewrites.

Every document within this repository exists to preserve that vision.

---

# Development Workflow

Every feature should follow the same lifecycle.

```
Business Discussion

↓

Architecture Decision

↓

Documentation

↓

ADR (If Required)

↓

Implementation

↓

Code Review

↓

Documentation Update
```

Architecture always precedes implementation.

Implementation should never become the source of truth.

---

# Engineering Principles

The following principles guide every engineering decision.

## Business Before Technology

Business requirements define architecture.

Technology serves the business.

Never redesign business workflows simply to accommodate a framework or library.

---

## Documentation First

Business concepts should be documented before implementation begins.

Documentation should answer:

- Why the feature exists.
- What business problem it solves.
- Which domain owns it.
- How it interacts with the rest of the platform.

---

## Single Source of Truth

Business concepts should have exactly one owner.

Examples:

- Person belongs to the People Domain.
- Teaching Assignment belongs to the Academic Domain.
- Authentication belongs to the Identity Domain.
- Business Authority belongs to the Authorization Domain.

Modules consume these concepts.

They do not redefine them.

---

## Business Language

Business terminology should remain consistent across:

- Documentation
- Database
- Backend
- GraphQL
- REST
- Frontend
- Mobile
- AI
- Tests

Avoid introducing technical terminology where business terminology exists.

---

## Preserve History

Historical records should never be overwritten.

Business events create history.

History should remain available for reporting, auditing and future reference.

---

## Long-Term Evolution

Architectural decisions should optimize for the next five to ten years.

Avoid introducing shortcuts that simplify today's implementation while creating tomorrow's migration.

---

# Architecture Overview

The backend is organized around business domains.

```
People

Identity

Authorization

Academic

Finance

Operations

Communication
```

Domains define business concepts.

Modules implement business workflows.

---

# Documentation Structure

```
docs/

├── business/
│
│   Product direction and business language.
│
├── architecture/
│
│   Core architecture and engineering decisions.
│
├── modules/
│
│   Business workflows implemented by the platform.
│
└── architecture/adr/
│
│   Architectural Decision Records.
```

---

# Reading Order

Developers should read the documentation in the following order.

## Business

1. Product Vision
2. Business Principles
3. School Terminology
4. School Workflows

---

## Architecture

5. Engineering Principles
6. Naming Conventions
7. People Domain
8. Identity Domain
9. Authorization
10. Academic Domain
11. Domain Interaction
12. Backend Architecture

---

## ADRs

Read Architectural Decision Records to understand why important architectural choices were made.

---

## Modules

Module documentation explains how business workflows are implemented.

Examples include:

- Student Management
- Staff Management
- Academic Management
- Attendance

Future modules should follow the same documentation pattern.

---

# Implementation Principles

Implementation should always respect the following rules.

## Services own business logic.

Business logic belongs only within the Service Layer.

---

## Transport layers remain thin.

REST and GraphQL expose business capabilities.

They never implement business rules.

---

## Modules remain independent.

Each module owns its own workflows while consuming shared business concepts from architecture domains.

---

## No duplicate business concepts.

If a business concept already exists within another domain, reference it.

Do not recreate it.

---

## Backward compatibility is temporary.

During architecture migration, REST and GraphQL may coexist.

The Service Layer remains the single source of business behavior.

---

# Architecture Freeze

The current architecture should be considered stable.

Architectural changes should occur only when:

- Business requirements change.
- An architectural flaw is discovered.
- A new ADR is approved.

Implementation should not gradually redefine architecture.

---

# AI Development

AI is a first-class development participant within Nexchool.

Different AI systems may participate in:

- Architecture
- Documentation
- Implementation
- Code Review
- Testing

Regardless of implementation tooling, every AI system should treat this documentation as the highest source of truth.

Implementation should follow documentation.

Documentation should never be reverse-engineered from implementation.

---

# Project Vision

Nexchool is not being built as a collection of CRUD modules.

It is being built as a business platform that accurately represents how schools operate.

Every domain, workflow, module and architectural decision should move the platform closer to that objective.

The quality of the platform will not be measured by the number of implemented features.

It will be measured by the correctness, consistency and maintainability of the business architecture behind those features.

---

# Final Principle

Whenever an implementation decision is uncertain, ask the following question:

> **"Does this accurately represent how a real school operates?"**

If the answer is no, revisit the business discussion before writing code.

Business correctness should always take precedence over implementation convenience.
