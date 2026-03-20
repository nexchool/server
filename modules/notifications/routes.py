"""
Notifications API Routes

List, mark read. Requires tenant_id and RBAC.
"""

from flask import request, g

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.core.decorators import auth_required, tenant_required, require_plan_feature
from backend.core.decorators.rbac import require_any_permission
from backend.shared.helpers import success_response, error_response, not_found_response
from backend.modules.notifications.models import Notification
from datetime import datetime


from flask import Blueprint

PERM_READ = "finance.read"
PERM_MANAGE = "finance.manage"

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@notifications_bp.route("", methods=["GET"])
@tenant_required
@auth_required
@require_plan_feature("notifications")
@require_any_permission(PERM_READ, PERM_MANAGE)
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

    query = Notification.query.filter_by(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    query = query.order_by(Notification.created_at.desc()).limit(limit).offset(offset)

    notifications = query.all()
    data = [n.to_dict() for n in notifications]
    return success_response(data={"notifications": data})


@notifications_bp.route("/<notification_id>/read", methods=["PATCH"])
@tenant_required
@auth_required
@require_plan_feature("notifications")
@require_any_permission(PERM_READ, PERM_MANAGE)
def mark_read(notification_id):
    """PATCH /api/notifications/<id>/read"""
    tenant_id = get_tenant_id()
    user_id = g.current_user.id if g.current_user else None
    if not tenant_id or not user_id:
        return error_response("AuthError", "Context required", 400)

    n = Notification.query.filter_by(
        id=notification_id,
        tenant_id=tenant_id,
        user_id=user_id,
    ).first()
    if not n:
        return not_found_response("Notification")

    try:
        n.read_at = datetime.utcnow()
        db.session.commit()
        return success_response(data=n.to_dict())
    except Exception:
        db.session.rollback()
        return error_response("UpdateError", "Failed to mark as read", 500)


@notifications_bp.route("/mark-all-read", methods=["POST"])
@tenant_required
@auth_required
@require_plan_feature("notifications")
@require_any_permission(PERM_READ, PERM_MANAGE)
def mark_all_read():
    """POST /api/notifications/mark-all-read"""
    tenant_id = get_tenant_id()
    user_id = g.current_user.id if g.current_user else None
    if not tenant_id or not user_id:
        return error_response("AuthError", "Context required", 400)

    try:
        updated = Notification.query.filter_by(
            tenant_id=tenant_id,
            user_id=user_id,
        ).filter(Notification.read_at.is_(None)).update(
            {Notification.read_at: datetime.utcnow()},
            synchronize_session=False,
        )
        db.session.commit()
        return success_response(data={"updated_count": updated})
    except Exception:
        db.session.rollback()
        return error_response("UpdateError", "Failed to mark all as read", 500)
