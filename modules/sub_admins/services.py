"""
Sub-Admin services (tenant-scoped).

A "sub-admin" is a tenant User (not soft-deleted) linked via UserRole to a
private Role with ``is_subadmin=True``. Each sub-admin owns exactly one private
role named ``subadmin:<user_id>``; that role's RolePermission rows are the
module permissions the School Admin granted.

All functions are tenant-scoped: the caller passes ``tenant_id`` explicitly
(routes source it from ``get_tenant_id()``). Mutating helpers return a result
dict ``{"success", "error"?, "code"?, "status_code"?, ...}`` so the thin route
layer can map to the standard error envelope without embedding business logic.
"""

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.auth.models import User
from modules.auth.services import revoke_all_user_sessions
from modules.rbac.models import Permission, Role, RolePermission, UserRole
from shared.utils import paginate_query

from .catalog import (
    expand_selection,
    selection_grants_anything,
    summarize_permissions,
)

logger = logging.getLogger(__name__)

# Minimum password length enforced on create and reset (matches project rule).
MIN_PASSWORD_LENGTH = 8

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _err(code: str, message: str, status_code: int) -> Dict:
    return {"success": False, "code": code, "error": message, "status_code": status_code}


def _is_valid_email(email: str) -> bool:
    return bool(email) and bool(_EMAIL_RE.match(email))


def _private_role_name(user_id: str) -> str:
    return f"subadmin:{user_id}"


def _get_subadmin_user(tenant_id: str, user_id: str) -> Optional[User]:
    """
    Return the User iff it is a non-deleted sub-admin in this tenant.

    A sub-admin must be attached to at least one is_subadmin role in the same
    tenant. This guard prevents acting on the main Admin, teachers, students.
    """
    user = (
        User.query.filter_by(id=user_id, tenant_id=tenant_id)
        .filter(User.deleted_at.is_(None))
        .first()
    )
    if not user:
        return None

    is_subadmin = (
        db.session.query(UserRole.id)
        .join(Role, Role.id == UserRole.role_id)
        .filter(
            UserRole.user_id == user_id,
            UserRole.tenant_id == tenant_id,
            Role.is_subadmin.is_(True),
        )
        .first()
    )
    return user if is_subadmin else None


def _get_private_role(tenant_id: str, user_id: str) -> Optional[Role]:
    """Return the sub-admin's private is_subadmin role within the tenant."""
    return (
        Role.query.join(UserRole, UserRole.role_id == Role.id)
        .filter(
            UserRole.user_id == user_id,
            UserRole.tenant_id == tenant_id,
            Role.is_subadmin.is_(True),
        )
        .first()
    )


def _role_permission_names(role_id: str) -> List[str]:
    role = Role.query.get(role_id)
    if not role:
        return []
    return [p.name for p in role.permissions]


def _sync_role_permissions(tenant_id: str, role: Role, desired: set) -> None:
    """Add missing and remove no-longer-selected RolePermission rows.

    Permission rows are looked up by name in one query (no N+1). Unknown
    permission names are skipped silently — the catalog is validated, so this is
    a defensive guard only.
    """
    current = {p.name: p for p in role.permissions}
    to_add = desired - set(current.keys())
    to_remove = set(current.keys()) - desired

    if to_add:
        perms = Permission.query.filter(Permission.name.in_(to_add)).all()
        for perm in perms:
            db.session.add(
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    permission_id=perm.id,
                )
            )

    if to_remove:
        remove_ids = [current[name].id for name in to_remove]
        RolePermission.query.filter(
            RolePermission.role_id == role.id,
            RolePermission.permission_id.in_(remove_ids),
        ).delete(synchronize_session=False)


def _dispatch_credentials_email(
    user: User,
    tenant_id: str,
    tenant_name: str,
    password: str,
    login_url: str,
    notification_type: str,
    title: str,
) -> None:
    """Send ADMIN_CREDENTIALS / ADMIN_PASSWORD_RESET; never fail the op on error."""
    try:
        from modules.notifications.services import notification_dispatcher
        from modules.notifications.enums import NotificationChannel

        results = notification_dispatcher.dispatch(
            user_id=user.id,
            tenant_id=tenant_id,
            notification_type=notification_type,
            channels=[NotificationChannel.EMAIL.value],
            title=title,
            body=None,
            extra_data={
                "admin_name": user.name or user.email,
                "tenant_name": tenant_name or "",
                "admin_email": user.email,
                "password": password,
                "login_url": login_url or "",
            },
        )
        for channel, ok in results.items():
            if not ok:
                logger.warning(
                    "%s email not sent (channel=%s); check notification_templates "
                    "and SMTP/Celery. tenant=%s sub_admin=%s",
                    notification_type,
                    channel,
                    tenant_id,
                    user.email,
                )
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning(
            "Failed to send %s email for tenant %s sub_admin %s: %s",
            notification_type,
            tenant_id,
            user.email,
            exc,
            exc_info=True,
        )


def serialize_sub_admin(user: User, role: Optional[Role], detail: bool = False) -> Dict:
    """Serialize a sub-admin User + private role into an API dict."""
    data = {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "status": "suspended" if user.is_suspended else "active",
        "modules": summarize_permissions(
            [p.name for p in role.permissions] if role else []
        ),
    }
    if detail:
        data["created_at"] = user.created_at.isoformat() if user.created_at else None
        data["updated_at"] = user.updated_at.isoformat() if user.updated_at else None
    return data


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def list_sub_admins(
    tenant_id: str,
    search: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> Dict:
    """Paginated list of sub-admins for a tenant (excludes soft-deleted)."""
    query = (
        User.query.join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .filter(
            User.tenant_id == tenant_id,
            User.deleted_at.is_(None),
            UserRole.tenant_id == tenant_id,
            Role.is_subadmin.is_(True),
        )
        .distinct()
    )

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            db.or_(User.email.ilike(pattern), User.name.ilike(pattern))
        )

    if status == "active":
        query = query.filter(User.is_suspended.is_(False))
    elif status == "suspended":
        query = query.filter(User.is_suspended.is_(True))

    query = query.order_by(User.created_at.desc())

    result = paginate_query(query, page, per_page)

    items = []
    for user in result["items"]:
        role = _get_private_role(tenant_id, user.id)
        items.append(serialize_sub_admin(user, role))
    result["items"] = items
    return result


def get_sub_admin(tenant_id: str, user_id: str) -> Dict:
    """Return a sub-admin's detail, or an error dict if not a sub-admin here."""
    user = _get_subadmin_user(tenant_id, user_id)
    if not user:
        return _err("NotFound", "Sub-admin not found", 404)
    role = _get_private_role(tenant_id, user_id)
    return {"success": True, "sub_admin": serialize_sub_admin(user, role, detail=True)}


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def create_sub_admin(
    tenant_id: str,
    tenant_name: str,
    name: str,
    email: str,
    password: str,
    modules: List[dict],
    login_url: str = "",
) -> Dict:
    """Create a sub-admin user + private role with the selected module perms."""
    email = (email or "").strip().lower()
    name = (name or "").strip()

    if not _is_valid_email(email):
        return _err("ValidationError", "A valid email is required", 422)
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return _err(
            "ValidationError",
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
            422,
        )
    if not selection_grants_anything(modules):
        return _err("ValidationError", "Select at least one module to grant", 422)

    try:
        permission_names = expand_selection(modules)
    except ValueError as exc:
        return _err("ValidationError", str(exc), 422)

    # Duplicate guard must see soft-deleted rows (unique constraint ignores
    # deleted_at) to avoid an IntegrityError 500 on insert.
    if User.get_user_by_email(email, tenant_id=tenant_id, include_deleted=True):
        return _err("Conflict", "A user with this email already exists", 409)

    try:
        user = User(tenant_id=tenant_id, email=email, name=name or email)
        user.set_password(password)
        user.email_verified = True
        db.session.add(user)
        db.session.flush()

        role = Role(
            tenant_id=tenant_id,
            name=_private_role_name(user.id),
            description=f"Private permission set for sub-admin {email}",
            is_subadmin=True,
        )
        db.session.add(role)
        db.session.flush()

        _sync_role_permissions(tenant_id, role, permission_names)

        db.session.add(
            UserRole(tenant_id=tenant_id, user_id=user.id, role_id=role.id)
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _err("Conflict", "A user with this email already exists", 409)
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to create sub-admin: %s", exc, exc_info=True)
        return _err("InternalError", "Failed to create sub-admin", 500)

    _dispatch_credentials_email(
        user,
        tenant_id,
        tenant_name,
        password,
        login_url,
        notification_type="ADMIN_CREDENTIALS",
        title="Your School Admin Account",
    )

    role = _get_private_role(tenant_id, user.id)
    return {
        "success": True,
        "sub_admin": serialize_sub_admin(user, role, detail=True),
    }


def update_sub_admin(
    tenant_id: str,
    user_id: str,
    name: Optional[str] = None,
    modules: Optional[List[dict]] = None,
) -> Dict:
    """Edit a sub-admin's name and/or re-sync its module permissions."""
    user = _get_subadmin_user(tenant_id, user_id)
    if not user:
        return _err("NotFound", "Sub-admin not found", 404)

    if modules is not None:
        if not selection_grants_anything(modules):
            return _err("ValidationError", "Select at least one module to grant", 422)
        try:
            desired = expand_selection(modules)
        except ValueError as exc:
            return _err("ValidationError", str(exc), 422)

    try:
        if name is not None:
            user.name = name.strip() or user.name

        if modules is not None:
            role = _get_private_role(tenant_id, user_id)
            if not role:
                return _err("NotFound", "Sub-admin role not found", 404)
            _sync_role_permissions(tenant_id, role, desired)

        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to update sub-admin %s: %s", user_id, exc, exc_info=True)
        return _err("InternalError", "Failed to update sub-admin", 500)

    role = _get_private_role(tenant_id, user_id)
    return {
        "success": True,
        "sub_admin": serialize_sub_admin(user, role, detail=True),
    }


def suspend_sub_admin(tenant_id: str, user_id: str, actor_id: str) -> Dict:
    """Suspend a sub-admin and revoke its active sessions."""
    if actor_id == user_id:
        return _err("ValidationError", "You cannot suspend your own account", 400)

    user = _get_subadmin_user(tenant_id, user_id)
    if not user:
        return _err("NotFound", "Sub-admin not found", 404)

    try:
        user.is_suspended = True
        revoke_all_user_sessions(user_id)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to suspend sub-admin %s: %s", user_id, exc, exc_info=True)
        return _err("InternalError", "Failed to suspend sub-admin", 500)

    return {"success": True, "message": "Sub-admin suspended"}


def restore_sub_admin(tenant_id: str, user_id: str) -> Dict:
    """Clear the suspended flag on a sub-admin."""
    user = _get_subadmin_user(tenant_id, user_id)
    if not user:
        return _err("NotFound", "Sub-admin not found", 404)

    try:
        user.is_suspended = False
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to restore sub-admin %s: %s", user_id, exc, exc_info=True)
        return _err("InternalError", "Failed to restore sub-admin", 500)

    return {"success": True, "message": "Sub-admin restored"}


def reset_sub_admin_password(
    tenant_id: str,
    tenant_name: str,
    user_id: str,
    actor_id: str,
    password: str,
    login_url: str = "",
) -> Dict:
    """Set a new admin-typed password, revoke sessions, email the sub-admin."""
    if actor_id == user_id:
        return _err("ValidationError", "You cannot reset your own password here", 400)
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return _err(
            "ValidationError",
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
            422,
        )

    user = _get_subadmin_user(tenant_id, user_id)
    if not user:
        return _err("NotFound", "Sub-admin not found", 404)

    try:
        user.set_password(password)
        revoke_all_user_sessions(user_id)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error(
            "Failed to reset sub-admin password %s: %s", user_id, exc, exc_info=True
        )
        return _err("InternalError", "Failed to reset password", 500)

    _dispatch_credentials_email(
        user,
        tenant_id,
        tenant_name,
        password,
        login_url,
        notification_type="ADMIN_PASSWORD_RESET",
        title="Your School Admin Password Has Been Reset",
    )

    return {"success": True, "message": "Password reset"}


def delete_sub_admin(tenant_id: str, user_id: str, actor_id: str) -> Dict:
    """Soft-delete a sub-admin (set deleted_at) and revoke sessions."""
    if actor_id == user_id:
        return _err("ValidationError", "You cannot delete your own account", 400)

    user = _get_subadmin_user(tenant_id, user_id)
    if not user:
        return _err("NotFound", "Sub-admin not found", 404)

    try:
        user.deleted_at = datetime.utcnow()
        revoke_all_user_sessions(user_id)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to delete sub-admin %s: %s", user_id, exc, exc_info=True)
        return _err("InternalError", "Failed to delete sub-admin", 500)

    return {"success": True, "message": "Sub-admin deleted"}
