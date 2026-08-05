# Business Events

> Status: Identified, not published

---

# Purpose

This document names the business events that occur inside Nexchool.

Nothing publishes them today, and no message bus exists. They are written down
now so that services are built to *think* in events — a service that already
knows which business event it represents can publish it later without being
rewritten.

The test of a service is simple: it should be describable as an event that
happened in a school, not as a set of rows that changed.

```
Admission

↓

Person created

↓

Student relationship created

↓

Family linked

↓

Admission completed
```

rather than

```
Insert A

Insert B

Update C
```

---

# People

| Event | Meaning | Raised by |
|-------|---------|-----------|
| PersonCreated | A human became known to the organization | People |
| PersonMerged | Two records were confirmed to describe one human | People |
| StaffJoined | The organization employed a person | People — `employ()` |
| EmploymentEnded | An employment period closed: resigned, retired, dismissed | People |
| StaffRejoined | A former employee began a new employment period | People |
| FamilyCreated | A household became known to the organization | People |
| FamilyMemberAdded | A person joined a family in a stated relationship | People |

---

# Identity

| Event | Meaning | Raised by |
|-------|---------|-----------|
| AccountCreated | A person was given a way to sign in | Identity |
| SignedIn | A session began | Identity |
| SignedOut | A session ended | Identity |
| PasswordChanged | Credentials changed; every session ended | Identity |
| AccountSuspended | Access was withdrawn without touching business records | Identity |
| AccountClosed | Access ended permanently | Identity |
| ActiveContextSwitched | The presented experience changed | Identity |

---

# Academic

| Event | Meaning | Raised by |
|-------|---------|-----------|
| StudentAdmitted | A person became a student of the school | Student Management |
| AcademicEnrollmentCreated | A student was placed for an academic year | Academic |
| SectionTransferred | A student moved within the same academic year | Academic |
| PromotionCompleted | A student advanced to the next academic year | Academic |
| StudentWithdrawn | A student discontinued before completing | Student Management |
| StudentReEnrolled | A withdrawn student resumed | Student Management |
| StudentGraduated | A student completed their education | Academic |
| TeacherParticipationStarted | A staff member began teaching | Academic |
| TeachingAssignmentAssigned | A teacher took responsibility for a subject in a section | Academic |
| ClassTeacherAssigned | A teacher took charge of a section | Academic |
| AcademicYearActivated | A new operational context opened | Academic |
| AcademicYearRolledOver | The next year was prepared from the current one | Academic |

---

# Operations

| Event | Meaning | Raised by |
|-------|---------|-----------|
| AttendanceRecorded | Participation was recorded for a session | Attendance |
| AttendanceCorrected | A recorded attendance was amended | Attendance |
| AttendanceLocked | Attendance became part of the permanent record | Attendance |
| LeaveApproved | Staff leave was granted | Staff Management |
| FeeCollected | A payment was received | Finance |
| ResultsPublished | Assessment outcomes were released | Examination |

---

# Naming

Events are named for what happened, in the past tense, in school language.

Good

```
StudentAdmitted

StaffJoined

PromotionCompleted
```

Avoid

```
StudentUpdated

RecordChanged

EntityProcessed
```

An event named for a table change is not a business event.

---

# When These Become Real

Nothing here should be implemented as an event bus until a consumer needs one.
Identifying them costs nothing and shapes how services are written; building
delivery infrastructure for events nobody consumes would be the speculative
abstraction the engineering principles warn against.

The value today is in the naming: if a service cannot be described by one of
these events, it is probably doing more than one thing.
