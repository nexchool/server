# ADR-006 — Business Authority Driven Authorization

## Status

Accepted

---

## Date

2026-08-04

---

# Context

Early versions of Nexchool followed a traditional Role-Based Access Control (RBAC) model.

Typical implementations assigned permissions directly to application roles.

Example:

```
Teacher

↓

student.read

attendance.create

homework.create
```

As the architecture evolved, several limitations became apparent.

Examples included:

- Teachers promoted to Academic Coordinators.
- Vice Principals temporarily acting as Principals.
- Temporary examination responsibilities.
- Schools introducing custom organizational positions.
- Multiple responsibilities assigned to the same Staff member.

Managing authorization through application roles increasingly reflected software implementation rather than how schools actually operate.

---

# Decision

Nexchool adopts a Business Authority driven authorization model.

Business authority originates from the school's organizational structure.

Authorization is derived from that authority rather than assigned directly to User accounts.

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

Permission Keys remain an implementation detail.

Business Authority remains the primary architectural concept.

---

# Rationale

Schools assign responsibilities rather than software permissions.

Examples include:

- Principal
- Teacher
- Receptionist
- Accountant
- Librarian
- Academic Coordinator

A Principal does not think:

> Give Rahul "attendance.record".

Instead, the Principal thinks:

> Rahul is now the Academic Coordinator.

That organizational decision naturally carries authority.

The Authorization Domain translates that authority into software capabilities.

This approach aligns software behavior with real-world school administration.

---

# Alternatives Considered

## Option 1

Traditional RBAC.

```
Role

↓

Permissions
```

### Advantages

- Familiar architecture.
- Easy initial implementation.
- Widely supported.

### Disadvantages

- Software-centric terminology.
- Difficult to evolve.
- Large numbers of permissions.
- Encourages user-specific permission management.
- Poor alignment with school operations.

Decision:

Rejected.

---

## Option 2

Direct User Permissions.

```
User

↓

Permissions
```

### Advantages

- Maximum flexibility.

### Disadvantages

- Difficult administration.
- High maintenance.
- Permission duplication.
- Inconsistent organizational behavior.

Decision:

Rejected.

---

## Option 3

Business Authority driven authorization.

```
Business Authority

↓

Authority Profile

↓

Capabilities

↓

Business Actions

↓

Permission Keys
```

### Advantages

- Business-first architecture.
- Reusable authorization.
- Easier administration.
- Organizational consistency.
- Long-term scalability.

Decision:

Accepted.

---

# Consequences

## Positive

- Authorization reflects organizational structure.
- Reduced administrative effort.
- Reusable Authority Profiles.
- Business terminology throughout the platform.
- Cleaner separation between business and implementation.
- Easier long-term maintenance.

---

## Trade-offs

The authorization model introduces several business concepts.

Developers must understand:

- Business Authority
- Authority Profile
- Capability
- Business Action
- Permission Key

Although more concepts exist, each owns a single responsibility.

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

Schools should begin using these profiles immediately without creating authorization from scratch.

---

# School Authority Profiles

Schools may customize authorization when necessary.

Examples include:

- Academic Coordinator
- Examination Coordinator
- Olympiad Coordinator
- Discipline Coordinator

Schools extend the authorization model by creating or modifying Authority Profiles rather than assigning individual permissions to users.

This customization remains optional.

---

# Capabilities

Capabilities represent business operations.

Examples include:

Academic

- Student Attendance
- Homework
- Examination

Finance

- Fee Collection

Transport

- Vehicle Management

Communication

- Announcements

Capabilities use business terminology rather than technical terminology.

---

# Business Actions

Capabilities expose one or more Business Actions.

Examples:

Student Attendance

- View Attendance
- Record Attendance
- Edit Attendance
- Lock Attendance

Homework

- Create Homework
- Publish Homework
- Archive Homework

Business Actions describe school operations rather than CRUD operations whenever practical.

---

# Permission Keys

Permission Keys are internal implementation identifiers.

Examples include:

```
student_attendance.record

student_attendance.edit

fee.collect

report_card.publish
```

Permission Keys are consumed by:

- Backend Services
- Authorization Middleware
- APIs
- GraphQL Resolvers

Permission Keys should never be exposed to school administrators.

---

# Temporary Delegation

Schools occasionally delegate authority temporarily.

Examples include:

- Principal on leave.
- Vice Principal acting as Principal.
- Temporary Examination Coordinator.

Delegation should contain:

- Authority being delegated.
- Effective date.
- Expiration date.
- Optional business reason.

Delegation automatically expires.

It should remain an exception rather than the primary authorization model.

---

# Active Context

Authorization is independent of Active Context.

Changing between:

- Teacher
- Parent
- Student

changes only the user experience.

Business Authority remains unchanged.

Authorization remains unchanged.

---

# Architectural Impact

Business Authority becomes the source of every authorization decision within Nexchool.

Future modules including:

- Attendance
- Examination
- Finance
- Library
- Hostel
- Payroll
- AI
- Inventory

should derive authorization through the Authorization Domain rather than implementing independent permission systems.

This establishes a single authorization model for the entire platform.

---

# Related Documents

- authorization-domain.md
- people-domain.md
- identity-domain.md
- academic-domain.md
- domain-interactions.md
