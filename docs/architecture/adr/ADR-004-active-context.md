# ADR-004 — Active Context

## Status

Accepted

---

## Date

2026-08-04

---

# Context

As Nexchool evolved into a Person-centric architecture, a single individual could simultaneously participate in multiple business relationships.

Examples include:

- Teacher and Parent.
- Principal and Parent.
- Receptionist and Guardian.
- Teacher and Academic Coordinator.

The initial approach considered creating separate User accounts for each responsibility.

Example:

```
Teacher Login

Parent Login
```

Although simple, this approach introduced several business and usability problems.

Examples included:

- Multiple usernames and passwords.
- Duplicate authentication.
- Separate notification channels.
- Fragmented user experience.
- Duplicate session management.

The architecture no longer represented how people actually participate within schools.

---

# Decision

Nexchool introduces the concept of an Active Context.

A User authenticates once.

After authentication, the User selects the business experience they wish to work within.

```
Person

        │

        ▼

User

        │

        ▼

Authentication

        │

        ▼

Authenticated Session

        │

        ▼

Active Context
```

Examples of Active Context include:

- Teacher
- Parent
- Student
- Staff

Only one Active Context exists at a time.

Changing the Active Context changes the user experience without requiring re-authentication.

---

# Rationale

Authentication establishes identity.

Business relationships establish participation.

Active Context establishes user experience.

These are independent concerns.

A person should not be forced to maintain multiple accounts simply because they perform multiple responsibilities within the same organization.

Active Context allows one authenticated session to present different business experiences while preserving a single identity.

---

# Alternatives Considered

## Option 1

Separate User accounts for every responsibility.

Examples:

```
Teacher Account

Parent Account

Student Account
```

### Advantages

- Simple implementation.
- Familiar architecture.

### Disadvantages

- Multiple credentials.
- Duplicate authentication.
- Fragmented notifications.
- Poor user experience.
- Duplicate session management.

Decision:

Rejected.

---

## Option 2

Single dashboard containing every responsibility simultaneously.

Examples:

Teacher

+

Parent

+

Academic Coordinator

on one screen.

### Advantages

- Single navigation.
- No context switching.

### Disadvantages

- Overwhelming user experience.
- Complex navigation.
- Difficult permission management.
- Poor mobile usability.
- Difficult long-term maintenance.

Decision:

Rejected.

---

## Option 3

Single User with Active Context.

```
User

↓

Authentication

↓

Active Context

↓

Business Experience
```

### Advantages

- One authentication.
- One session.
- Clean user experience.
- Simple navigation.
- Excellent mobile experience.
- Supports multiple responsibilities.
- Scalable architecture.

Decision:

Accepted.

---

# Consequences

## Positive

- One User account.
- One authentication.
- One authenticated session.
- Multiple business experiences.
- Simplified mobile navigation.
- No duplicate identities.
- Consistent notification behavior.
- Supports future organizational growth.

---

## Trade-offs

Developers must distinguish between:

- User
- Business Relationship
- Active Context
- Authorization

Although this introduces another architectural concept, each concept owns a clearly defined responsibility.

---

# Context Switching

Users may change their Active Context without logging in again.

Example:

```
Teacher Context

↓

Switch Context

↓

Parent Context
```

Authentication remains unchanged.

Authorization remains unchanged.

Only the visible application experience changes.

---

# Notifications

Notifications are independent of the currently selected Active Context.

A User receives notifications for every business responsibility they possess.

Example:

Current Context

```
Teacher
```

Incoming Notification

```
Parent

↓

Fee Reminder
```

When the User opens the notification:

```
Open Application

↓

Authenticate Session

↓

Switch Active Context

↓

Navigate to Notification
```

The user does not manually change contexts.

The application performs the context switch automatically.

This behavior mirrors the user experience of modern multi-account applications while preserving a single identity.

---

# Authorization

Active Context never grants or removes authority.

Authorization depends upon:

- Business Authority
- Authority Profiles
- Capabilities
- Business Actions
- Scope

Changing Active Context changes only:

- Navigation.
- Dashboard.
- Menus.
- Default workflows.

Authorization remains identical.

---

# Architectural Impact

The introduction of Active Context enables:

- One Person architecture.
- One User architecture.
- Context-aware mobile applications.
- Cross-context notifications.
- Future multi-responsibility workflows.
- Simplified authentication.
- Consistent business identity.

Without Active Context, Nexchool would require duplicate accounts or significantly more complex user experiences.

---

# Related Documents

- people-domain.md
- identity-domain.md
- authorization-domain.md
- domain-interactions.md
