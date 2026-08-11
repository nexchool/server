# ADR-003 — Identity and Authentication Separation

## Status

Accepted

---

## Date

2026-08-04

---

# Context

Early versions of Nexchool assumed that every business participant required a User account.

Typical implementations modeled authentication as part of the business identity.

Examples included:

- Teacher Account
- Student Account
- Parent Account
- Receptionist Account

Under this approach, authentication and business participation became tightly coupled.

As the product evolved, several business scenarios demonstrated that this assumption was incorrect.

Examples included:

- A Driver who never logs into Nexchool.
- A Cleaner without a User account.
- A Parent who prefers not to use the mobile application.
- A Student in lower grades without authentication.
- A Teacher who has temporarily left the organization.
- A Staff member whose account is disabled while their employment records remain active.

These scenarios showed that authentication and business identity represent different business concerns.

---

# Decision

Nexchool separates Business Identity from Authentication.

Every human known to the school exists as a Person.

Authentication is optional.

A User account is created only when the person requires access to the platform.

```
Person

        │

        ▼

User (Optional)

        │

        ▼

Authentication

        │

        ▼

Session
```

Business identity exists independently of authentication.

Removing or disabling a User account never removes the Person or their business relationships.

---

# Rationale

Schools manage people regardless of whether they access software.

Authentication exists solely to allow individuals to interact with the platform.

Business identity represents the school's understanding of the individual.

These concerns evolve independently.

Separating them provides a more accurate representation of real-world school operations while simplifying long-term product evolution.

---

# Alternatives Considered

## Option 1

Authentication coupled with business identity.

```
Teacher

↓

Teacher Login
```

### Advantages

- Simple implementation.
- Fewer initial concepts.

### Disadvantages

- Every participant requires authentication.
- Difficult to disable access without affecting business records.
- Tight coupling between identity and authentication.
- Poor long-term flexibility.

Decision:

Rejected.

---

## Option 2

Independent authentication per business relationship.

Examples:

- Teacher Login
- Parent Login
- Student Login

### Advantages

- Familiar implementation.

### Disadvantages

- Duplicate accounts.
- Duplicate authentication.
- Poor user experience.
- Difficult to support multiple responsibilities.

Decision:

Rejected.

---

## Option 3

Independent Business Identity and Authentication.

```
Person

↓

User (Optional)

↓

Authentication
```

### Advantages

- Authentication becomes optional.
- Business identity remains stable.
- Supports multiple responsibilities.
- Simplifies future authorization.
- Enables Active Context.

Decision:

Accepted.

---

# Consequences

## Positive

- Authentication becomes optional.
- Business identity remains independent.
- Supports one User with multiple responsibilities.
- Simplifies authorization architecture.
- Enables future authentication providers.
- Eliminates duplicate accounts.

---

## Trade-offs

Developers must distinguish between:

- Person
- User
- Authentication
- Session

Although this introduces additional concepts, each concept owns a single responsibility and evolves independently.

---

# Business Examples

## Driver

```
Person

↓

Staff

↓

No User
```

The Driver exists within the school.

Authentication is unnecessary.

---

## Primary School Student

```
Person

↓

Student

↓

No User
```

The Student participates academically without requiring platform access.

---

## Teacher

```
Person

↓

Staff

↓

Teacher

↓

User

↓

Authentication
```

The Teacher participates academically and accesses Nexchool using a User account.

---

## Parent

```
Person

↓

Family Member

↓

User
```

Some Parents may access the application.

Others may never require authentication.

Both remain valid business participants.

---

## Disabled Account

```
Person

↓

Staff

↓

Teacher

↓

User

↓

Disabled
```

Disabling the User account removes platform access.

It does not remove:

- Person
- Staff
- Teacher
- Business Authority
- Historical Records

---

# Architectural Impact

Separating Business Identity from Authentication establishes the foundation for several architectural decisions within Nexchool.

It enables:

- One Person architecture.
- Active Context.
- Authorization based on Business Authority.
- Multiple simultaneous business relationships.
- Optional authentication.
- Future authentication providers.
- Mobile-first experiences.

Without this separation, each of these features would require significantly more complex implementations.

---

# Related Documents

- people-domain.md
- identity-domain.md
- authorization-domain.md
- domain-interactions.md

