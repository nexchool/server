# School ERP – Current Functionality

High-level overview of implemented modules and their extent. No API references.

---

## Backend (Flask)

**Auth** – Register, login, logout. Email validation, forgot password, reset password. Authenticated profile get/update.

**RBAC** – Permissions and roles full CRUD. Assign permissions to roles (single and bulk). Assign roles to users; get user roles and effective permissions. Lookup by role name and by user email.

**Users** – List, get by id, update, delete. Email verification trigger. Lookup user by email.

**Classes** – List (optional filter by academic year), create, get, update, delete. Assign/unassign students and teachers to a class. List unassigned students and unassigned teachers for a class.

**Students** – List (permission-based: all, or by teacher’s classes), create (with optional email/login; credentials email via mailer), get, get current user’s student profile, update, delete.

**Teachers** – List (optional search/status), create, get, get current user’s teacher profile, update, delete.

**Attendance** – Teachers: list “my classes” for marking; mark attendance for a class on a date (records: student_id, status, optional remarks). Read: by class+date, by student, or “my attendance” for current user. Permission-scoped (mark, read self, read class, read all).

**Mailer** – Used when creating a student with email: sends template email with login credentials (e.g. student creation).

**Infrastructure** – Health check and API root. Global error handlers (4xx/5xx). CORS, DB init, app factory.

---

## Frontend (Expo / React Native)

**Auth** – Login, register, forgot password, reset password, verify email. Auth state and token handling.

**Home** – Dashboard after login. Role-based quick links (Students, Teachers, Classes, Attendance, Academics). Logout.

**Students** – List with search/filter, create student (modal/form), view student detail by id, edit/delete. Permission-aware (read all / read by class).

**Teachers** – List with search, create teacher (modal), view teacher detail by id, edit/delete. Permission-aware.

**Classes** – List classes, create class (modal), class detail by id with assign/unassign students and teachers. Permission-aware.

**Attendance** – “My classes” (teacher); mark attendance by class and date; “My attendance” (student/self); admin-style overview by class. Permission-aware.

**Academics** – Hub screen with role-based messaging and navigation (admin / teacher / student / parent). Links into attendance and placeholder grade views; no full grading module yet.

**Activities** – Placeholder screen with role-based subtitle; no backend. “Coming soon” style.

**Finance** – Placeholder screen with role-based subtitle; no fees backend or payments yet.

**Profile** – Show user info, derived role from permissions, logout. No full profile-edit UI (backend supports it).

**Permissions** – Tab visibility and in-screen actions driven by RBAC (e.g. Protected component, permission constants). Admin/Teacher/Student/Parent role helpers for UI.

---

## Summary

| Area        | Backend                         | Frontend                                      |
|------------|----------------------------------|-----------------------------------------------|
| Auth       | Full (login, register, recovery) | Full (screens + state)                        |
| RBAC       | Full CRUD                        | Used for tabs and guards only                 |
| Users      | Full CRUD                        | Not exposed as dedicated user-management UI   |
| Classes    | Full + assign students/teachers  | Full (list, detail, create, assign)          |
| Students   | Full + mailer on create          | Full (list, detail, create, edit, delete)     |
| Teachers   | Full                             | Full (list, detail, create, edit, delete)     |
| Attendance | Full (mark + read by class/student/self) | Full (my-classes, mark, my-attendance, overview) |
| Academics  | —                                | Hub + links; no grading backend              |
| Activities | —                                | Placeholder                                   |
| Finance    | —                                | Placeholder                                   |

