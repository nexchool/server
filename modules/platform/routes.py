"""
Platform (Super Admin) API Routes

All routes require @auth_required and @platform_admin_required.
Prefix: /platform (registered at /api/platform).
"""

from flask import request, g

from backend.modules.platform import platform_bp
from backend.core.decorators import auth_required, platform_admin_required
from backend.core.extensions import limiter
from backend.shared.helpers import success_response, error_response, not_found_response, validation_error_response
from backend.modules.platform import services

# Rate limit: 30 requests per minute per IP for all platform routes
PLATFORM_LIMIT = "30 per minute"


@platform_bp.route("/plan-features", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def list_plan_features():
    """GET /platform/plan-features - List all plan feature keys and labels (for plan config UI)."""
    from backend.core.plan_features import PLAN_FEATURE_KEYS, PLAN_FEATURE_LABELS
    data = [
        {"key": k, "label": PLAN_FEATURE_LABELS.get(k, k.replace("_", " ").title())}
        for k in PLAN_FEATURE_KEYS
    ]
    return success_response(data=data)


@platform_bp.route("/plans", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def list_plans():
    """GET /platform/plans - List all plans (for tenant creation form)."""
    data = services.list_plans()
    return success_response(data=data)


@platform_bp.route("/dashboard", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def dashboard():
    """
    GET /platform/dashboard
    Returns: total_tenants, active_tenants, suspended_tenants, total_students,
             total_teachers, revenue_monthly, tenant_growth_by_month
    """
    data = services.get_dashboard_stats()
    return success_response(data=data)


@platform_bp.route("/tenants", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def create_tenant():
    """
    POST /platform/tenants
    Body: name, subdomain, contact_email?, phone?, address?, plan_id, admin_email, admin_name?
    """
    data = request.get_json() or {}
    required = ["name", "subdomain", "plan_id", "admin_email"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return validation_error_response({k: "Required" for k in missing})

    result = services.create_tenant(
        name=data["name"],
        subdomain=data["subdomain"],
        contact_email=data.get("contact_email"),
        phone=data.get("phone"),
        address=data.get("address"),
        plan_id=data["plan_id"],
        admin_email=data["admin_email"],
        admin_name=data.get("admin_name"),
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


@platform_bp.route("/tenants/<tenant_id>/change-plan", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def change_plan(tenant_id):
    """PATCH /platform/tenants/<id>/change-plan   Body: { plan_id }"""
    data = request.get_json() or {}
    plan_id = data.get("plan_id")
    if not plan_id:
        return validation_error_response({"plan_id": "Required"})
    result = services.change_tenant_plan(
        tenant_id, plan_id, platform_admin_id=g.current_user.id
    )
    if not result["success"]:
        if result["error"] == "Tenant not found":
            return not_found_response("Tenant")
        if result["error"] == "Plan not found":
            return not_found_response("Plan")
        return error_response("BadRequest", result["error"], 400)
    return success_response(data=result["tenant"], message="Plan updated")


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
    """
    GET /platform/tenants?page=1&per_page=20&status=active|suspended
    Returns paginated list with tenant info, plan name, student_count, teacher_count, status.
    """
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    per_page = min(max(per_page, 1), 100)
    status = request.args.get("status")
    result = services.list_tenants(page=page, per_page=per_page, status=status)
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
    """GET /platform/tenants/<id>/admins  List school admins for tenant."""
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
    """DELETE /platform/tenants/<id>/admins/<admin_id>  Remove admin role from user."""
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


# --- Plans CRUD ---
@platform_bp.route("/plans", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def create_plan():
    """POST /platform/plans  Body: name, price_monthly, max_students, max_teachers, features_json?"""
    data = request.get_json() or {}
    required = ["name", "price_monthly", "max_students", "max_teachers"]
    missing = [k for k in required if k not in data]
    if missing:
        return validation_error_response({k: "Required" for k in missing})
    result = services.create_plan(
        name=data["name"],
        price_monthly=float(data["price_monthly"]),
        max_students=int(data["max_students"]),
        max_teachers=int(data["max_teachers"]),
        features_json=data.get("features_json"),
        platform_admin_id=g.current_user.id,
    )
    if not result["success"]:
        return error_response("BadRequest", result["error"], 400)
    return success_response(data=result["plan"], message="Plan created", status_code=201)


@platform_bp.route("/plans/<plan_id>", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def update_plan(plan_id):
    """PATCH /platform/plans/<id>  Body: name?, price_monthly?, max_students?, max_teachers?, features_json?"""
    data = request.get_json() or {}
    result = services.update_plan(
        plan_id=plan_id,
        platform_admin_id=g.current_user.id,
        name=data.get("name"),
        price_monthly=data.get("price_monthly") if "price_monthly" in data else None,
        max_students=data.get("max_students") if "max_students" in data else None,
        max_teachers=data.get("max_teachers") if "max_teachers" in data else None,
        features_json=data.get("features_json"),
    )
    if not result["success"]:
        if result["error"] == "Plan not found":
            return not_found_response("Plan")
        return error_response("BadRequest", result["error"], 400)
    return success_response(data=result["plan"], message="Plan updated")


@platform_bp.route("/plans/<plan_id>", methods=["DELETE"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def delete_plan(plan_id):
    """DELETE /platform/plans/<id>"""
    result = services.delete_plan(plan_id, platform_admin_id=g.current_user.id)
    if not result["success"]:
        if result["error"] == "Plan not found":
            return not_found_response("Plan")
        return error_response("BadRequest", result["error"], 400)
    return success_response(message="Plan deleted")


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
    """PATCH /platform/notification-templates/<id>  Body: type?, channel?, category?, subject_template?, body_template?, is_system?"""
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
    """POST /platform/notification-templates/preview  Body: subject_template, body_template. Renders with dummy context."""
    data = request.get_json() or {}
    subject_template = data.get("subject_template", "")
    body_template = data.get("body_template", "")
    result = services.preview_notification_template(
        subject_template=subject_template,
        body_template=body_template,
    )
    if not result["success"]:
        return error_response("BadRequest", result["error"], 400)
    return success_response(data={"subject": result["subject"], "body": result["body"]})


@platform_bp.route("/notification-templates/<template_id>/preview", methods=["POST", "OPTIONS"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def preview_notification_template_by_id(template_id):
    """POST /platform/notification-templates/<id>/preview  Renders template with dummy context."""
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
    """POST /platform/notification-templates/<id>/test-send  Sends rendered template to logged-in super admin email."""
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