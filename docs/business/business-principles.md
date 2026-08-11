# Business Principles

> Version: 1.0
> Status: Living Document
> Last Updated: 2026-08-03

---

# References

- product-vision.md
- school-terminology.md
- ../architecture/engineering-principles.md
- ../architecture/naming-conventions.md

---

# Purpose

This document defines the business principles that guide every product decision in Nexchool.

It exists to answer one question:

> "How do we decide whether a feature or architecture is correct?"

This document is the decision framework for the entire platform.

Whenever a product, architecture, or engineering discussion arises, these principles should be consulted before implementation.

---

# Principle 1 — The School Is Always Right

Nexchool exists to serve schools.

The software should adapt to school workflows.

Schools should never be forced to adapt to software limitations.

If the real-world workflow differs from our implementation, our implementation should be questioned first.

---

# Principle 2 — Model Reality

Every entity in Nexchool should represent something that actually exists inside a school.

Examples

- Student
- Staff
- Family
- Subject
- Academic Year
- Class
- Section

Avoid creating entities that only exist because they simplify implementation.

---

# Principle 3 — Business Before Code

Every feature must solve a real business problem.

Before implementation ask:

- Who uses this?
- Why do they need it?
- How do they perform this today?
- What business value does this create?

If these questions cannot be answered, the feature should not be built.

---

# Principle 4 — One Business Concept, One Owner

Every business concept should have a single source of truth.

Examples

A Staff member should exist in one place.

A Family should exist in one place.

A Student should exist in one place.

A Designation should exist in one place.

Avoid duplicate ownership.

---

# Principle 5 — Responsibilities Are Not Designations

A person's designation and responsibilities are different business concepts.

Examples

Designation

- Teacher
- Principal
- Receptionist

Responsibilities

- Class Teacher
- Academic Coordinator
- Examination Coordinator
- Transport Manager

Responsibilities may change frequently.

Designations usually do not.

The software should model both independently.

---

# Principle 6 — Authentication Is Not Identity

Having a login account does not define who a person is.

A person may exist without logging into the system.

Authentication should remain independent from business identity.

---

# Principle 7 — Roles Are Not Permissions

Business Roles

Teacher

Principal

Receptionist

Accountant

describe who someone is.

Permissions describe what they are allowed to do.

Never combine these concepts.

---

# Principle 8 — Build Foundations Before Features

If multiple future features require the same architecture,

build the architecture first.

Avoid repeatedly solving the same problem.

---

# Principle 9 — Architecture Evolves

The architecture should evolve through small, controlled migrations.

Prefer

Current

↓

Compatibility Layer

↓

Migration

↓

Cleanup

Avoid

Current

↓

Rewrite

---

# Principle 10 — Real Business Events

Every status should represent a meaningful business event.

Bad

- Active
- Inactive

Good

- Working
- Suspended
- Left
- Retired

The software should explain what actually happened.

---

# Principle 11 — Minimize Future Rewrites

During early development we accept larger architectural changes if they significantly reduce future migration cost.

Before schools begin using Nexchool in production, architecture correctness is more important than implementation speed.

Once production schools are onboarded, backward compatibility becomes a much higher priority.

---

# Principle 12 — Business Language Everywhere

The same terminology should appear in:

- UI
- Backend
- Database
- APIs
- Documentation
- Jira
- Product discussions

Everyone should speak the same language.

---

# Principle 13 — Every Screen Answers One Question

Every screen should solve one clear business problem.

Examples

Teachers

"Who works in my school?"

Students

"Who studies in my school?"

Attendance

"Who was present today?"

Fees

"Who has paid?"

Avoid combining unrelated workflows into a single screen.

---

# Principle 14 — Business First, Configuration Second

Default workflows should reflect how most schools operate.

Only introduce configuration when there is a genuine business variation across schools.

Configuration should solve differences between schools, not compensate for poor architecture.

---

# Principle 15 — Prefer Evolution Over Abstraction

Do not introduce generic abstractions simply because they might be useful.

Only generalize after identifying real duplication.

A shared architecture should emerge from repeated business needs.

---

# Principle 16 — Think in Domains

Nexchool is built as business domains.

Examples

Identity

People

Academics

Finance

Operations

Communication

Features belong inside domains.

Domains should remain independent wherever practical.

---

# Principle 17 — Every New Entity Must Justify Its Existence

Before introducing a new entity ask:

- Does this exist in a real school?
- Is this different from an existing concept?
- Does this simplify the business?
- Will schools understand it?

If not,

do not introduce it.

---

# Principle 18 — Documentation Is Part of the Product

Architecture documentation is not optional.

Every significant business or architecture decision must be documented before implementation.

The documentation is the source of truth.

The code is an implementation of that truth.

---

# Principle 19 — Product Decisions Outlive Technology

Frameworks change.

Programming languages change.

Databases change.

Business processes change slowly.

Always optimize for business longevity rather than technical trends.

---

# Principle 20 — The Five-Year Test

Before approving any major decision ask:

Will this still make sense five years from now?

If the answer is no,

reconsider the design.

---

# Decision Checklist

Before approving any feature or architecture:

Business

- Is this a real school concept?
- Does it solve a real problem?
- Will schools naturally understand it?

Architecture

- Does it introduce duplicate concepts?
- Does it reduce future migration effort?
- Does it fit an existing domain?

Implementation

- Can developers understand it?
- Can AI consistently implement it?
- Can future contributors extend it?

Only when all three perspectives align should implementation begin.

---

# Final Principle

Nexchool is not a collection of software modules.

It is a digital representation of how schools operate.

Every decision should make that representation more accurate, more maintainable, and easier for schools to understand.
