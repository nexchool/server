"""
Calendar activity side-effects: notifications, audit log, user-name resolution.

Shared by the calendar services and the holidays module so every calendar
mutation (holiday/vacation/exam/event/semester) produces the same in-app
notification + tenant audit trail. All hooks are fire-and-forget: a failure is
logged and never blocks the mutation itself.
"""

from typing import Dict, Iterable, List, Optional, Sequence

from flask import current_app, g


NOTIFY_ROLES = ("Admin", "Teacher", "Student", "Parent")


def _actor():
    user = getattr(g, "current_user", None)
    return (
        getattr(user, "id", None),
        getattr(user, "name", None) or getattr(user, "email", None) or "System",
    )


def actor_user_id() -> Optional[str]:
    return _actor()[0]


def resolve_user_names(
    rows: Sequence[Dict], keys: Iterable[str] = ("created_by", "updated_by")
) -> List[Dict]:
    """Attach `<key>_name` fields to serialized rows in one batched query."""
    from modules.auth.models import User

    ids = {row.get(key) for row in rows for key in keys if row.get(key)}
    if not ids:
        return list(rows)
    users = User.query.filter(User.id.in_(ids)).all()
    names = {u.id: (u.name or u.email) for u in users}
    for row in rows:
        for key in keys:
            row[f"{key}_name"] = names.get(row.get(key))
    return list(rows)


def notify_calendar_change(
    title: str,
    body: str,
    tenant_id: str,
    extra_data: Optional[Dict] = None,
) -> None:
    """Create an in-app notification for admins, teachers, students, parents."""
    try:
        from modules.notifications import notification_service
        from modules.notifications import notification_targeting_service as targeting

        user_ids: List[str] = []
        for role in NOTIFY_ROLES:
            user_ids.extend(
                u.id for u in targeting.get_users_by_role(role, tenant_id)
            )
        user_ids = list(dict.fromkeys(user_ids))
        if not user_ids:
            return

        notification = notification_service.create_notification(
            tenant_id=tenant_id,
            notification_type="academic_calendar",
            title=title,
            body=body,
            extra_data=extra_data or {},
            user_id=None,
        )
        notification_service.create_recipients(notification.id, user_ids)
    except Exception as exc:
        current_app.logger.warning(
            "academic_calendar notification failed: %s", exc, exc_info=True
        )


def audit_calendar_action(
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    description: str,
    tenant_id: str,
    meta: Optional[Dict] = None,
) -> None:
    """Append a tenant audit entry (committed with the caller's transaction)."""
    try:
        from modules.audit.services import log_tenant_action

        user_id, user_name = _actor()
        log_tenant_action(
            module="academic_calendar",
            action=action,
            resource_type=resource_type,
            description=description,
            tenant_id=tenant_id,
            actor_user_id=user_id,
            actor_name=user_name,
            actor_role="admin" if user_id else "system",
            resource_id=resource_id,
            meta=meta,
        )
    except Exception as exc:
        current_app.logger.warning(
            "academic_calendar audit log failed: %s", exc, exc_info=True
        )
