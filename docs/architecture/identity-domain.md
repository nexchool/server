# Identity Domain

> **Status:** Approved
>
> **Owner:** Product Architecture
>
> **Last Updated:** August 2026

> **Terminology.** This canon's word for a login is **Account** (naming rule
> 17). The code model and table are still named `User` / `users`; those
> technical names remain until a refactor makes renaming them safe. Documents
> always say Account.

---

# Purpose

The Identity Domain defines how people access Nexchool.

Its responsibility is to authenticate people, establish secure sessions, and provide controlled access to the platform without becoming part of the school's business model.

Identity answers the question:

> "How does this person access the system?"

It does **not** answer:

> "Who is this person within the school?"

That responsibility belongs to the People Domain.

The separation between business identity and technical identity is a fundamental architectural principle throughout Nexchool.

---

# Domain Philosophy

Schools know people.

Software knows accounts.

These are not the same thing.

A teacher remains a teacher even if they forget their password.

A parent remains a parent even if they never log into the application.

A student remains enrolled even if the school does not provide them with portal access.

Authentication exists only to grant access to software.

It never defines business identity.

---

# Why This Domain Exists

The Identity Domain exists to solve technical problems without affecting business architecture.

It provides:

- Authentication
- Session management
- Account management
- Access control
- Application context

while remaining completely independent from school operations.

Business domains should never depend on authentication to understand who a person is.

---

# Responsibilities

The Identity Domain is responsible for:

- Accounts
- Authentication
- Session management
- Password management
- Multi-factor authentication
- Login providers
- Access tokens
- Refresh tokens
- Active application context
- Account lifecycle

---

The Identity Domain is NOT responsible for:

- Person information
- Employment
- Student admission
- Teaching
- Families
- Permissions
- Payroll
- Attendance
- Fees
- Academic records

Those responsibilities belong to their respective domains.

---

# Core Concepts

The Identity Domain revolves around two concepts.

- Account
- Active Context

---

# Account

An Account represents a technical identity capable of accessing Nexchool.

An Account exists solely for authentication and application access.

It does not represent a teacher, student, parent, or employee.

Those identities already exist within the People Domain.

---

# Relationship with Person

Every Account belongs to exactly one Person.

```
Person
    │
    └── Account (Optional)
```

A Person may exist without an Account.

Examples include:

- Young students
- Parents without portal access
- Temporary workers
- Visitors
- Former employees

Authentication should never be required for someone to exist within the school's business records.

---

# One Person, One Account

A Person may have at most one Account.

```
Person
        │
        ▼
Account
```

The same individual should never maintain multiple login accounts for different responsibilities.

Examples:

✅ Teacher + Parent → One Account

✅ Receptionist + Parent → One Account

✅ Student → One Account

This simplifies authentication, notifications, auditing, and overall user experience.

---

# Business Identity

Business identity comes entirely from the People Domain.

```
Person

↓

Business Relationships

↓

Staff
Student
Family Member
```

Identity never creates business relationships.

It only provides access to them.

---

# Authentication

Authentication verifies that the Account holder is who they claim to be.

Authentication methods may include:

- Password
- OTP
- Email verification
- Mobile verification
- OAuth
- Single Sign-On

Future authentication methods should integrate into the Identity Domain without affecting business domains.

---

# Session

After successful authentication, Nexchool establishes a secure session.

The session represents the authenticated Account.

It does not determine business identity.

---

# Active Context

> **Implementation status (2026-08-08):** available contexts are derived and
> served today (the GraphQL `me` query). Session-stored context, switching,
> and notification-driven context routing are **deliberately deferred**
> (ADR-011) — under the default family access model nearly everyone holds
> exactly one context. The sections below describe the target design, not
> current behaviour.

A Person may participate in multiple business relationships simultaneously.

Examples include:

- Teacher
- Parent
- Student

Although these relationships exist simultaneously, the application presents one experience at a time.

This experience is called the Active Context.

---

# What is Active Context?

Active Context determines which application experience is currently presented to the person.

It affects:

- Navigation
- Layout
- Available modules
- Home screen
- Menu structure
- Deep linking

Changing the Active Context does not change:

- Authentication
- Business identity
- Permissions
- Relationships

Only the user experience changes.

---

# Example

Rahul Sharma

```
Person

├── Staff
│      └── Teacher
│
├── Family Member
│
└── Account
```

Available contexts:

- Teacher
- Parent

Current Active Context:

```
Teacher
```

Switching to Parent does not create another session.

It simply changes the application experience.

---

# Context Switching

A person may switch between available contexts without logging out.

Example:

```
Teacher

↓

Parent
```

The application updates:

- Navigation
- Dashboard
- Menus
- Landing pages

The authenticated session remains unchanged.

---

# Context Persistence

The application remembers the person's last Active Context.

Example:

```
Last Active Context

Teacher
```

Reopening the application restores the previous experience automatically.

---

# Notifications

Notifications belong to the Person.

They are never tied to the current Active Context.

A Person receives notifications for every business relationship they possess.

Examples:

Teacher notification:

- Attendance pending

Parent notification:

- Fee reminder

Both notifications should be delivered regardless of the currently selected context.

---

# Notification Routing

Each notification contains contextual information.

Example:

```
Recipient

Person

Target Context

Parent

Target Screen

Fees

Deep Link

/children/fees
```

When the person opens the notification:

1. Authenticate session if required.
2. Switch Active Context automatically.
3. Navigate to the requested screen.
4. Display the notification.

The context switch should happen transparently.

The person should never manually switch contexts to open a notification.

---

# Permissions

Permissions determine what a person may access.

The Active Context determines how the application is presented.

These are different concepts.

Example:

A Principal may have permission to:

- Attendance
- Payroll
- Reports
- Admissions

While using the Teacher context, only the Teacher experience is displayed.

Switching contexts changes the presentation.

Permissions continue to enforce authorization independently.

Detailed permission architecture is defined within the Authorization Domain.

---

# Account Lifecycle

Typical lifecycle:

```
Person Created

↓

Account Created (Optional)

↓

Authentication Enabled

↓

Active Usage

↓

Account Disabled

↓

Account Archived
```

Disabling an Account never deletes the underlying Person.

---

# Future Authentication

The Identity Domain should support future authentication providers without changing business architecture.

Examples include:

- Google
- Microsoft
- Apple
- Government Identity Providers
- Enterprise SSO

Business domains should remain completely unaware of how authentication occurs.

---

# Security Principles

Identity follows several architectural principles.

## Authentication never defines business identity.

---

## One Person owns at most one Account.

---

## Sessions belong to Accounts.

---

## Context belongs to the application experience.

---

## Permissions belong to authorization.

---

## Business relationships belong to the People Domain.

---

# Non Goals

The Identity Domain does not model:

- Teachers
- Students
- Parents
- Staff
- Families
- Departments
- Designations
- Classes
- Payroll
- Academic records

These concepts belong to their respective business domains.

---

# Summary

The Identity Domain provides secure access to Nexchool while remaining independent from the school's business model.

A Person may optionally receive an Account to access the platform.

Each Account authenticates once, maintains a single session, and may switch between multiple application contexts without creating additional accounts or logging in again.

Business identity remains the responsibility of the People Domain.

Authentication simply enables access to that identity.

This separation ensures that Nexchool remains secure, scalable, maintainable, and aligned with real-world school operations while supporting future authentication methods and application experiences without architectural changes.
