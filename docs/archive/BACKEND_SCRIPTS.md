# Backend Scripts — High-Level Overview

This document summarizes the scripts in `server/scripts/`. All scripts are run from the project root (e.g. `app/` or `school-ERP/`) unless stated otherwise.

---

## Setup & Seeding

| Script | Purpose |
|--------|---------|
| **`seed_rbac`** | Seeds global permissions and default roles (Admin, Teacher, Student, Parent) for RBAC. Run after migrations when setting up a new environment. |
| **`create_super_admin`** | Creates the first platform admin user with `is_platform_admin=True`. Use when the DB is empty to get access to the Super Admin panel. Ensures default tenant, permissions, and roles exist. |
| **`create_admin`** | Interactive script to create an Admin user in a tenant. Prompts for email, password, name, and tenant ID. |
| **`seed_notification_templates`** | Seeds notification templates (email verification, password reset, welcome, etc.) into `notification_templates` as global templates. Run via Flask shell. |
| **`seed_existing_mailer_templates_to_db`** | Reads HTML templates from `server/modules/mailer/templates/` and inserts them into `notification_templates` as global records. |

---

## User Management

| Script | Purpose |
|--------|---------|
| **`reset_user_password`** | Resets a user's password by email or user ID. Supports interactive prompt, auto-generated temp password, and `--force-reset` for next-login change. |

---

## Permissions Fixes & Backfills

These scripts add missing permissions to existing roles for tenants created before certain features were introduced. All are idempotent.

| Script | Purpose |
|--------|---------|
| **`fix_teacher_permissions`** | Fixes the "No permissions assigned" error that blocks teachers from logging in. Assigns the Teacher role and backfills missing role permissions. Use `--all` for all tenants, or pass an email. Supports `--dry-run`. |
| **`backfill_teacher_leave_permissions`** | Adds `teacher.leave.apply` (Teacher role) and `teacher.leave.manage` (Admin role) to all tenants. |
| **`backfill_timetable_subject_permissions`** | Adds subject and timetable permissions to Admin, Teacher, Student, and Parent roles across all tenants. |
| **`backfill_admin_finance_permissions`** | Adds finance permissions (`finance.read`, `finance.manage`, `finance.collect`, `finance.refund`) to Admin roles across all tenants. |

---

## Utilities

| Script | Purpose |
|--------|---------|
| **`rbac_helpers`** | Helper functions for RBAC tasks (e.g. `assign_admin_role`, `assign_teacher_role`, `show_user_permissions`). Import and use from Flask shell, not run as a CLI script. |

---

## Quick Reference — Common Commands

```bash
# Initial setup (new deployment)
python -m scripts.seed_rbac
python -m scripts.create_super_admin

# Create tenant admin
python -m scripts.create_admin

# Fix teacher login issues
python -m scripts.fix_teacher_permissions --all
python -m scripts.fix_teacher_permissions teacher@school.com

# Reset user password
python -m scripts.reset_user_password --email user@school.com --auto

# Backfill permissions (run after adding new features)
python -m scripts.backfill_teacher_leave_permissions
python -m scripts.backfill_timetable_subject_permissions
python -m scripts.backfill_admin_finance_permissions
```
