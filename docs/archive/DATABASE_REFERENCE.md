# Database Reference

Schema reference for the School ERP backend (SQLAlchemy / Flask-SQLAlchemy). Schema is managed by **Flask-Migrate** (Alembic); tables are created and updated via migrations, not `db.create_all()`.

---

## Tables Overview

| Table             | Purpose |
|-------------------|---------|
| `users`           | Auth: login (email/password), profile, verification, password reset |
| `sessions`        | Refresh tokens and session metadata per user |
| `roles`           | RBAC role definitions (e.g. Admin, Teacher, Student) |
| `permissions`      | RBAC permission definitions (resource.action.scope) |
| `role_permissions` | Many-to-many: which permissions each role has |
| `user_roles`      | Many-to-many: which roles each user has |
| `students`        | Student profile; links to `users` and optionally `classes` |
| `teachers`        | Teacher profile; links to `users` |
| `classes`         | Class/section per academic year; optional class teacher (`users.id`) |
| `class_teachers`   | Many-to-many: teachers assigned to classes (with subject/class-teacher flag) |
| `attendance`      | One row per student per class per date (status: present/absent/late) |

---

## Table Definitions

### users

| Column                  | Type         | Nullable | Notes |
|-------------------------|--------------|----------|--------|
| id                      | VARCHAR(36)  | No       | PK, UUID |
| email                   | VARCHAR(120) | No       | Unique, indexed |
| password_hash           | VARCHAR(255) | No       | |
| name                    | VARCHAR(120) | Yes      | |
| profile_picture_url     | VARCHAR(255) | Yes      | |
| email_verified          | BOOLEAN      | No       | Default false |
| verification_token      | VARCHAR(255) | Yes      | |
| reset_password_token    | VARCHAR(255) | Yes      | |
| reset_password_sent_at  | DATETIME     | Yes      | |
| force_password_reset    | BOOLEAN      | No       | Default false |
| last_login_at           | DATETIME     | Yes      | |
| created_at              | DATETIME     | No       | |
| updated_at              | DATETIME     | No       | |

### sessions

| Column                 | Type         | Nullable | Notes |
|------------------------|--------------|----------|--------|
| id                     | VARCHAR(36)  | No       | PK, UUID |
| user_id                | VARCHAR(36)  | No       | FK → users.id, CASCADE |
| refresh_token          | TEXT         | Yes      | Indexed |
| refresh_token_expires_at | DATETIME   | No       | |
| created_at             | DATETIME     | No       | |
| last_accessed_at       | DATETIME     | Yes      | |
| revoked                | BOOLEAN      | No       | Default false |
| revoked_at             | DATETIME     | Yes      | |
| ip_address             | VARCHAR(45)  | Yes      | |
| user_agent             | VARCHAR(255) | Yes      | |
| device_info            | VARCHAR(255) | Yes      | |
| login_method           | VARCHAR(20)  | No       | Default 'email' |

### roles

| Column     | Type         | Nullable | Notes |
|------------|--------------|----------|--------|
| id         | VARCHAR(36)  | No       | PK, UUID |
| name       | VARCHAR(50)  | No       | Unique, indexed |
| description| VARCHAR(255) | Yes      | |
| created_at | DATETIME     | No       | |

### permissions

| Column      | Type         | Nullable | Notes |
|-------------|--------------|----------|--------|
| id          | VARCHAR(36)  | No       | PK, UUID |
| name        | VARCHAR(100) | No       | Unique, indexed (e.g. student.create, attendance.mark) |
| description | VARCHAR(255) | Yes      | |
| created_at  | DATETIME     | No       | |

### role_permissions

| Column        | Type        | Nullable | Notes |
|---------------|-------------|----------|--------|
| id            | VARCHAR(36) | No       | PK, UUID |
| role_id       | VARCHAR(36) | No       | FK → roles.id, CASCADE |
| permission_id | VARCHAR(36) | No       | FK → permissions.id, CASCADE |
| created_at    | DATETIME    | No       | |
| **Unique**    | (role_id, permission_id) | | |

### user_roles

| Column     | Type        | Nullable | Notes |
|------------|-------------|----------|--------|
| id         | VARCHAR(36) | No       | PK, UUID |
| user_id    | VARCHAR(36) | No       | FK → users.id, CASCADE |
| role_id    | VARCHAR(36) | No       | FK → roles.id, CASCADE |
| created_at | DATETIME    | No       | |
| **Unique** | (user_id, role_id) | | |

### students

| Column              | Type         | Nullable | Notes |
|---------------------|--------------|----------|--------|
| id                  | VARCHAR(36)  | No       | PK, UUID |
| user_id             | VARCHAR(36)  | No       | FK → users.id, Unique (one student profile per user) |
| admission_number    | VARCHAR(20)  | No       | Unique, indexed |
| roll_number         | INTEGER      | Yes      | |
| academic_year       | VARCHAR(20)  | Yes      | e.g. "2025-2026" |
| class_id            | VARCHAR(36)  | Yes      | FK → classes.id |
| date_of_birth       | DATE         | Yes      | |
| gender              | VARCHAR(10)  | Yes      | |
| phone               | VARCHAR(20)  | Yes      | |
| address             | TEXT         | Yes      | |
| guardian_name       | VARCHAR(100) | Yes      | |
| guardian_relationship | VARCHAR(50) | Yes      | |
| guardian_phone      | VARCHAR(20)  | Yes      | |
| guardian_email      | VARCHAR(120) | Yes      | |
| created_at          | DATETIME     | No       | |
| updated_at          | DATETIME     | No       | |

### teachers

| Column            | Type         | Nullable | Notes |
|-------------------|--------------|----------|--------|
| id                | VARCHAR(36)  | No       | PK, UUID |
| user_id           | VARCHAR(36)  | No       | FK → users.id, Unique |
| employee_id       | VARCHAR(20)  | No       | Unique, indexed |
| designation       | VARCHAR(100) | Yes      | |
| department        | VARCHAR(100) | Yes      | |
| qualification     | VARCHAR(200) | Yes      | |
| specialization    | VARCHAR(200) | Yes      | |
| experience_years  | INTEGER      | Yes      | |
| phone             | VARCHAR(20)  | Yes      | |
| address           | TEXT         | Yes      | |
| date_of_joining   | DATE         | Yes      | |
| status            | VARCHAR(20)  | No       | Default 'active' (e.g. active/inactive) |
| created_at        | DATETIME     | No       | |
| updated_at        | DATETIME     | No       | |

### classes

| Column        | Type        | Nullable | Notes |
|---------------|-------------|----------|--------|
| id            | VARCHAR(36) | No       | PK, UUID |
| name          | VARCHAR(50) | No       | e.g. "Grade 10" |
| section       | VARCHAR(10) | No       | e.g. "A" |
| academic_year | VARCHAR(20) | No       | e.g. "2025-2026" |
| start_date    | DATE        | Yes      | |
| end_date      | DATE        | Yes      | |
| teacher_id    | VARCHAR(36) | Yes      | FK → users.id (class teacher) |
| created_at    | DATETIME    | No       | |
| updated_at    | DATETIME    | No       | |
| **Unique**    | (name, section, academic_year) | | |

### class_teachers

| Column          | Type        | Nullable | Notes |
|-----------------|-------------|----------|--------|
| id              | VARCHAR(36) | No       | PK, UUID |
| class_id        | VARCHAR(36) | No       | FK → classes.id |
| teacher_id      | VARCHAR(36) | No       | FK → teachers.id |
| subject         | VARCHAR(100)| Yes      | |
| is_class_teacher| BOOLEAN     | No       | Default false |
| created_at      | DATETIME    | No       | |
| **Unique**      | (class_id, teacher_id) | | |

### attendance

| Column    | Type        | Nullable | Notes |
|-----------|-------------|----------|--------|
| id        | VARCHAR(36) | No      | PK, UUID |
| date      | DATE        | No       | Indexed |
| class_id  | VARCHAR(36) | No       | FK → classes.id |
| student_id| VARCHAR(36) | No       | FK → students.id |
| status    | VARCHAR(10) | No       | present / absent / late |
| remarks   | TEXT        | Yes      | |
| marked_by | VARCHAR(36) | No       | FK → users.id |
| created_at| DATETIME    | No       | |
| updated_at| DATETIME    | No       | |
| **Unique**| (date, class_id, student_id) | | |

---

## Relationships (Logical)

- **User** → has many **Sessions**; has many **Roles** via **user_roles**; may have one **Student** or one **Teacher** profile; may be class teacher of **Classes** (`classes.teacher_id`).
- **Role** → has many **Permissions** via **role_permissions**.
- **Student** → belongs to **User**; optionally belongs to one **Class**; has many **Attendance** records.
- **Teacher** → belongs to **User**; has many **Class** assignments via **class_teachers**.
- **Class** → optional class teacher (**User**); has many **Students** (`students.class_id`); has many **ClassTeacher** rows; has many **Attendance** records.
- **Attendance** → belongs to **Class**, **Student**, and **User** (marked_by).

---

## Migrations (Flask-Migrate / Alembic)

Schema is managed by Flask-Migrate. From the **project root** with the app’s virtualenv active and `DATABASE_URL` set:

```bash
export FLASK_APP=app:app

# Apply all pending migrations (create/update tables)
flask db upgrade

# After changing models: generate a new migration
flask db migrate -m "Describe your change"

# Show current revision
flask db current

# Roll back one revision
flask db downgrade
```

- **New deployments:** run `flask db upgrade` once to create all tables.
- **Model changes:** run `flask db migrate -m "message"`, review the generated script in `server/migrations/versions/`, then `flask db upgrade`.

Legacy SQL scripts in `server/migrations/` (e.g. `add_student_phone.sql`) are kept for reference only; the canonical schema is defined by the models and these migrations.
