# ADR-009 — Academic Year as the Operational Context

## Status

Accepted

---

## Date

2026-08-04

---

# Context

Traditional School ERP systems often treat Academic Year as a property of individual records.

Each module independently stores and filters Academic Year information.

Examples include:

- Attendance
- Homework
- Examination
- Report Cards
- Fees
- Transport

Although functional, this approach creates duplicated filtering logic across the application.

As Nexchool evolved, it became clear that Academic Year influences nearly every operational workflow performed by a school.

School administrators naturally think in terms of:

> "Show me everything for Academic Year 2026–2027."

rather than:

> "Filter each module individually."

This indicated that Academic Year represents more than academic information.

It defines the operational context of the application.

---

# Decision

Nexchool treats Academic Year as the application's primary operational context.

The currently selected Academic Year automatically scopes business operations throughout the platform.

```
Academic Year

        │

        ▼

Application Context

        │

        ├── Students

        ├── Attendance

        ├── Examination

        ├── Homework

        ├── Timetable

        ├── Reports

        ├── Analytics

        └── Future Modules
```

Modules should automatically operate within the currently selected Academic Year unless a business workflow explicitly requires historical information.

---

# Rationale

Schools operate one Academic Year at a time.

Teachers.

Students.

Principals.

Accountants.

Administrators.

All naturally think within the currently active Academic Year.

Making Academic Year the operational context aligns the software with real-world school administration while eliminating repeated filtering throughout the application.

---

# Alternatives Considered

## Option 1

Module-specific Academic Year filtering.

Examples:

Attendance

↓

Select Academic Year

Homework

↓

Select Academic Year

Examination

↓

Select Academic Year

### Advantages

- Simple implementation.
- Independent modules.

### Disadvantages

- Duplicate filtering.
- Inconsistent user experience.
- Increased implementation effort.
- Higher maintenance cost.
- Frequent user interaction.

Decision:

Rejected.

---

## Option 2

Global Academic Year Operational Context.

```
Academic Year

↓

Application Context

↓

Modules
```

### Advantages

- Consistent user experience.
- Centralized filtering.
- Reduced implementation complexity.
- Better reporting.
- Easier historical navigation.
- Scalable architecture.

Decision:

Accepted.

---

# Consequences

## Positive

- Every module behaves consistently.
- Historical navigation becomes straightforward.
- Reporting becomes simpler.
- Analytics become more accurate.
- Future modules inherit the same behavior.
- Less duplicated filtering logic.

---

## Trade-offs

Modules must respect the currently active Academic Year.

Developers should avoid implementing independent Academic Year selection unless required by a specific business workflow.

---

# Operational Context

Academic Year defines the default operating scope of the application.

Examples include:

Current Context

```
Academic Year

2026–2027
```

Automatically scopes:

- Students
- Attendance
- Homework
- Timetable
- Examination
- Lesson Planning
- Reports
- Academic Analytics

The user should not repeatedly select the Academic Year within individual modules.

---

# Historical Navigation

Changing the Academic Year changes the operational context rather than modifying historical records.

Example:

```
Current Context

2026–2027

↓

Student

↓

Grade 8
```

Switch Academic Year

```
2024–2025

↓

Same Student

↓

Grade 6
```

The Person remains unchanged.

Historical data remains unchanged.

Only the application's operational context changes.

---

# Module Responsibilities

Modules should automatically respect the current Academic Year.

Examples include:

Attendance

↓

Attendance Records

Homework

↓

Homework List

Examination

↓

Assessments

Transport

↓

Student Assignments

Finance

↓

Academic-Year specific fees

Reports

↓

Academic reports

Modules should not independently determine the current Academic Year.

---

# Multiple Programmes

**Correction (2026-08-08).** This section originally said each Programme owns
its own Academic Years. ADR-012 settled the opposite, and v1 was right: the
Academic Year belongs to the organization — a trust running CBSE and GSEB has
one 2026-27, not two. What varies per Programme (terms, promotion rules,
academic structure) attaches to the (Programme, Academic Year) pair.

Academic Years are organizational and shared across Programmes.

For organizations operating multiple Programmes, the operational context is therefore the combination of Programme and Academic Year.

Single-Programme schools simply select the Academic Year.

---

# Cross-Domain Interaction

Academic Year belongs to the Academic Domain.

Business modules reference the selected Academic Year through the application context.

No module owns Academic Year.

No module duplicates Academic Year logic.

This preserves a single source of truth.

---

# Business Examples

## Principal Reviews Previous Year

```
Current Context

↓

2026–2027

↓

Dashboard
```

Switch

```
2025–2026

↓

Entire application updates
```

The Principal immediately views the previous Academic Year without manually filtering each module.

---

## Teacher Reviews Previous Student Performance

```
Current Context

↓

2024–2025

↓

Attendance

↓

Homework

↓

Examination

↓

Report Card
```

All modules reference the same Academic Year.

---

## Student Promotion

```
Academic Year

2026–2027

↓

Grade 8
```

Switch

```
Academic Year

2027–2028

↓

Grade 9
```

The Student remains the same.

Academic participation changes according to the selected operational context.

---

# Architectural Impact

Treating Academic Year as the operational context establishes a consistent interaction model throughout Nexchool.

This decision enables:

- Consistent module behavior.
- Simplified reporting.
- Historical navigation.
- Future analytics.
- AI contextual understanding.
- Reduced implementation complexity.
- Improved user experience.

Without this decision, every module would independently manage Academic Year filtering, increasing duplication and reducing consistency.

---

# Related Documents

- academic-domain.md
- domain-interactions.md
- ADR-007-admission-vs-academic-enrollment.md
