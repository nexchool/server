"""Device token registration API."""

from flask import Blueprint, g, request

from core.database import db
from core.decorators import auth_required, tenant_required
from core.tenant import get_tenant_id
from modules.devices import device_service
from shared.helpers import error_response, success_response, validation_error_response

# url_prefix is applied in app.register_blueprint(..., url_prefix="/api/devices")
devices_bp = Blueprint("devices", __name__)


@devices_bp.route("", methods=["GET"])
@tenant_required
@auth_required
def list_my_devices():
    """
    GET /api/devices
    List push registrations for the current user (masked token previews).
    Use to verify that POST /api/devices/register succeeded before expecting push.
    """
    tenant_id = get_tenant_id()
    user_id = getattr(g, "current_user", None) and g.current_user.id
    if not tenant_id or not user_id:
        return error_response("AuthError", "Authentication required", 401)

    rows = device_service.summarize_tokens_for_user(tenant_id, user_id)
    return success_response(data={"devices": rows, "count": len(rows)})


@devices_bp.route("/register", methods=["POST"])
@tenant_required
@auth_required
def register_device():
    """
    POST /api/devices/register
    Body: { device_token, platform, provider?, app_version? }
    """
    tenant_id = get_tenant_id()
    user_id = getattr(g, "current_user", None) and g.current_user.id
    if not tenant_id or not user_id:
        return error_response("AuthError", "Authentication required", 401)

    data = request.get_json(silent=True) or {}
    token = data.get("device_token")
    platform = data.get("platform")
    provider = data.get("provider")
    app_version = data.get("app_version")

    row, err = device_service.register_device_token(
        tenant_id=tenant_id,
        user_id=user_id,
        device_token=token,
        platform=platform,
        provider=provider,
        app_version=app_version,
    )
    if err:
        return validation_error_response(err)

    try:
        db.session.commit()
        return success_response(data=row.to_dict(), message="Device registered")
    except Exception:
        db.session.rollback()
        return error_response("ServerError", "Failed to save device", 500)


@devices_bp.route("/unregister", methods=["POST"])
@tenant_required
@auth_required
def unregister_device():
    """
    POST /api/devices/unregister
    Body: { device_token }
    """
    tenant_id = get_tenant_id()
    user_id = getattr(g, "current_user", None) and g.current_user.id
    if not tenant_id or not user_id:
        return error_response("AuthError", "Authentication required", 401)

    data = request.get_json(silent=True) or {}
    token = data.get("device_token")
    ok, err = device_service.unregister_device_token(
        tenant_id=tenant_id,
        user_id=user_id,
        device_token=token,
    )
    if err:
        return validation_error_response(err)
    if not ok:
        return error_response("Forbidden", "Invalid token ownership", 403)

    try:
        db.session.commit()
        return success_response(message="Device unregistered")
    except Exception:
        db.session.rollback()
        return error_response("ServerError", "Failed to update device", 500)
