"""
Fix Teacher Permissions

Diagnoses and fixes the "No permissions assigned" error that blocks a teacher
from logging in. Two root causes are handled:

  1. The teacher's User account has no UserRole row → assigns the Teacher role.
  2. The Teacher role exists but has no RolePermissions rows → backfills them.

Usage (from the app/ directory):

  # Fix a specific teacher by email
  python -m backend.scripts.fix_teacher_permissions teacher@school.com

  # Fix all teachers with missing permissions (across every tenant)
  python -m backend.scripts.fix_teacher_permissions --all

  # Dry-run: show what would be fixed without touching the database
  python -m backend.scripts.fix_teacher_permissions --all --dry-run
  python -m backend.scripts.fix_teacher_permissions teacher@school.com --dry-run
"""

import sys

from backend.app import create_app
from backend.core.database import db
from backend.core.models import Tenant, TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED
from backend.modules.auth.models import User
from backend.modules.rbac.models import Role, Permission, RolePermission, UserRole
from backend.modules.rbac.services import get_user_permissions
from backend.modules.rbac.role_seeder import DEFAULT_ROLES


# ── helpers ──────────────────────────────────────────────────────────────────

def _teacher_role_for_tenant(tenant_id: str) -> Role | None:
    return Role.query.filter_by(name="Teacher", tenant_id=tenant_id).first()


def _ensure_teacher_role_has_permissions(role: Role, dry_run: bool) -> int:
    """
    Backfill any permissions that belong to the Teacher role definition but are
    missing from the given role's RolePermission rows.  Returns the count added.
    """
    expected_perms: list[str] = DEFAULT_ROLES["Teacher"]["permissions"]
    existing_perm_names = {p.name for p in role.permissions}
    missing = [n for n in expected_perms if n not in existing_perm_names]

    if not missing:
        return 0

    added = 0
    for perm_name in missing:
        perm = Permission.query.filter_by(name=perm_name).first()
        if not perm:
            print(f"      [WARN] Global permission '{perm_name}' not found – "
                  "run seed_rbac first.")
            continue
        if dry_run:
            print(f"      [DRY-RUN] Would assign permission '{perm_name}' to "
                  f"Teacher role in tenant {role.tenant_id}")
        else:
            rp = RolePermission(
                tenant_id=role.tenant_id,
                role_id=role.id,
                permission_id=perm.id,
            )
            db.session.add(rp)
        added += 1

    if not dry_run and added:
        db.session.commit()

    return added


def _ensure_user_has_teacher_role(user: User, dry_run: bool) -> tuple[bool, str]:
    """
    Make sure *user* has the Teacher role assigned in its tenant.
    Returns (changed: bool, message: str).
    """
    role = _teacher_role_for_tenant(user.tenant_id)
    if not role:
        return False, (
            f"Teacher role does not exist for tenant {user.tenant_id}. "
            "Run seed_rbac or backfill script first."
        )

    existing = UserRole.query.filter_by(
        user_id=user.id, role_id=role.id
    ).first()
    if existing:
        return False, "Teacher role already assigned."

    if dry_run:
        return True, f"[DRY-RUN] Would assign Teacher role to {user.email}"

    user_role = UserRole(
        tenant_id=user.tenant_id,
        user_id=user.id,
        role_id=role.id,
    )
    db.session.add(user_role)
    db.session.commit()
    return True, f"Teacher role assigned to {user.email}"


# ── per-user diagnosis and fix ────────────────────────────────────────────────

def fix_user(user: User, dry_run: bool) -> dict:
    result = {
        "email": user.email,
        "tenant_id": user.tenant_id,
        "role_assigned": False,
        "permissions_backfilled": 0,
        "already_ok": False,
        "errors": [],
    }

    # Step 1 – check / fix role assignment
    changed, msg = _ensure_user_has_teacher_role(user, dry_run)
    if "already assigned" not in msg:
        print(f"    Role fix: {msg}")
    if not changed and "already assigned" in msg:
        pass  # silent – expected happy path
    elif changed:
        result["role_assigned"] = True

    # Step 2 – ensure the Teacher role itself has all its permissions
    role = _teacher_role_for_tenant(user.tenant_id)
    if role:
        added = _ensure_teacher_role_has_permissions(role, dry_run)
        if added:
            print(f"    Backfilled {added} permission(s) onto the Teacher role "
                  f"(tenant {user.tenant_id}).")
            result["permissions_backfilled"] = added

    # Step 3 – final sanity check (skip in dry-run, DB wasn't touched)
    if not dry_run:
        perms = get_user_permissions(user.id)
        if perms:
            result["already_ok"] = True
        else:
            result["errors"].append(
                "User still has no permissions after fix. "
                "Check that global permissions exist (run seed_rbac)."
            )

    return result


# ── entry points ─────────────────────────────────────────────────────────────

def fix_by_email(email: str, dry_run: bool = False) -> None:
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            print(f"\n[ERROR] No user found with email: {email}")
            sys.exit(1)

        # Verify this is actually a teacher account
        if not hasattr(user, "teacher_profile") or not user.teacher_profile:
            print(f"\n[WARN] User '{email}' has no Teacher profile. Proceeding anyway.")

        print(f"\nDiagnosing: {email}  (tenant: {user.tenant_id})")

        perms = get_user_permissions(user.id)
        if perms and not dry_run:
            print(f"  OK – user already has {len(perms)} permission(s). No action needed.")
            print(f"  Permissions: {', '.join(perms)}")
            return

        if not perms:
            print("  User currently has NO permissions – applying fix …")

        result = fix_user(user, dry_run)

        if result["errors"]:
            for err in result["errors"]:
                print(f"  [ERROR] {err}")
        else:
            if not dry_run:
                final_perms = get_user_permissions(user.id)
                print(f"\n  Done. User now has {len(final_perms)} permission(s):")
                for p in final_perms:
                    print(f"    • {p}")
            else:
                print("\n  Dry-run complete. Re-run without --dry-run to apply.")


def fix_all_teachers(dry_run: bool = False) -> None:
    app = create_app()
    with app.app_context():
        tenants = Tenant.query.filter(
            Tenant.status.in_([TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED])
        ).all()

        if not tenants:
            print("No active tenants found.")
            return

        total_fixed = 0
        total_already_ok = 0
        total_errors = 0

        for tenant in tenants:
            # Find all users in this tenant who have a teacher_profile
            from backend.modules.teachers.models import Teacher
            teachers = Teacher.query.filter_by(tenant_id=tenant.id).all()

            if not teachers:
                continue

            print(f"\nTenant: {tenant.name} ({tenant.subdomain})  "
                  f"— {len(teachers)} teacher(s)")

            for teacher in teachers:
                user = teacher.user
                if not user:
                    print(f"  [SKIP] Teacher id={teacher.id} has no linked user.")
                    continue

                perms = get_user_permissions(user.id)
                if perms:
                    total_already_ok += 1
                    continue  # nothing to do

                print(f"  Fixing: {user.email}")
                result = fix_user(user, dry_run)

                if result["errors"]:
                    total_errors += 1
                    for err in result["errors"]:
                        print(f"    [ERROR] {err}")
                else:
                    total_fixed += 1

        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)
        print(f"  Already had permissions : {total_already_ok}")
        print(f"  Fixed                   : {total_fixed}")
        print(f"  Errors                  : {total_errors}")
        if dry_run:
            print("\n  (Dry-run – no changes written to the database.)")
        print("=" * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    print("\n" + "=" * 60)
    print("Fix Teacher Permissions" + ("  [DRY-RUN]" if dry_run else ""))
    print("=" * 60)

    if "--all" in args:
        fix_all_teachers(dry_run=dry_run)
    elif args:
        fix_by_email(args[0], dry_run=dry_run)
    else:
        print(__doc__)
        sys.exit(0)

    print()
