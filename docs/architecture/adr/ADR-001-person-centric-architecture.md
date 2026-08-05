# ADR-001 — Person-Centric Architecture

## Status

Accepted

---

## Date

2026-08-04

---

# Context

The initial People architecture modeled business participants independently.

```
People

├── Staff

├── Student

└── Family
```

Each participant maintained its own identity and business information.

As product design progressed, several real-world school scenarios exposed limitations in this approach.

Examples included:

- A Teacher who is also the parent of a student.
- A Principal with children studying in the same school.
- A Student who later joins the school as a Teacher.
- A Parent who later becomes a Staff member.
- Multiple organizational responsibilities performed by the same individual.

These scenarios resulted in duplicated personal information and fragmented business relationships.

The architecture no longer reflected how schools actually operate.

---

# Decision

Nexchool adopts a Person-centric architecture.

Every real human known to the school is represented by exactly one Person.

Business participation is modeled through independent business relationships.

```
Person

        │

        ├── Staff

        ├── Student

        └── Family Member
```

Academic participation extends these relationships where appropriate.

For example:

```
Person

↓

Staff

↓

Teacher
```

Authentication remains independent.

```
Person

↓

User (Optional)
```

Person becomes the single source of truth for human identity throughout the platform.

---

# Rationale

Schools interact with people rather than isolated business records.

A single individual may participate in multiple organizational roles during different stages of their relationship with the school.

Examples include:

- Teacher and Parent.
- Principal and Parent.
- Student and Alumni.
- Alumni and Teacher.
- Guardian and Staff.

Representing each participation as a separate Person creates unnecessary duplication and increases long-term maintenance costs.

A Person-centric model more accurately reflects real-world business relationships while preserving a single source of truth for personal identity.

---

# Alternatives Considered

## Option 1

Independent entities.

```
Staff

Student

Family
```

### Advantages

- Simple implementation.
- Easy initial development.

### Disadvantages

- Duplicate personal information.
- Difficult relationship management.
- Multiple records for the same individual.
- Complex synchronization.
- Poor long-term scalability.

Decision:

Rejected.

---

## Option 2

Generic enterprise Person entity.

### Advantages

- Highly reusable.
- Common enterprise pattern.

### Disadvantages

- Focuses on technical abstraction.
- Weak business terminology.
- Does not clearly communicate the school's business model.

Decision:

Rejected.

---

## Option 3

Person-centered business architecture.

### Advantages

- One identity.
- Multiple business relationships.
- Accurate representation of school operations.
- Eliminates duplication.
- Supports future organizational evolution.

Decision:

Accepted.

---

# Consequences

## Positive

- Single source of truth for personal identity.
- No duplicated personal information.
- Supports multiple simultaneous business relationships.
- Simplifies future modules.
- Consistent business terminology.
- Stable foundation for Identity and Academic domains.

---

## Trade-offs

Business relationships become more explicit.

Developers must distinguish between:

- Person
- Staff
- Student
- Family Member
- Teacher
- User

Although this introduces additional concepts, each concept owns a clearly defined responsibility.

---

# Related Documents

- people-domain.md
- identity-domain.md
- academic-domain.md
- authorization-domain.md
- domain-interactions.md