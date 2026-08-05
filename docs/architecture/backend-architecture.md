# Backend Architecture

## Purpose

This document defines the backend architecture of Nexchool.

It establishes the engineering principles, application layers, communication patterns, and implementation guidelines that every backend component should follow.

The objective is to ensure that business logic remains independent of transport technologies, allowing the platform to evolve without repeated architectural changes.

This document complements the business and architecture documentation by describing how those concepts are implemented within the backend.

---

# Architecture Principles

The backend follows several fundamental principles.

## Business First

Business rules belong to the service layer.

Transport technologies should never contain business logic.

---

## Layer Separation

Each layer has a single responsibility.

Every request should flow through clearly defined layers.

---

## Technology Independence

Business logic should remain independent of:

- REST
- GraphQL
- Background Jobs
- Scheduled Tasks
- Future Event Processing

Changing transport technology should never require rewriting business logic.

---

## Domain Driven Organization

Backend code should be organized around business domains and modules rather than technical concerns.

Business concepts remain the primary organizational unit.

---

## Long-Term Maintainability

Every architectural decision should optimize for long-term evolution rather than short-term implementation convenience.

---

# High-Level Architecture

The backend follows a layered architecture.

```
Clients

│

├── Web

├── Mobile

├── AI

└── Future Integrations

        │

        ▼

REST Controllers

GraphQL Resolvers

        │

        ▼

Application Services

        │

        ▼

Repositories

        │

        ▼

PostgreSQL
```

Transport technologies terminate at the Service Layer.

Business logic begins within the Service Layer.

---

# Layer Responsibilities

## REST Layer

Responsible for:

- Authentication
- File Upload
- File Download
- Health Checks
- Webhooks
- Infrastructure Endpoints

REST should also temporarily expose existing business APIs during migration.

REST must never contain business logic.

---

## GraphQL Layer

Responsible for exposing business capabilities.

GraphQL becomes the primary API layer for:

- Web
- Mobile
- AI
- Internal Dashboards

GraphQL Resolvers should remain thin.

They should delegate all work to Application Services.

---

## Service Layer

The Service Layer is the heart of the backend.

It owns:

- Business Rules
- Validation
- Workflow Orchestration
- Authorization Requests
- Domain Coordination

Every business operation should be implemented exactly once within this layer.

Both REST Controllers and GraphQL Resolvers consume the same Services.

---

## Repository Layer

Repositories own data persistence.

Responsibilities include:

- Database Queries
- Transactions
- Persistence
- Data Mapping

Repositories should never implement business rules.

---

# Dependency Rules

Dependencies always flow downward.

```
Resolver

↓

Service

↓

Repository

↓

Database
```

or

```
Controller

↓

Service

↓

Repository

↓

Database
```

Reverse dependencies are prohibited.

Repositories must never call Services.

Services must never call Controllers or Resolvers.

---

# Module Structure

Every business module should follow the same structure.

```
students/

    routes.py          REST controller (infrastructure + legacy endpoints)

    resolvers.py       GraphQL resolvers

    service.py         Application Service — all business logic

    repository.py      Persistence

    models.py          SQLAlchemy entities

    graphql/           GraphQL types

    schemas/           Request / response schemas
```

This structure should remain consistent across the entire backend.

The backend remains Python / Flask. GraphQL is served from the same application through a Python GraphQL library. Earlier drafts of this document used TypeScript-style filenames; those were illustrative only.

---

# REST Strategy

REST remains part of Nexchool.

However, its responsibility changes.

REST is primarily responsible for infrastructure concerns.

Examples include:

- Login
- Logout
- Token Refresh
- Uploads
- Downloads
- Health Checks
- Webhooks

Existing business REST APIs will gradually migrate to GraphQL.

---

# GraphQL Strategy

GraphQL becomes the primary business API.

It is served at `/api/graphql`. Concerns shared by every operation — request
context (tenant and identity), the error contract, query limits and schema
assembly — live in `graphql_api/`. Modules contribute their own types and
resolvers to that schema; they never build a transport of their own.

Authentication is implemented once, in `core/authentication.py`, and consumed by
both transports. The same is true of tenant resolution in `core/tenant.py`.

All new business features should be exposed through GraphQL.

GraphQL should represent business language rather than database models.

Example:

```
Student

Person

Teaching Assignment

Academic Year
```

Not:

```
StudentEntity

StudentModel

StudentDTO
```

---

# Business Logic

Business logic must exist only within Services.

Example:

```
GraphQL

↓

Student Resolver

↓

Student Service

↓

Repository
```

or

```
REST

↓

Student Controller

↓

Student Service

↓

Repository
```

The Service Layer remains identical regardless of transport technology.

---

# Migration Strategy

The migration from REST to GraphQL should be incremental.

Phase 1

Introduce GraphQL infrastructure.

---

Phase 2

Implement new architecture and Service Layer.

---

Phase 3

Expose new business capabilities through GraphQL.

---

Phase 4

Refactor existing REST endpoints to reuse the new Services.

---

Phase 5

Gradually retire business REST endpoints after frontend migration.

Infrastructure REST endpoints remain.

---

## Route-by-Route Migration

Migration happens while working inside a module, never as a bulk conversion project.

For every route touched during v2 work:

1. Decide where it belongs. Infrastructure concerns (authentication, uploads, downloads, health, webhooks) stay REST. Business capabilities move to GraphQL.

2. A business operation is exposed by exactly one transport. Never duplicate the same operation in REST and GraphQL.

3. After a route migrates to GraphQL and the replacement is verified working, delete the old REST code. Dead code must not remain in the product.

---

# Summary

The Nexchool backend separates business logic from transport technologies through a layered architecture.

REST and GraphQL act as independent API layers while sharing a common Service Layer.

Repositories own persistence.

Services own business behavior.

This separation allows Nexchool to evolve from REST to GraphQL without rewriting business logic or disrupting existing clients.
