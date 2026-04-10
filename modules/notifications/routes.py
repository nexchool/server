"""
Notifications API Routes

List, mark read, send (targeted / bulk). Requires tenant_id and RBAC.
"""

from datetime import datetime

from flask import Blueprint, g, request
from sqlalchemy import and_, or_

from backend.core.database import db
from backend.core.decorators import auth_required, require_plan_feature, tenant_required
from backend.core.decorators.rbac import require_any_permission
from backend.core.tenant import get_tenant_id
from backend.modules.notifications.enums import (
    NotificationChannel,
    NotificationRecipientStatus,
    NotificationType,
)
from backend.modules.notifications.models import Notification, NotificationRecipient
from backend.modules.notifications.notification_service import (
    create_notification,
    create_recipients,
    send_notification as enqueue_dispatch,
)
from backend.modules.notifications.notification_targeting_service import (
    TargetingValidationError,
    collect_user_ids_bulk_merge,
    collect_user_ids_single_mode,
)
from backend.shared.helpers import (
    error_response,
    not_found_response,
    success_response,
    validation_error_response,
)

PERM_MANAGE = "finance.manage"

# url_prefix is applied in app.register_blueprint(..., url_prefix="/api/notifications")
notifications_bp = Blueprint("notifications", __name__)


def _allowed_notification_types() -> set:
    return {e.value for e in NotificationType}


def _serialize_list_item(n: Notification, user_id: str) -> dict:
    """Merge legacy per-user row with bulk parent + recipient read state."""
    data = n.to_dict(strip_internal_extra=True)
    if n.user_id == user_id:
        return data
    nr = NotificationRecipient.query.filter_by(
        notification_id=n.id,
        user_id=user_id,
    ).first()
    if nr:
        data["read_at"] = nr.read_at.isoformat() if nr.read_at else None
        data["recipient_id"] = nr.id
        data["recipient_status"] = nr.status
    return data


@notifications_bp.route("", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("notifications")
def list_notifications():
    """
    GET /api/notifications
    List notifications for current user. Query: unread_only, limit, offset.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return error_response("TenantError", "Tenant context required", 400)

    user_id = g.current_user.id if g.current_user else None
    if not user_id:
        return error_response("AuthError", "User not found", 401)

    unread_only = request.args.get("unread_only", "false").lower() == "true"
    limit = min(int(request.args.get("limit", 50) or 50), 100)
    offset = int(request.args.get("offset", 0) or 0)

    recipient_nids = db.session.query(NotificationRecipient.notification_id).filter(
        NotificationRecipient.user_id == user_id
    )

    q = Notification.query.filter(
        Notification.tenant_id == tenant_id,
        or_(
            Notification.user_id == user_id,
            and_(Notification.user_id.is_(None), Notification.id.in_(recipient_nids)),
        ),
    )

    if unread_only:
        unread_recipient_nids = db.session.query(NotificationRecipient.notification_id).filter(
            NotificationRecipient.user_id == user_id,
            NotificationRecipient.read_at.is_(None),
        )
        q = q.filter(
            or_(
                and_(Notification.user_id == user_id, Notification.read_at.is_(None)),
                and_(
                    Notification.user_id.is_(None),
                    Notification.id.in_(unread_recipient_nids),
                ),
            )
        )

    q = q.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    notifications = q.all()
    data = [_serialize_list_item(n, user_id) for n in notifications]
    return success_response(data={"notifications": data})


@notifications_bp.route("/<notification_id>/read", methods=["PATCH"])
@tenant_required
@auth_required
@require_plan_feature("notifications")
def mark_read(notification_id):
    """PATCH /api/notifications/<id>/read"""
    tenant_id = get_tenant_id()
    user_id = g.current_user.id if g.current_user else None
    if not tenant_id or not user_id:
        return error_response("AuthError", "Context required", 400)

    n = Notification.query.filter_by(id=notification_id, tenant_id=tenant_id).first()
    if not n:
        return not_found_response("Notification")

    now = datetime.utcnow()

    if n.user_id == user_id:
        try:
            n.read_at = now
            db.session.commit()
            return success_response(data=n.to_dict())
        except Exception:
            db.session.rollback()
            return error_response("UpdateError", "Failed to mark as read", 500)

    nr = NotificationRecipient.query.filter_by(
        notification_id=notification_id,
        user_id=user_id,
    ).first()
    if not nr:
        return not_found_response("Notification")

    try:
        nr.read_at = now
        if nr.status != NotificationRecipientStatus.FAILED.value:
            nr.status = NotificationRecipientStatus.READ.value
        db.session.commit()
        return success_response(data=_serialize_list_item(n, user_id))
    except Exception:
        db.session.rollback()
        return error_response("UpdateError", "Failed to mark as read", 500)


@notifications_bp.route("/mark-all-read", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("notifications")
def mark_all_read():
    """POST /api/notifications/mark-all-read"""
    tenant_id = get_tenant_id()
    user_id = g.current_user.id if g.current_user else None
    if not tenant_id or not user_id:
        return error_response("AuthError", "Context required", 400)

    now = datetime.utcnow()
    try:
        legacy_updated = (
            Notification.query.filter_by(tenant_id=tenant_id, user_id=user_id)
            .filter(Notification.read_at.is_(None))
            .update({Notification.read_at: now}, synchronize_session=False)
        )

        bulk_parent_ids = db.session.query(Notification.id).filter(
            Notification.tenant_id == tenant_id,
            Notification.user_id.is_(None),
        )
        rec_updated = NotificationRecipient.query.filter(
            NotificationRecipient.user_id == user_id,
            NotificationRecipient.read_at.is_(None),
            NotificationRecipient.notification_id.in_(bulk_parent_ids),
        ).update(
            {
                NotificationRecipient.read_at: now,
                NotificationRecipient.status: NotificationRecipientStatus.READ.value,
            },
            synchronize_session=False,
        )

        db.session.commit()
        return success_response(data={"updated_count": legacy_updated + rec_updated})
    except Exception:
        db.session.rollback()
        return error_response("UpdateError", "Failed to mark all as read", 500)


def _parse_channels(raw) -> list:
    if not raw:
        return [NotificationChannel.IN_APP.value]
    if not isinstance(raw, list):
        return []
    allowed = {c.value for c in NotificationChannel}
    out = [c for c in raw if c in allowed]
    return out or [NotificationChannel.IN_APP.value]


@notifications_bp.route("/send", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("notifications")
@require_any_permission(PERM_MANAGE)
def send_notification_route():
    """
    POST /api/notifications/send
    Body: notification_type, title, body?, channels?, extra_data?, async_support?,
          targeting: { user_ids?, role?, class_id?, include_teachers_for_class?, all_students?, all_teachers? }
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return error_response("TenantError", "Tenant context required", 400)

    data = request.get_json(silent=True) or {}
    ntype = data.get("notification_type")
    title = (data.get("title") or "").strip()
    if not ntype or not title:
        return validation_error_response("notification_type and title are required")
    if ntype not in _allowed_notification_types():
        return validation_error_response("invalid notification_type")

    targeting = data.get("targeting") or {}
    try:
        user_ids = collect_user_ids_single_mode(
            tenant_id,
            user_ids=targeting.get("user_ids"),
            role=targeting.get("role"),
            class_id=targeting.get("class_id"),
            include_teachers_for_class=bool(targeting.get("include_teachers_for_class")),
            all_students=bool(targeting.get("all_students")),
            all_teachers=bool(targeting.get("all_teachers")),
        )
    except TargetingValidationError as e:
        return validation_error_response(str(e))

    if not user_ids:
        return validation_error_response("No recipients resolved for targeting")

    channels = _parse_channels(data.get("channels"))
    extra = data.get("extra_data") if isinstance(data.get("extra_data"), dict) else {}
    async_support = data.get("async_support")
    if async_support is not None and not isinstance(async_support, bool):
        async_support = None

    body = data.get("body")

    try:
        n = create_notification(
            tenant_id=tenant_id,
            notification_type=ntype,
            title=title,
            body=body,
            extra_data=extra,
            channels=channels,
            user_id=None,
            async_support=async_support,
        )
        inserted = create_recipients(n.id, user_ids)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return error_response("CreateError", "Failed to create notification", 500)

    queued = enqueue_dispatch(n.id)
    return success_response(
        data={
            "notification_id": n.id,
            "recipient_count": inserted,
            "dispatch_queued": queued,
        },
        message="Notification created",
    )


@notifications_bp.route("/send-bulk", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("notifications")
@require_any_permission(PERM_MANAGE)
def send_bulk_notification_route():
    """
    POST /api/notifications/send-bulk
    Same body as /send but targeting union of all provided filters.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return error_response("TenantError", "Tenant context required", 400)

    data = request.get_json(silent=True) or {}
    ntype = data.get("notification_type")
    title = (data.get("title") or "").strip()
    if not ntype or not title:
        return validation_error_response("notification_type and title are required")
    if ntype not in _allowed_notification_types():
        return validation_error_response("invalid notification_type")

    targeting = data.get("targeting") or {}
    user_ids = collect_user_ids_bulk_merge(
        tenant_id,
        user_ids=targeting.get("user_ids"),
        role=targeting.get("role"),
        class_id=targeting.get("class_id"),
        include_teachers_for_class=bool(targeting.get("include_teachers_for_class")),
        all_students=bool(targeting.get("all_students")),
        all_teachers=bool(targeting.get("all_teachers")),
    )

    if not user_ids:
        return validation_error_response("No recipients resolved for targeting")

    channels = _parse_channels(data.get("channels"))
    extra = data.get("extra_data") if isinstance(data.get("extra_data"), dict) else {}
    async_support = data.get("async_support")
    if async_support is not None and not isinstance(async_support, bool):
        async_support = None

    body = data.get("body")

    try:
        n = create_notification(
            tenant_id=tenant_id,
            notification_type=ntype,
            title=title,
            body=body,
            extra_data=extra,
            channels=channels,
            user_id=None,
            async_support=async_support,
        )
        inserted = create_recipients(n.id, user_ids)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return error_response("CreateError", "Failed to create notification", 500)

    queued = enqueue_dispatch(n.id)
    return success_response(
        data={
            "notification_id": n.id,
            "recipient_count": inserted,
            "dispatch_queued": queued,
        },
        message="Bulk notification created",
    )
