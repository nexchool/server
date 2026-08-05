# ADR-002 — Family Relationship Model

## Status

Accepted

---

## Date

2026-08-04

---

# Context

The original Family model assumed a fixed family structure.

Typical implementations represented families using predefined fields such as:

```
Family

├── Father

├── Mother

└── Guardian
```

Although simple, this model quickly became restrictive when compared with real-world school operations.

Schools regularly encounter family structures that do not fit predefined roles.

Examples include:

- Single-parent families.
- Grandparents acting as guardians.
- Court-appointed guardians.
- Foster parents.
- Relatives acting as emergency guardians.
- Multiple legal guardians.
- Students living with extended family.

As additional exceptions accumulated, the original model required continuous structural changes.

The architecture no longer reflected the diversity of real families.

---

# Decision

Nexchool models a Family as an independent business entity composed of Family Members.

Each Family Member participates through a relationship rather than a predefined database field.

```
Family

        │

        ▼

Family Member

        │

        ▼

Relationship
```

Examples of relationships include:

- Father
- Mother
- Guardian
- Grandfather
- Grandmother
- Uncle
- Aunt
- Brother
- Sister
- Relative
- Foster Parent
- Court-Appointed Guardian

Relationships describe participation within the Family.

They do not change the underlying architecture.

---

# Rationale

Families are business relationships rather than fixed technical structures.

Schools should not need software updates whenever a new family relationship is encountered.

Instead, the architecture should accommodate diverse family structures while maintaining a consistent business model.

Modeling Family Members independently allows Nexchool to support real-world family arrangements without introducing additional database columns or business logic for every variation.

---

# Alternatives Considered

## Option 1

Fixed family structure.

```
Family

├── Father

├── Mother

└── Guardian
```

### Advantages

- Simple implementation.
- Easy to understand.

### Disadvantages

- Inflexible.
- Difficult to extend.
- Does not support many real-world family situations.
- Requires schema changes for additional relationships.

Decision:

Rejected.

---

## Option 2

Separate entity for every relationship.

```
Father

Mother

Guardian

Grandparent

...
```

### Advantages

- Explicit modelling.

### Disadvantages

- Large number of entities.
- Duplicate business logic.
- Difficult maintenance.
- Poor scalability.

Decision:

Rejected.

---

## Option 3

Relationship-based Family model.

```
Family

↓

Family Member

↓

Relationship
```

### Advantages

- Flexible.
- Business-driven.
- Supports real-world schools.
- Eliminates structural duplication.
- Easily extended.

Decision:

Accepted.

---

# Consequences

## Positive

- Supports diverse family structures.
- Removes assumptions about household composition.
- Simplifies future enhancements.
- Provides a stable business model.
- Eliminates repeated schema modifications.

---

## Trade-offs

Family relationships become data rather than database structure.

Developers must distinguish between:

- Family
- Family Member
- Relationship

This introduces an additional level of abstraction but significantly improves long-term flexibility.

---

# Business Examples

## Traditional Family

```
Patel Family

│

├── Father

├── Mother

└── Student
```

---

## Single Parent

```
Sharma Family

│

├── Mother

└── Student
```

---

## Grandparent Guardian

```
Joshi Family

│

├── Grandmother

└── Student
```

---

## Foster Care

```
Family

│

├── Foster Parent

└── Student
```

---

## Court-Appointed Guardian

```
Family

│

├── Guardian

└── Student
```

Each example follows the same architecture.

Only the relationship changes.

---

# Consequences for Future Modules

The Family Relationship Model provides a stable foundation for future modules including:

- Admissions
- Student Profiles
- Fee Management
- Communication
- Emergency Contacts
- Medical Records
- Transport
- Hostel

These modules reference Family relationships rather than assuming predefined parent roles.

---

# Related Documents

- people-domain.md
- identity-domain.md
- authorization-domain.md
- domain-interactions.md

