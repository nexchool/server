# Engineering Principles

> Version: 1.0
> Status: Living Document
> Last Updated: 2026-08-03

---

# References

- ../business/product-vision.md

---

# Purpose

This document defines the engineering principles that every contributor to Nexchool must follow.

These principles apply to:

- Architecture
- Backend
- Frontend
- Database
- APIs
- Documentation
- Testing
- AI-assisted development

Whenever implementation conflicts with these principles, implementation should be reconsidered before changing the principles.

---

# Core Philosophy

Business drives technology.

Technology never drives the business.

Every engineering decision should begin by understanding the school workflow, not by selecting a framework, pattern, or abstraction.

---

# Principle 1 — Business First

Before implementing any feature, answer:

- What business problem are we solving?
- Who performs this task?
- How does a school perform this today?
- Why would they use this feature?

Only after these questions are answered should implementation begin.

---

# Principle 2 — Model Reality

The software should represent how schools actually work.

Avoid creating concepts that exist only because they are convenient for software.

Good examples:

- Teacher
- Student
- Staff
- Parent
- Family
- Academic Year
- Section
- Class Teacher

Bad examples:

- Generic Resource
- Generic Entity
- Lifecycle Object
- Business Object

If schools don't use the term, question whether Nexchool should.

---

# Principle 3 — Ubiquitous Business Language

Business terminology should remain consistent across the entire platform.

The same concept should use the same name in:

- Database tables
- Models
- Services
- GraphQL
- REST APIs
- UI
- Documentation
- Jira
- Tests

Example:

If the product uses "Staff",

do not introduce:

- Employee
- Resource
- Personnel

unless they represent different business concepts.

---

# Principle 4 — Simplicity Over Cleverness

Prefer readable code over clever code.

Future developers should understand the implementation quickly.

We optimize for maintainability, not impressiveness.

---

# Principle 5 — Build Domains, Not Modules

Avoid thinking in isolated modules.

Instead, organize the platform into business domains.

Examples:

Identity

People

Academics

Operations

Finance

Communication

Every feature should belong to a domain.

Modules are implementations.

Domains represent the business.

---

# Principle 6 — Single Source of Truth

Every business concept should have one owner.

Examples:

A teacher should have one authoritative record.

A staff member should have one employment status.

A student should have one academic record.

Avoid duplicate sources of truth.

---

# Principle 7 — Backward Compatibility

Whenever possible:

- Prefer additive migrations.
- Avoid breaking APIs.
- Keep compatibility layers during transitions.
- Remove deprecated structures only after migration is complete.

Data migrations should always be reversible where practical.

---

# Principle 8 — Architecture Before Features

Large features should never introduce architecture.

Architecture should exist first.

Features should extend the architecture.

When multiple future features require the same foundation,

build the foundation first.

---

# Principle 9 — Documentation First

Every significant architectural change should include:

- Business reasoning
- Technical reasoning
- Migration strategy
- Alternatives considered

Implementation begins only after the design is documented.

---

# Principle 10 — Evolution Over Rewrites

Architecture should evolve gradually.

Prefer:

Current

↓

Compatibility Layer

↓

Migration

↓

Cleanup

instead of

Current

↓

Complete Rewrite

---

# Principle 11 — Separation of Concerns

Authentication is not identity.

Identity is not responsibility.

Responsibility is not permission.

Permission is not business role.

Each concept should have a clear owner.

---

# Principle 12 — Explicit Relationships

Relationships should be represented explicitly.

Avoid hiding business logic inside:

- Strings
- Status values
- Magic flags
- Conditional code

If a relationship exists in the business,

it should usually exist in the data model.

---

# Principle 13 — Future Proof, Not Future Heavy

We build for the future.

We do not build every future feature today.

Introduce architecture only when:

- it solves an existing problem,
- or it prevents a predictable future migration.

Avoid speculative abstractions.

---

# Principle 14 — AI Is an Engineering Assistant

AI assists implementation.

AI does not define product architecture.

Architecture decisions are made by the product owners and documented in this repository.

AI implementations should follow these documents.

---

# Engineering Checklist

Before merging any feature ask:

## Business

- Does this solve a real school problem?
- Would a school understand this terminology?

## Architecture

- Does it introduce duplicate concepts?
- Does it create multiple sources of truth?
- Does it fit an existing domain?

## Implementation

- Is the code understandable?
- Is the naming consistent?
- Is the migration safe?
- Is documentation updated?

If any answer is "No",

the implementation should be reviewed.

---

# Non-Negotiable Rules

The following rules should never be violated.

1. Business terminology always wins.

2. One source of truth for every business concept.

3. Documentation precedes implementation.

4. No feature introduces architecture without discussion.

5. Backward compatibility is preferred over breaking changes.

6. Every architecture decision should reduce future complexity.

7. Code should tell the story of the business.

---

# Final Principle

We are not building software.

We are modelling how schools operate.

The codebase should become a faithful representation of a school's day-to-day business processes.

Everything else is implementation.