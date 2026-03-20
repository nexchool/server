"""
Reset User Password

Resets the password for any user identified by email or user ID.
Passwords are stored as one-way bcrypt hashes and cannot be read back,
so this script sets a new password instead.

Usage (from the app/ directory):

  # Reset by email — prompts for new password interactively
  python -m backend.scripts.reset_user_password --email teacher@school.com

  # Reset by user ID — prompts for new password interactively
  python -m backend.scripts.reset_user_password --id <user-uuid>

  # Generate a random temporary password automatically
  python -m backend.scripts.reset_user_password --email teacher@school.com --auto

  # Also force the user to change their password on next login
  python -m backend.scripts.reset_user_password --email teacher@school.com --auto --force-reset

  # Show user info without changing anything
  python -m backend.scripts.reset_user_password --email teacher@school.com --info
"""

import sys
import secrets
import string
import getpass
import argparse

from backend.app import create_app
from backend.modules.auth.models import User


# ── helpers ──────────────────────────────────────────────────────────────────

def _generate_temp_password(length: int = 12) -> str:
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        # Ensure at least one of each required character class
        if (any(c.islower() for c in pwd)
                and any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd)):
            return pwd


def _find_user(email: str | None, user_id: str | None) -> User | None:
    if email:
        return User.query.filter_by(email=email.lower().strip()).first()
    if user_id:
        return User.query.get(user_id.strip())
    return None


def _print_user_info(user: User) -> None:
    from backend.modules.rbac.services import get_user_permissions, get_user_roles
    roles = get_user_roles(user.id)
    perms = get_user_permissions(user.id)

    print(f"\n  User ID             : {user.id}")
    print(f"  Email               : {user.email}")
    print(f"  Name                : {user.name or '(not set)'}")
    print(f"  Tenant ID           : {user.tenant_id}")
    print(f"  Email Verified      : {user.email_verified}")
    print(f"  Force Password Reset: {user.force_password_reset}")
    print(f"  Roles               : {', '.join(r['name'] for r in roles) or '(none)'}")
    print(f"  Permissions         : {len(perms)} assigned")


# ── core action ──────────────────────────────────────────────────────────────

def reset_password(
    email: str | None = None,
    user_id: str | None = None,
    new_password: str | None = None,
    auto_generate: bool = False,
    force_reset: bool = False,
    info_only: bool = False,
) -> bool:
    app = create_app()
    with app.app_context():
        user = _find_user(email, user_id)

        if not user:
            lookup = email or user_id
            print(f"\n  [ERROR] No user found for: {lookup}")
            return False

        print("\n" + "=" * 60)
        print("  User Found")
        print("=" * 60)
        _print_user_info(user)

        if info_only:
            print("=" * 60)
            return True

        # Determine the new password
        if auto_generate:
            password = _generate_temp_password()
        elif new_password:
            password = new_password
        else:
            print()
            while True:
                password = getpass.getpass("  Enter new password: ")
                if not password:
                    print("  [ERROR] Password cannot be empty.")
                    continue
                confirm = getpass.getpass("  Confirm new password: ")
                if password != confirm:
                    print("  [ERROR] Passwords do not match. Try again.\n")
                    continue
                break

        # Apply the change
        user.set_password(password)
        user.reset_password_token = None
        user.reset_password_sent_at = None
        if force_reset:
            user.force_password_reset = True
        user.save()

        print("\n" + "=" * 60)
        print("  Password Reset Successful")
        print("=" * 60)
        print(f"  Email               : {user.email}")
        if auto_generate:
            print(f"  New (temp) password : {password}")
            print("\n  Share this password securely and ask the user to change it.")
        else:
            print("  Password updated.")
        if force_reset:
            print("  Force password reset on next login: YES")
        print("=" * 60 + "\n")
        return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Reset a user's password by email or user ID.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    lookup = parser.add_mutually_exclusive_group(required=True)
    lookup.add_argument("--email", metavar="EMAIL", help="User's email address")
    lookup.add_argument("--id", dest="user_id", metavar="UUID", help="User's UUID")

    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-generate a random temporary password instead of prompting",
    )
    parser.add_argument(
        "--force-reset",
        action="store_true",
        help="Force the user to change their password on next login",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Show user info only — do not change the password",
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    title = "User Info" if args.info else "Reset User Password"
    print(f"  {title}")
    print("=" * 60)

    success = reset_password(
        email=args.email,
        user_id=args.user_id,
        auto_generate=args.auto,
        force_reset=args.force_reset,
        info_only=args.info,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
