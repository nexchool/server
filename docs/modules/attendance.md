# Attendance

## Purpose

The Attendance module records and manages academic participation throughout the Academic Year.

It provides the business workflows required to record, review, correct and report attendance for students.

Attendance represents participation in academic activities rather than merely recording presence or absence.

The Attendance module does not redefine academic concepts.

Instead, it consumes the academic structure prepared by Academic Management and records participation against that structure.

---

# Business Responsibilities

The Attendance module is responsible for:

- Student Attendance
- Attendance Review
- Attendance Correction
- Attendance Approval
- Attendance Locking
- Attendance Reports
- Attendance Analytics
- Attendance Notifications

The architecture also supports Staff Attendance, although it is implemented as a future capability.

---

# Business Scope

Attendance begins after students are academically enrolled.

Its responsibility continues throughout the Academic Year.

Typical lifecycle:

```
Academic Enrollment

↓

Teaching Assignment

↓

Attendance Recording

↓

Attendance Review

↓

Corrections

↓

Attendance Locked

↓

Reports & Analytics
```

Attendance becomes part of the student's permanent academic history.

---

# Module Ownership

The Attendance module owns the following workflows.

## Student Attendance

Recording participation during academic activities.

---

## Attendance Correction

Correcting incorrectly recorded attendance.

---

## Attendance Approval

Reviewing attendance corrections when approval is required.

---

## Attendance Lock

Preventing unauthorized modification after attendance is finalized.

---

## Attendance Reports

Generating attendance summaries and statistics.

---

## Attendance Analytics

Calculating attendance percentages and trends.

---

## Attendance Notifications

Sending attendance-related notifications to parents and guardians.

---

# What This Module Does NOT Own

The Attendance module intentionally does not own the following business concepts.

| Business Concept | Owner |
|------------------|-------|
| Person | People Domain |
| Student | People Domain |
| Teacher | Academic Domain |
| Academic Year | Academic Domain |
| Academic Enrollment | Academic Domain |
| Teaching Assignment | Academic Domain |
| Authorization | Authorization Domain |

Attendance references these concepts but never redefines them.

---

# Dependencies

The Attendance module depends upon:

## Academic Domain

Provides:

- Academic Year
- Academic Enrollment
- Teaching Assignment

---

## Student Management

Provides:

- Student lifecycle
- Student status

---

## Authorization Domain

Provides:

- Business Authority

---

## Communication Module

Provides:

- Parent Notifications
- Attendance Alerts

---

## Identity Domain

Provides:

- Active Context

---

# Integration Matrix

| Domain / Module | Purpose |
|-----------------|---------|
| Academic | Teaching Assignments |
| Student Management | Student information |
| Authorization | Business Authority |
| Communication | Parent notifications |
| AI | Attendance insights |
| Examination | Eligibility calculations |
| Reports | Attendance reporting |

---

# Operational Roles

Attendance is performed by different users depending upon their responsibilities.

## Operational Users

Responsible for day-to-day attendance recording.

Examples include:

- Class Teacher
- Subject Teacher

---

## Administrative Users

Responsible for monitoring and administration.

Examples include:

- Principal
- Vice Principal

Administrative users normally review attendance rather than recording it.

---

## Emergency Users

Administrative users may perform attendance recording when operational circumstances require it.

Example:

A teacher is absent.

The Principal records attendance from the mobile application.

This represents an operational exception rather than a separate workflow.

---

# Attendance Lifecycle

Every attendance record follows the same lifecycle.

```
Attendance Session

↓

Attendance Recorded

↓

Review

↓

Correction (Optional)

↓

Approval (If Required)

↓

Locked

↓

Reports
```

Once locked, attendance becomes part of the permanent academic record.

---

# Attendance Concepts

Attendance records academic participation.

The module supports multiple attendance strategies.

Examples include:

- Daily Attendance
- Period-wise Attendance

The attendance strategy should be configurable at the organization level.

Different organizations may adopt different operational practices.

---

# Business Principles

The Attendance module follows these principles.

## Academic Participation

Attendance belongs to academic participation.

Students without Academic Enrollment cannot participate.

---

## Teaching Context

Attendance is recorded against Teaching Assignments.

Morning attendance may use a designated homeroom or class attendance configuration.

---

## Mobile First

Attendance is primarily an operational workflow.

Teachers should be able to complete attendance efficiently using the mobile application.

Administrative interfaces focus on monitoring, reporting and exception handling.

---

## Preserve History

Attendance history should never be deleted.

Corrections should remain auditable.

---

## Business Before Technology

Attendance workflows should reflect how schools operate.

Implementation details should never influence business behavior.

---

# Summary

The Attendance module manages the complete attendance lifecycle for students.

It records academic participation using the academic structure prepared by Academic Management while integrating with Student Management, Authorization and Communication.

The module supports operational users, administrative oversight and future expansion to Staff Attendance without changing the underlying business architecture.

# Student Attendance Workflow

## Purpose

The Student Attendance workflow records a student's participation in academic activities during an Academic Year.

Attendance is recorded against the student's current Academic Enrollment and Teaching Assignment.

The objective is to maintain an accurate academic participation record throughout the student's educational journey.

---

## Participants

Primary participants include:

- Class Teacher
- Subject Teacher

Administrative participants include:

- Principal
- Vice Principal

Supporting modules include:

- Academic Domain
- Student Management
- Authorization
- Communication

---

## Workflow

```
Teaching Assignment

↓

Open Attendance Session

↓

Load Students

↓

Record Attendance

↓

Review

↓

Submit

↓

Attendance Recorded
```

Attendance should be simple enough to complete within a few minutes.

---

## Business Outcome

Successful attendance recording creates:

- Attendance Record
- Attendance Timestamp
- Recorded By
- Attendance Status

The attendance record becomes part of the student's academic history.

---

# Attendance Modes

Different schools follow different attendance policies.

The Attendance module supports multiple attendance modes.

## Daily Attendance

Attendance is recorded once per day.

Generally performed by the Class Teacher.

```
School Starts

↓

Attendance

↓

Whole Day
```

---

## Period-wise Attendance

Attendance is recorded for every teaching period.

Generally performed by Subject Teachers.

```
Period 1

↓

Attendance

↓

Period 2

↓

Attendance

↓

...
```

Attendance mode should be configurable at the organization level.

---

# Attendance Status

Attendance status represents the student's participation during the attendance session.

Supported statuses include:

- Present
- Absent
- Late
- Half Day
- Approved Leave

Future attendance statuses may be introduced without changing the workflow.

---

# Attendance Recording

## Purpose

Attendance recording captures participation for a teaching session.

Teachers should be able to complete attendance quickly using the mobile application.

---

## Workflow

```
Open Attendance

↓

Mark Students

↓

Review

↓

Submit
```

Attendance should support:

- Individual selection
- Bulk operations
- Quick corrections before submission

---

## Bulk Attendance

The module should support bulk attendance operations.

Example:

```
Mark All Present

↓

Select Absent Students

↓

Submit
```

This reflects the workflow followed by most schools.

---

# Attendance Correction Workflow

## Purpose

Attendance may require correction after submission.

Examples include:

- Wrong student marked absent.
- Student arrived late.
- Teacher selected the wrong status.

---

## Workflow

```
Attendance Record

↓

Correction Requested

↓

Review

↓

Approve (If Required)

↓

Attendance Updated
```

Organizations may configure whether corrections require approval.

---

# Attendance Approval

Some organizations may require administrative approval before attendance corrections become effective.

Typical approvers include:

- Principal
- Vice Principal

Approval policies should be configurable.

---

# Attendance Lock Workflow

## Purpose

Attendance should eventually become immutable.

Locking prevents unauthorized modification after attendance has been finalized.

---

## Workflow

```
Attendance Recorded

↓

Configured Lock Time

↓

Attendance Locked
```

Examples:

- End of School Day
- 5:00 PM
- Principal Approval

The locking policy should be configurable.

---

# Leave Management

Attendance distinguishes between absence and approved leave.

Examples include:

- Medical Leave
- Personal Leave
- Family Emergency

Approved Leave should not be treated as ordinary absence.

---

## Workflow

```
Leave Approved

↓

Attendance Session

↓

Approved Leave Recorded
```

Attendance statistics should distinguish approved leave from unapproved absence.

---

# Late Arrival

Students arriving after the attendance session may be marked as Late.

Example:

```
Attendance Started

↓

Student Arrives Late

↓

Late Status Recorded
```

Late arrival contributes separately to attendance reporting.

---

# Half Day Attendance

Students may attend only part of the school day.

Examples include:

- Medical Appointment
- Personal Reasons
- School Permission

Half Day represents partial participation rather than absence.

---

# Notifications

Attendance events may trigger notifications.

Examples include:

- Student Marked Absent
- Late Arrival
- Attendance Correction

Notification policies should be configurable.

Parents should receive notifications regardless of which role they are currently using within the application.

If a notification is opened from the mobile device, Nexchool should automatically switch to the appropriate Active Context before displaying the related attendance information.

---

# Attendance Reports

Attendance reports provide operational visibility.

Examples include:

- Daily Attendance
- Monthly Attendance
- Student Attendance Summary
- Section Attendance
- Grade Attendance
- Organization Attendance

Reports should always reference historical attendance records.

---

# Attendance Analytics

The Attendance module calculates attendance metrics.

Examples include:

- Attendance Percentage
- Consecutive Absences
- Late Arrival Statistics
- Leave Statistics

Analytics modules may consume these calculations for dashboards and insights.

---

# Business Rules

## Attendance belongs to Academic Participation.

Students without Academic Enrollment cannot have attendance recorded.

---

## Attendance belongs to Teaching Assignments.

Attendance should reference Teaching Assignments rather than individual Teachers.

---

## Attendance supports multiple recording strategies.

Organizations choose Daily or Period-wise attendance according to their operational policy.

---

## Corrections remain auditable.

Attendance corrections should preserve historical information whenever possible.

---

## Attendance becomes immutable after locking.

Locked attendance should not be modified through normal operational workflows.

---

## Notifications are configurable.

Schools decide which attendance events trigger notifications.

---

## Attendance statistics distinguish Leave from Absence.

Approved Leave should not negatively affect attendance reporting in the same manner as unapproved absence.
