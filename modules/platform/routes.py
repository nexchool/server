"""
Platform (Super Admin) API Routes

All routes require @auth_required and @platform_admin_required.
Prefix: /platform (registered at /api/platform).
"""

from flask import request, g

from modules.platform import platform_bp
from core.decorators import auth_required, platform_admin_required
from core.extensions import limiter
from shared.helpers import success_response, error_response, not_found_response, validation_error_response
from modules.platform import services

# Rate limit: 30 requests per minute per IP for all platform routes
PLATFORM_LIMIT = "30 per minute"


@platform_bp.route("/feature-catalog", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def list_feature_catalog():
    """GET /platform/feature-catalog - All feature keys grouped by core/optional."""
    return success_response(data=services.list_feature_catalog())


@platform_bp.route("/dashboard", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def dashboard():
    """GET /platform/dashboard - aggregate platform metrics."""
    data = services.get_dashboard_stats()
    return success_response(data=data)


@platform_bp.route("/tenants", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def create_tenant():
    """
    POST /platform/tenants
    Body: name, subdomain, contact_email?, phone?, address?, admin_email,
          admin_name?, price_per_student_per_year?, discount_percentage?,
          discount_start_date?, discount_end_date?, feature_flags?
    """
    data = request.get_json() or {}
    required = ["name", "subdomain", "admin_email"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return validation_error_response({k: "Required" for k in missing})

    result = services.create_tenant(
        name=data["name"],
        subdomain=data["subdomain"],
        contact_email=data.get("contact_email"),
        phone=data.get("phone"),
        address=data.get("address"),
        admin_email=data["admin_email"],
        admin_name=data.get("admin_name"),
        price_per_student_per_year=data.get("price_per_student_per_year"),
        discount_percentage=data.get("discount_percentage"),
        discount_start_date=data.get("discount_start_date"),
        discount_end_date=data.get("discount_end_date"),
        feature_flags=data.get("feature_flags"),
        platform_admin_id=g.current_user.id,
        login_url=data.get("login_url"),
    )
    if not result["success"]:
        return error_response("CreationError", result["error"], 400)
    return success_response(data=result, message="Tenant created", status_code=201)


@platform_bp.route("/tenants/<tenant_id>/suspend", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def suspend_tenant(tenant_id):
    """PATCH /platform/tenants/<id>/suspend"""
    result = services.suspend_tenant(tenant_id, platform_admin_id=g.current_user.id)
    if not result["success"]:
        return error_response("NotFound", result["error"], 404)
    return success_response(data=result["tenant"], message="Tenant suspended")


@platform_bp.route("/tenants/<tenant_id>/activate", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def activate_tenant(tenant_id):
    """PATCH /platform/tenants/<id>/activate"""
    result = services.activate_tenant(tenant_id, platform_admin_id=g.current_user.id)
    if not result["success"]:
        return error_response("NotFound", result["error"], 404)
    return success_response(data=result["tenant"], message="Tenant activated")


@platform_bp.route("/tenants/<tenant_id>/pricing", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def update_tenant_pricing(tenant_id):
    """
    PATCH /platform/tenants/<id>/pricing
    Body: price_per_student_per_year?, discount_percentage?,
          discount_start_date?, discount_end_date?
    Field omitted -> unchanged. Field set to "" -> cleared.
    """
    data = request.get_json() or {}
    result = services.update_tenant_pricing(
        tenant_id=tenant_id,
        platform_admin_id=g.current_user.id,
        price_per_student_per_year=(
            data["price_per_student_per_year"] if "price_per_student_per_year" in data else None
        ),
        discount_percentage=(
            data["discount_percentage"] if "discount_percentage" in data else None
        ),
        discount_start_date=(
            data["discount_start_date"] if "discount_start_date" in data else None
        ),
        discount_end_date=(
            data["discount_end_date"] if "discount_end_date" in data else None
        ),
    )
    if not result["success"]:
        if result["error"] == "Tenant not found":
            return not_found_response("Tenant")
        return error_response("BadRequest", result["error"], 400)
    return success_response(data=result["tenant"], message="Pricing updated")


@platform_bp.route("/tenants/<tenant_id>/features", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def update_tenant_features(tenant_id):
    """
    PATCH /platform/tenants/<id>/features
    Body: { flags: { feature_key: bool, ... } }
    Only optional features may be toggled. Core features are silently kept on.
    """
    data = request.get_json() or {}
    flags = data.get("flags")
    if not isinstance(flags, dict):
        return validation_error_response({"flags": "Must be an object of feature_key -> bool"})
    result = services.update_tenant_feature_flags(
        tenant_id=tenant_id,
        platform_admin_id=g.current_user.id,
        flags=flags,
    )
    if not result["success"]:
        if result["error"] == "Tenant not found":
            return not_found_response("Tenant")
        return error_response("BadRequest", result["error"], 400)
    return success_response(
        data={"tenant_id": result["tenant_id"], "feature_flags": result["feature_flags"]},
        message="Feature flags updated",
    )


@platform_bp.route("/tenants/<tenant_id>/subscription", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def get_tenant_subscription(tenant_id):
    """GET /platform/tenants/<id>/subscription"""
    result = services.get_tenant_subscription(tenant_id)
    if not result["success"]:
        return not_found_response("Tenant")
    return success_response(data=result["subscription"])


@platform_bp.route("/tenants/<tenant_id>/subscription", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def update_tenant_subscription(tenant_id):
    """
    PATCH /platform/tenants/<id>/subscription

    Body keys (all optional):
        status                       trial | active | suspended | deleted
        trial_ends_at                YYYY-MM-DD or ISO datetime; "" clears
        billing_cycle                yearly
        price_per_student_per_year   number or "" to clear
        discount_percentage          0-100 or "" to clear
        discount_start_date          YYYY-MM-DD or "" to clear
        discount_end_date            YYYY-MM-DD or "" to clear
    """
    data = request.get_json() or {}
    fields = (
        "status",
        "trial_ends_at",
        "billing_cycle",
        "price_per_student_per_year",
        "discount_percentage",
        "discount_start_date",
        "discount_end_date",
    )
    kwargs = {f: data[f] for f in fields if f in data}
    result = services.update_tenant_subscription(
        tenant_id=tenant_id,
        platform_admin_id=g.current_user.id,
        **kwargs,
    )
    if not result["success"]:
        if result.get("error") == "Tenant not found":
            return not_found_response("Tenant")
        return error_response("BadRequest", result["error"], 400)
    return success_response(
        data=result["subscription"], message="Subscription updated"
    )


@platform_bp.route("/tenants/<tenant_id>/usage", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def get_tenant_usage(tenant_id):
    """GET /platform/tenants/<id>/usage"""
    from core.models import Tenant
    from modules.subscription.usage import get_tenant_usage as _read_usage

    if not Tenant.query.get(tenant_id):
        return not_found_response("Tenant")
    return success_response(data=_read_usage(tenant_id))


@platform_bp.route("/tenants/<tenant_id>/billing", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def get_tenant_billing(tenant_id):
    """
    GET /platform/tenants/<id>/billing?on_date=YYYY-MM-DD
    Returns active student count, base amount, applied discount, and total.
    """
    on_date_str = request.args.get("on_date")
    on_date = None
    if on_date_str:
        try:
            from datetime import datetime as dt
            on_date = dt.strptime(on_date_str, "%Y-%m-%d").date()
        except ValueError:
            return validation_error_response({"on_date": "Expected YYYY-MM-DD"})
    result = services.calculate_tenant_billing(tenant_id, on_date=on_date)
    if not result["success"]:
        return not_found_response("Tenant")
    return success_response(data=result)


@platform_bp.route("/tenants/<tenant_id>/reset-admin", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def reset_admin(tenant_id):
    """POST /platform/tenants/<id>/reset-admin"""
    result = services.reset_tenant_admin(tenant_id, platform_admin_id=g.current_user.id)
    if not result["success"]:
        if result["error"] == "Tenant not found":
            return not_found_response("Tenant")
        if "school admin" in result["error"].lower():
            return error_response("NotFound", result["error"], 404)
        return error_response("BadRequest", result["error"], 400)
    return success_response(message=result["message"])


@platform_bp.route("/tenants", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def list_tenants():
    """GET /platform/tenants?page=1&per_page=20&status=active|suspended&search=..."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    per_page = min(max(per_page, 1), 100)
    status = request.args.get("status")
    search = request.args.get("search")
    result = services.list_tenants(
        page=page, per_page=per_page, status=status, search=search
    )
    return success_response(
        data={"items": result["data"], "pagination": result["pagination"]},
        status_code=200,
    )


@platform_bp.route("/tenants/<tenant_id>", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def get_tenant(tenant_id):
    """GET /platform/tenants/<id>"""
    result = services.get_tenant_by_id(tenant_id)
    if not result["success"]:
        return error_response("NotFound", result["error"], 404)
    return success_response(data=result["tenant"])


@platform_bp.route("/tenants/<tenant_id>", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def update_tenant(tenant_id):
    """PATCH /platform/tenants/<id>  Body: name?, contact_email?, phone?, address?, logo_url?, tagline?, board_affiliation?"""
    data = request.get_json() or {}
    result = services.update_tenant(
        tenant_id=tenant_id,
        platform_admin_id=g.current_user.id,
        name=data.get("name"),
        contact_email=data.get("contact_email"),
        phone=data.get("phone"),
        address=data.get("address"),
        logo_url=data.get("logo_url"),
        tagline=data.get("tagline"),
        board_affiliation=data.get("board_affiliation"),
    )
    if not result["success"]:
        return error_response("NotFound", result["error"], 404)
    return success_response(data=result["tenant"], message="Tenant updated")


@platform_bp.route("/tenants/<tenant_id>", methods=["DELETE"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def delete_tenant_route(tenant_id):
    """DELETE /platform/tenants/<id>  Soft delete (status=deleted)."""
    result = services.delete_tenant(tenant_id, platform_admin_id=g.current_user.id)
    if not result["success"]:
        return error_response("NotFound", result["error"], 404)
    return success_response(message="Tenant deleted")


@platform_bp.route("/tenants/<tenant_id>/admins", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def list_tenant_admins(tenant_id):
    """GET /platform/tenants/<id>/admins"""
    result = services.list_tenant_admins(tenant_id)
    return success_response(data={"admins": result["admins"]})


@platform_bp.route("/tenants/<tenant_id>/admins", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def add_tenant_admin(tenant_id):
    """POST /platform/tenants/<id>/admins  Body: email, name?"""
    data = request.get_json() or {}
    email = data.get("email")
    if not email:
        return validation_error_response({"email": "Required"})
    result = services.add_tenant_admin(
        tenant_id=tenant_id,
        email=email,
        name=data.get("name"),
        platform_admin_id=g.current_user.id,
        login_url=data.get("login_url"),
    )
    if not result["success"]:
        return error_response("BadRequest", result["error"], 400)
    return success_response(data={"admin_user_id": result["admin_user_id"]}, message="Admin created", status_code=201)


@platform_bp.route("/tenants/<tenant_id>/admins/<admin_id>", methods=["DELETE"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def remove_tenant_admin_route(tenant_id, admin_id):
    """DELETE /platform/tenants/<id>/admins/<admin_id>"""
    result = services.remove_tenant_admin(
        tenant_id=tenant_id,
        admin_user_id=admin_id,
        platform_admin_id=g.current_user.id,
    )
    if not result["success"]:
        if result["error"] == "Tenant not found":
            return not_found_response("Tenant")
        if "not found" in result["error"].lower():
            return not_found_response("Admin")
        return error_response("BadRequest", result["error"], 400)
    return success_response(message="Admin removed")


@platform_bp.route("/tenants/<tenant_id>/admins/<admin_id>", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def update_tenant_admin_route(tenant_id, admin_id):
    """PATCH /platform/tenants/<id>/admins/<admin_id>  Body: name?, email?"""
    data = request.get_json() or {}
    if not data.get("name") and not data.get("email"):
        return validation_error_response({"name": "At least one of name or email is required"})
    result = services.update_tenant_admin(
        tenant_id=tenant_id,
        admin_user_id=admin_id,
        platform_admin_id=g.current_user.id,
        name=data.get("name"),
        email=data.get("email"),
    )
    if not result["success"]:
        if result["error"] == "Tenant not found":
            return not_found_response("Tenant")
        if "not found" in result["error"].lower():
            return not_found_response("Admin")
        return error_response("BadRequest", result["error"], 400)
    return success_response(message="Admin updated")


# --- Tenant notification settings ---
@platform_bp.route("/tenants/<tenant_id>/notification-settings", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def get_tenant_notification_settings(tenant_id):
    """GET /platform/tenants/<id>/notification-settings"""
    result = services.get_tenant_notification_settings(tenant_id)
    if not result["success"]:
        return not_found_response("Tenant")
    return success_response(data={
        "tenant_id": result["tenant_id"],
        "templates": result["templates"],
    })


@platform_bp.route("/tenants/<tenant_id>/notification-settings", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def patch_tenant_notification_settings(tenant_id):
    """PATCH /platform/tenants/<id>/notification-settings  Body: { templates: [...] }"""
    data = request.get_json() or {}
    templates = data.get("templates", [])
    result = services.patch_tenant_notification_settings(
        tenant_id=tenant_id,
        templates=templates,
        platform_admin_id=g.current_user.id,
    )
    if not result["success"]:
        if result["error"] == "Tenant not found":
            return not_found_response("Tenant")
        return error_response("BadRequest", result["error"], 400)
    return success_response(data={"tenant_id": result["tenant_id"]}, message="Notification settings updated")


# --- Notification templates ---
@platform_bp.route("/notification-templates", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def list_notification_templates():
    """GET /platform/notification-templates?tenant_id=&category=&type=&channel=&page=&per_page="""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    result = services.list_notification_templates(
        tenant_id=request.args.get("tenant_id"),
        category=request.args.get("category"),
        template_type=request.args.get("type"),
        channel=request.args.get("channel"),
        page=page,
        per_page=per_page,
    )
    return success_response(
        data={"items": result["items"], "pagination": result["pagination"]},
    )


@platform_bp.route("/notification-templates", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def create_notification_template():
    """POST /platform/notification-templates  Body: type, channel, category, subject_template?, body_template?, tenant_id?, is_system?"""
    data = request.get_json() or {}
    required = ["type", "channel", "category"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return validation_error_response({k: "Required" for k in missing})
    result = services.create_notification_template(
        template_type=data["type"],
        channel=data["channel"],
        category=data["category"],
        subject_template=data.get("subject_template") or "",
        body_template=data.get("body_template") or "",
        tenant_id=data.get("tenant_id"),
        is_system=bool(data.get("is_system", False)),
        platform_admin_id=g.current_user.id,
    )
    if not result["success"]:
        return error_response("BadRequest", result["error"], 400)
    return success_response(data=result["template"], message="Template created", status_code=201)


@platform_bp.route("/notification-templates/<template_id>", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def update_notification_template(template_id):
    """PATCH /platform/notification-templates/<id>"""
    data = request.get_json() or {}
    result = services.update_notification_template(
        template_id=template_id,
        platform_admin_id=g.current_user.id,
        type=data.get("type"),
        channel=data.get("channel"),
        category=data.get("category"),
        subject_template=data.get("subject_template"),
        body_template=data.get("body_template"),
        is_system=data.get("is_system"),
    )
    if not result["success"]:
        if result["error"] == "Template not found":
            return not_found_response("Template")
        return error_response("BadRequest", result["error"], 400)
    return success_response(data=result["template"], message="Template updated")


@platform_bp.route("/notification-templates/<template_id>", methods=["DELETE"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def delete_notification_template(template_id):
    """DELETE /platform/notification-templates/<id>"""
    result = services.delete_notification_template(template_id, platform_admin_id=g.current_user.id)
    if not result["success"]:
        return not_found_response("Template")
    return success_response(message="Template deleted")


@platform_bp.route("/notification-templates/preview", methods=["POST", "OPTIONS"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def preview_notification_template_unsaved():
    """POST /platform/notification-templates/preview  Body: subject_template, body_template."""
    data = request.get_json() or {}
    result = services.preview_notification_template(
        subject_template=data.get("subject_template", ""),
        body_template=data.get("body_template", ""),
    )
    if not result["success"]:
        return error_response("BadRequest", result["error"], 400)
    return success_response(data={"subject": result["subject"], "body": result["body"]})


@platform_bp.route("/notification-templates/<template_id>/preview", methods=["POST", "OPTIONS"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def preview_notification_template_by_id(template_id):
    """POST /platform/notification-templates/<id>/preview"""
    data = request.get_json() or {}
    subject_template = data.get("subject_template")
    body_template = data.get("body_template")
    if subject_template is not None and body_template is not None:
        result = services.preview_notification_template(
            subject_template=subject_template,
            body_template=body_template,
        )
    else:
        result = services.preview_notification_template(template_id=template_id)
    if not result["success"]:
        if result["error"] == "Template not found":
            return not_found_response("Template")
        return error_response("BadRequest", result["error"], 400)
    return success_response(data={"subject": result["subject"], "body": result["body"]})


@platform_bp.route("/notification-templates/<template_id>/test-send", methods=["POST", "OPTIONS"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def test_send_notification_template(template_id):
    """POST /platform/notification-templates/<id>/test-send"""
    admin_email = getattr(g.current_user, "email", None)
    if not admin_email:
        return error_response("BadRequest", "No email for current user", 400)
    result = services.test_send_notification_template(template_id, admin_email)
    if not result["success"]:
        if result["error"] == "Template not found":
            return not_found_response("Template")
        return error_response("BadRequest", result["error"], 400)
    return success_response(message=result.get("message", "Test email sent"))


# --- Audit logs ---
@platform_bp.route("/audit-logs", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def audit_logs():
    """GET /platform/audit-logs?page=1&per_page=20&action=&tenant_id=&platform_admin_id=&date_from=&date_to="""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    per_page = min(max(per_page, 1), 100)
    result = services.list_audit_logs(
        page=page,
        per_page=per_page,
        action=request.args.get("action"),
        tenant_id=request.args.get("tenant_id"),
        platform_admin_id=request.args.get("platform_admin_id"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return success_response(
        data={"items": result["data"], "pagination": result["pagination"]},
    )


# --- Platform settings ---
@platform_bp.route("/settings", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def get_settings():
    """GET /platform/settings"""
    data = services.get_platform_settings()
    return success_response(data=data)


@platform_bp.route("/settings", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def patch_settings():
    """PATCH /platform/settings  Body: { key: value, ... }"""
    data = request.get_json() or {}
    if not isinstance(data, dict):
        return validation_error_response({"body": "Must be an object"})
    services.update_platform_settings(data, platform_admin_id=g.current_user.id)
    return success_response(message="Settings updated")
