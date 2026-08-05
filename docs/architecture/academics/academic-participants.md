# Academic Participants

The Academic Domain defines how people participate in the educational activities of a school.

It does not create people.

It does not employ staff.

It does not authenticate users.

Instead, it defines how existing people participate in the academic operations of the school.

The Academic Domain recognizes two primary academic participants.

- Teacher
- Student

Both participants originate from the People Domain.

Their academic responsibilities and lifecycle belong entirely to the Academic Domain.

---

# Teacher

A Teacher represents a Staff member who participates in academic activities.

Teaching is an academic specialization of Staff rather than an employment designation.

```
Person

        │

        ▼

Staff

        │

        ▼

Teacher
```

This separation allows employment and academic participation to evolve independently.

A Staff member may never become a Teacher.

Examples include:

- Receptionist
- Accountant
- Driver
- Office Administrator
- Maintenance Staff

Likewise, every Teacher must first exist as a Staff member.

Teacher can never exist independently of Staff.

---

# Teacher Responsibilities

The Academic Domain is responsible for a Teacher's academic responsibilities.

Examples include:

- Delivering academic instruction
- Teaching assigned subjects
- Evaluating student performance
- Conducting examinations
- Recording academic progress
- Providing academic guidance

Employment-related information such as designation, joining date, employment type, and employment status remain within the People Domain.

---

# Teacher Categories

The Academic Domain does not distinguish between:

- Permanent Teachers
- Visiting Teachers
- Contract Teachers
- Temporary Teachers

These are employment characteristics rather than academic concepts.

From an academic perspective, every Teacher participates through the same academic model.

---

# Student

A Student represents a Person who has been admitted into the school.

However, becoming a Student does not automatically establish academic participation.

Academic participation begins only after Academic Enrollment.

This distinction reflects how schools actually operate.

---

# Admission vs Academic Enrollment

Admission and Academic Enrollment solve different business problems.

Admission answers:

> Has this person become a student of the school?

Academic Enrollment answers:

> Where does this student participate academically?

These concepts should remain independent throughout the platform.

---

# Admission

Admission establishes the Student relationship between the Person and the school.

```
Person

        │

        ▼

Student Relationship
```

Admission confirms that the school has accepted the student.

Admission does not determine:

- Academic Year
- Academic Division
- Grade
- Section
- Subjects

Those decisions belong to Academic Enrollment.

---

# Academic Enrollment

Academic Enrollment represents a student's participation within the Academic Structure.

It connects the Student to a specific academic context.

An Academic Enrollment defines:

- Academic Year
- Academic Division
- Grade
- Section

```
Student Relationship

        │

        ▼

Academic Enrollment

        │

        ▼

Academic Structure
```

Without Academic Enrollment, a Student cannot participate in academic activities.

---

# Why Academic Enrollment Exists

Separating Admission from Academic Enrollment allows Nexchool to support real-world school operations.

Examples include:

- Admission completed before the academic year begins.
- Grade allocation pending.
- Section allocation pending.
- Student transferred to another Section.
- Student repeats an Academic Year.
- Student temporarily suspends studies.
- Student rejoins after a leave of absence.

These scenarios modify Academic Enrollment rather than the Student relationship.

---

# Student Status

The Student relationship represents the student's long-term association with the school.

Typical business states include:

- Active
- Inactive
- Suspended
- Graduated
- Transferred

These states describe the student's overall relationship with the school.

Graduation does not remove the Student relationship.

It simply changes its lifecycle state.

---

# Academic Enrollment Status

Academic Enrollment has its own independent lifecycle.

Typical states include:

- Pending
- Active
- Completed
- Cancelled

Enrollment status represents participation within a particular Academic Year.

It does not affect the Student relationship itself.

---

# Enrollment Lifecycle

The typical lifecycle is illustrated below.

```
Admission Approved

↓

Student Relationship Created

↓

Academic Enrollment

↓

Promotion

↓

Academic Enrollment

↓

Promotion

↓

Academic Enrollment

↓

Graduation
```

Throughout this process:

- The Person remains the same.
- The Student relationship remains the same.
- Academic Enrollment evolves over time.

---

# Teaching Assignment

Teaching Assignment is one of the central business concepts within the Academic Domain.

It represents the academic responsibility assigned to a Teacher during a specific Academic Year.

Teaching Assignment is not simply a relationship between a Teacher and a Subject.

It represents the school's decision that a particular Teacher is responsible for delivering instruction within a defined academic context.

---

# Why Teaching Assignment Exists

Without Teaching Assignment, every academic module would independently recreate the relationship between:

- Teacher
- Subject
- Grade
- Section
- Academic Year

This would duplicate business logic throughout the platform.

Instead, Nexchool introduces Teaching Assignment as a shared academic reference.

```
Teacher

        │

        ▼

Teaching Assignment

        │

        ▼

Academic Structure
```

Academic modules reference Teaching Assignments rather than rebuilding academic relationships independently.

---

# Teaching Assignment Defines

Every Teaching Assignment identifies:

- Teacher
- Academic Year
- Subject
- Grade
- Section

Future academic modules may reference the Teaching Assignment, including:

- Attendance
- Timetable
- Homework
- Lesson Planning
- Examination
- Academic Analytics
- AI Academic Assistance

Teaching Assignment serves as the common academic reference for these modules.

---

# Teaching Assignment is NOT

Teaching Assignment is not:

- Employment
- Designation
- Permission
- Timetable
- Schedule

It simply defines academic responsibility.

---

# Class Teacher

Class Teacher represents an academic responsibility assigned to a Teacher for a particular Section during an Academic Year.

It is not an employment designation.

It is not part of the Staff relationship.

It belongs entirely to the Academic Domain.

Example:

```
Academic Year

2026–2027

↓

Grade 5A

↓

Class Teacher

↓

Mrs. Mehta
```

The same Section may have a different Class Teacher in another Academic Year.

---

# Subject Teacher

A Subject Teacher participates through one or more Teaching Assignments.

Example:

```
Rahul Sharma

↓

Teaching Assignment

↓

Mathematics

↓

Grade 8A
```

The same Teacher may receive multiple Teaching Assignments.

Examples include:

- Grade 8A Mathematics
- Grade 8B Mathematics
- Grade 9A Mathematics

Each Teaching Assignment represents an independent academic responsibility.

---

# Academic Participation

Teachers and Students participate differently within the Academic Structure.

Teachers participate through:

- Teaching
- Evaluation
- Academic Guidance

Students participate through:

- Academic Enrollment
- Learning
- Academic Progress

Both participants interact through the same Academic Structure.

---

# Promotion

Promotion represents academic progression between Academic Enrollments.

Promotion belongs entirely to the Academic Domain.

Example:

```
Academic Year

2026–2027

↓

Grade 8A

↓

Promotion

↓

Academic Year

2027–2028

↓

Grade 9A
```

Promotion creates the student's next Academic Enrollment.

It does not create another Person.

It does not create another Student relationship.

---

# Graduation

Graduation marks the successful completion of a student's academic journey.

Graduation updates the Student lifecycle.

It does not remove the Student relationship.

Example:

```
Student Status

Graduated
```

Graduated students remain available through historical Academic Years.

This preserves the complete academic history of the school.

---

# Academic Lifecycle

A typical academic journey is illustrated below.

```
Person

↓

Student Relationship

↓

Admission

↓

Academic Enrollment

↓

Promotion

↓

Academic Enrollment

↓

Promotion

↓

Academic Enrollment

↓

Graduation
```

Only the Academic Enrollment changes throughout the student's educational journey.

The underlying Person and Student relationship remain unchanged.

---

# Business Rules

The following architectural principles apply throughout the Academic Domain.

## Every Teacher must be Staff.

Teacher cannot exist independently.

---

## Admission and Academic Enrollment are separate business concepts.

Admission establishes the Student relationship.

Academic Enrollment establishes academic participation.

---

## Every Academic Enrollment belongs to an Academic Year.

Academic participation cannot exist without an Academic Year.

---

## Teaching Assignment is the shared academic reference.

Academic modules should reference Teaching Assignments rather than recreating Teacher-Subject-Section relationships.

---

## Promotion updates Academic Enrollment.

Promotion never creates another Student.

---

## Graduation preserves academic history.

Graduation changes the Student lifecycle without removing historical records.

---

# Examples

## Teacher

```
Person

↓

Staff

↓

Teacher

↓

Teaching Assignment

↓

Grade 8A Mathematics
```

---

## Student

```
Person

↓

Student Relationship

↓

Academic Enrollment

↓

Grade 7B
```

---

## Student Promotion

```
2026–2027

↓

Grade 7B

↓

Promotion

↓

2027–2028

↓

Grade 8A
```

---

## Teacher with Multiple Teaching Assignments

```
Teacher

↓

Teaching Assignment

├── Grade 8A Mathematics

├── Grade 8B Mathematics

└── Grade 9A Mathematics
```

---

# Summary

The Academic Domain defines how Teachers and Students participate within the school's educational structure.

Admission establishes the Student relationship.

Academic Enrollment establishes participation within an Academic Year.

Teaching Assignment establishes academic responsibility.

Promotion manages academic progression.

Graduation completes the academic lifecycle while preserving historical records.

Together these concepts provide a consistent academic foundation upon which every future academic module within Nexchool can be built.