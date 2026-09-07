"""
Platform (Super Admin) API Routes

All routes require @auth_required and @platform_admin_required.
Prefix: /platform (registered at /api/platform).
"""

import logging

from flask import request, g

from modules.platform import platform_bp
from core.database import db
from core.decorators import auth_required, platform_admin_required
from core.extensions import limiter
from core.theme import derive_palette, validate_seeds
from shared.helpers import success_response, error_response, not_found_response, validation_error_response
from modules.platform import services

logger = logging.getLogger(__name__)

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


@platform_bp.route("/theme/preview", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def preview_theme():
    """
    POST /platform/theme/preview
    Body: { seeds: { primary, secondary?, tertiary? } }

    Derives a palette without storing it, so the panel can show what a colour
    will actually do before anyone commits a school to it. Deliberately the
    same `derive_palette` the tenant endpoint uses — a preview computed
    separately is a preview that can lie.
    """
    data = request.get_json() or {}
    seeds, errors = validate_seeds(data.get("seeds"))
    if errors:
        return validation_error_response(errors)
    return success_response(data={"seeds": seeds, "colors": derive_palette(seeds)})


@platform_bp.route("/tenants/<tenant_id>/theme", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def update_tenant_theme(tenant_id):
    """
    PATCH /platform/tenants/<id>/theme
    Body: { seeds: { primary, secondary?, tertiary? } } — hex colours.
          { seeds: null } clears the theme and returns the school to the
          palette the app ships with.

    Only `primary` is required; the others fall back to it, so a school with
    one brand colour is not a form that refuses to submit.
    """
    data = request.get_json() or {}
    if "seeds" not in data:
        return validation_error_response({"seeds": "Required"})

    result = services.update_tenant_theme(
        tenant_id=tenant_id,
        platform_admin_id=g.current_user.id,
        seeds=data["seeds"],
    )
    if not result["success"]:
        if result["error"] == "Tenant not found":
            return not_found_response("Tenant")
        return validation_error_response(result.get("fields") or {"seeds": result["error"]})
    return success_response(
        data={"tenant_id": result["tenant_id"], "theme": result["theme"]},
        message="Theme updated",
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


@platform_bp.route("/tenants/<tenant_id>/auth-policy", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def get_tenant_auth_policy(tenant_id):
    """GET /platform/tenants/<id>/auth-policy

    Which authentication methods this school permits, for which of its people,
    on which surface — plus ADR-011's family access mode and the credential
    policy. Read-only in this phase; the policy is configuration that nothing
    consults yet.

    Configuration only. No account, no identifier, no credential and nothing
    secret appears in the response.
    """
    from modules.auth.policy import describe

    tenant = _resolve_target_tenant(tenant_id)
    if tenant is None:
        return not_found_response("Tenant")

    return success_response(data=describe(tenant.id))


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


# ---------------------------------------------------------------------------
# Third-party services — what NexSchool buys, and what it charges for it
#
# Platform-admin only, and that is the authorization story in full: the
# catalog holds what NexSchool pays its vendors, which is a supplier
# negotiation and not a school's business. The school's own view of what it is
# charged is on `/api/subscription/state`, with the costs stripped out.
# ---------------------------------------------------------------------------

@platform_bp.route("/service-catalog", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def list_service_catalog():
    """GET /platform/service-catalog — every provider and what it sells."""
    from modules.billing.services import list_providers

    include_inactive = str(
        request.args.get("include_inactive", "false")
    ).lower() in ("1", "true", "yes")
    return success_response(data={"providers": list_providers(include_inactive=include_inactive)})


@platform_bp.route("/service-catalog/providers", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def upsert_service_provider():
    """POST /platform/service-catalog/providers — add or correct a vendor."""
    from modules.billing.services import BillingConfigurationError, upsert_provider

    data = request.get_json(silent=True) or {}
    try:
        provider = upsert_provider(
            key=data.get("key"),
            name=data.get("name"),
            is_active=bool(data.get("is_active", True)),
        )
        db.session.commit()
    except BillingConfigurationError as exc:
        db.session.rollback()
        return validation_error_response({"provider": str(exc)})

    return success_response(data=provider.to_dict())


@platform_bp.route("/service-catalog/services", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def upsert_provider_service():
    """POST /platform/service-catalog/services — add or correct what a vendor sells."""
    from modules.billing.services import BillingConfigurationError, upsert_service

    data = request.get_json(silent=True) or {}
    try:
        service = upsert_service(
            provider_key=data.get("provider_key"),
            key=data.get("key"),
            name=data.get("name"),
            unit=data.get("unit"),
            pricing_mode=data.get("pricing_mode"),
            provider_unit_cost=data.get("provider_unit_cost"),
            is_active=bool(data.get("is_active", True)),
        )
        db.session.commit()
    except BillingConfigurationError as exc:
        db.session.rollback()
        return validation_error_response({"service": str(exc)})

    # Platform-facing, so the internal cost is shown — this is the screen where
    # somebody is deciding what to charge for it.
    return success_response(data=service.to_dict(include_provider_cost=True))


@platform_bp.route("/tenants/<tenant_id>/services", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def list_tenant_services(tenant_id):
    """GET /platform/tenants/<id>/services — what this school is signed up to."""
    from core.models import Tenant
    from modules.billing.services import describe_tenant_services

    if not Tenant.query.get(tenant_id):
        return not_found_response("Tenant")
    return success_response(data={"services": describe_tenant_services(tenant_id)})


@platform_bp.route("/tenants/<tenant_id>/services", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def configure_tenant_service(tenant_id):
    """POST /platform/tenants/<id>/services — sign a school up, or change its terms.

    Price and cost are set separately and neither is derived from the other.
    An operator who wants them equal asks for `pass_through` and says so.
    """
    from core.models import Tenant
    from modules.billing.services import (
        BillingConfigurationError,
        configure_tenant_service as _configure,
    )

    if not Tenant.query.get(tenant_id):
        return not_found_response("Tenant")

    data = request.get_json(silent=True) or {}
    try:
        configuration = _configure(
            tenant_id,
            service_key=data.get("service_key"),
            is_enabled=bool(data.get("is_enabled", True)),
            pricing_mode=data.get("pricing_mode"),
            customer_unit_price=data.get("customer_unit_price"),
            customer_fixed_price=data.get("customer_fixed_price"),
            provider_unit_cost=data.get("provider_unit_cost"),
            estimated_annual_quantity=data.get("estimated_annual_quantity"),
        )
        db.session.commit()
    except BillingConfigurationError as exc:
        db.session.rollback()
        return validation_error_response({"service": str(exc)})

    from modules.billing.services import describe_tenant_services

    return success_response(
        data={
            "tenant_service_id": configuration.id,
            "services": describe_tenant_services(tenant_id),
        }
    )


@platform_bp.route("/tenants/<tenant_id>/annual-statement", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def get_tenant_annual_statement(tenant_id):
    """GET /platform/tenants/<id>/annual-statement?on_date=YYYY-MM-DD

    The whole year in one answer: the NexSchool subscription, one component per
    third-party service, and what they add to. An **estimate** — the payload
    says so in a field — because NexSchool has no invoices and this must not be
    mistaken for one.
    """
    from modules.billing.services import tenant_annual_statement

    on_date = None
    on_date_str = request.args.get("on_date")
    if on_date_str:
        try:
            from datetime import datetime as dt

            on_date = dt.strptime(on_date_str, "%Y-%m-%d").date()
        except ValueError:
            return validation_error_response({"on_date": "Expected YYYY-MM-DD"})

    # The live count, the same question `/billing` asks, so the two agree.
    billing = services.calculate_tenant_billing(tenant_id, on_date=on_date)
    if not billing["success"]:
        return not_found_response("Tenant")

    statement = tenant_annual_statement(
        tenant_id, active_students=billing["active_students"], on_date=on_date
    )
    if statement is None:
        return not_found_response("Tenant")
    return success_response(data=statement)


# ---------------------------------------------------------------------------
# Integrations — whose wire a school's work goes down
#
# Platform-admin only, the same boundary Phase 2 drew around pricing: which
# vendor NexSchool uses, and on what terms, is a commercial decision and not a
# school's setting. Nothing here returns a credential; the configuration holds
# the *names* of environment variables and never their values.
# ---------------------------------------------------------------------------

@platform_bp.route("/tenants/<tenant_id>/auth-policy", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def update_tenant_auth_policy(tenant_id):
    """PATCH /platform/tenants/<id>/auth-policy — the school's own settings.

    The two that are not methods: whether parents sign in as themselves
    (`family_access_mode`, ADR-011) and whether a school-issued student
    credential must be replaced on first use.

    **Turning separate parent logins on provisions nobody**, and turning them
    off destroys nothing — accounts, credentials, identifiers, sessions and
    family relationships all survive, and a parent simply stops being a parent
    authentication subject. A policy change that deleted identity would be the
    worst kind of surprise, so it does not.

    Both fields are optional; sending neither is a no-op that returns the
    current policy, which is what a client refreshing its view wants.
    """
    from core.models import Tenant
    from modules.auth import policy

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return not_found_response("Tenant")

    data = request.get_json(silent=True) or {}
    family_access_mode = (data.get("family_access_mode") or "").strip()
    credential_policy = (data.get("student_credential_policy") or "").strip()

    try:
        if family_access_mode:
            policy.set_family_access_mode(
                tenant_id, family_access_mode, updated_by_user_id=g.current_user.id
            )
        if credential_policy:
            policy.set_student_credential_policy(
                tenant_id, credential_policy, updated_by_user_id=g.current_user.id
            )
        policy.ensure_default_policy(tenant_id, updated_by_user_id=g.current_user.id)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return validation_error_response({"auth_policy": str(exc)})

    return success_response(data=policy.describe(tenant_id))


@platform_bp.route("/tenants/<tenant_id>/auth-policy/methods", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def set_tenant_auth_method(tenant_id):
    """PATCH /platform/tenants/<id>/auth-policy/methods — turn a sign-in method on or off.

    The policy read has existed since Phase 0c; this is the write, added
    because `mobile_otp` is the first method a school would plausibly want
    switched on and off and there was no way to do it but a Python shell.

    **Enabling a method that cannot work is refused.** `mobile_otp` needs an
    SMS provider, and a school switched on without one would present a sign-in
    option whose codes silently never arrive. So the integration is checked
    first and the operator is told what is missing — which, until a vendor is
    selected, is every time.
    """
    from core.models import Tenant
    from modules.auth import policy
    from modules.auth.strategies import UnknownAuthenticationMethod, registry

    tenant = Tenant.query.get(tenant_id)
    if not tenant:
        return not_found_response("Tenant")

    data = request.get_json(silent=True) or {}
    method_key = (data.get("method_key") or "").strip()
    subject_kind = (data.get("subject_kind") or "").strip()
    enabled = bool(data.get("enabled"))
    surface = (data.get("surface") or "any").strip() or "any"

    if method_key not in registry:
        return validation_error_response(
            {"method_key": f"'{method_key}' is not a sign-in method this build has."}
        )

    if enabled and _method_needs_sms(method_key):
        from modules.integrations.capabilities import CAPABILITY_SMS
        from modules.integrations.health import capability_health

        report = capability_health(tenant_id=tenant_id, capability=CAPABILITY_SMS)
        if not report.ready:
            return validation_error_response(
                {
                    "method_key": (
                        "This method sends an SMS, and this school has no working "
                        "SMS provider. " + (report.detail or "")
                    ).strip()
                }
            )

    try:
        policy.ensure_default_policy(tenant_id)
        policy.set_method(
            tenant_id,
            subject_kind,
            method_key,
            enabled=enabled,
            surface=surface,
            updated_by_user_id=g.current_user.id,
        )
        db.session.commit()
    except (ValueError, UnknownAuthenticationMethod) as exc:
        db.session.rollback()
        return validation_error_response({"policy": str(exc)})

    return success_response(data=policy.describe(tenant_id))


def _method_needs_sms(method_key: str) -> bool:
    """Whether turning this method on commits a school to sending messages.

    Read from the strategy rather than a list kept here, so a future paid
    method is covered by declaring itself paid.
    """
    from modules.auth.strategies import registry

    try:
        strategy = registry.get(method_key)
    except Exception:  # noqa: BLE001
        return False
    return bool(getattr(strategy, "is_paid", False))


@platform_bp.route("/integration-capabilities", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def list_integration_capabilities():
    """GET /platform/integration-capabilities — what this build can do, and who could do it.

    Read from the registry, not the database: this is a property of the
    deployed code rather than of anybody's configuration.
    """
    from modules.integrations.services import describe_capabilities

    return success_response(data={"capabilities": describe_capabilities()})


@platform_bp.route("/tenants/<tenant_id>/integrations", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def list_tenant_integrations(tenant_id):
    """GET /platform/tenants/<id>/integrations — configured providers, with health.

    Health is a readiness report and **nothing is sent to produce it**. Finding
    out whether an SMS integration works by sending an SMS charges the school
    and rings a real person's phone.
    """
    from core.models import Tenant
    from modules.integrations.services import describe_tenant_integrations

    if not Tenant.query.get(tenant_id):
        return not_found_response("Tenant")
    return success_response(
        data={"integrations": describe_tenant_integrations(tenant_id)}
    )


@platform_bp.route("/tenants/<tenant_id>/integrations", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def configure_tenant_integration(tenant_id):
    """POST /platform/tenants/<id>/integrations — point a capability at a provider.

    Configuring never enables. A new integration starts disabled so that adding
    a row cannot start carrying traffic; somebody turns it on deliberately,
    after reading its health.

    `credential_references` takes the **names** of environment variables. A
    value pasted into that field is refused — which is the point of the field.
    """
    from core.models import Tenant
    from modules.integrations.services import (
        IntegrationConfigurationError,
        configure_integration,
        describe_tenant_integrations,
    )

    if not Tenant.query.get(tenant_id):
        return not_found_response("Tenant")

    data = request.get_json(silent=True) or {}
    try:
        configure_integration(
            tenant_id,
            capability=data.get("capability"),
            provider_key=data.get("provider_key"),
            configuration=data.get("configuration") or {},
            credential_references=data.get("credential_references") or {},
            actor_user_id=g.current_user.id,
        )
        db.session.commit()
    except IntegrationConfigurationError as exc:
        db.session.rollback()
        return validation_error_response({"integration": str(exc)})

    return success_response(
        data={"integrations": describe_tenant_integrations(tenant_id)}
    )


@platform_bp.route("/tenants/<tenant_id>/integrations/<capability>/status", methods=["PATCH"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def set_tenant_integration_status(tenant_id, capability):
    """PATCH /platform/tenants/<id>/integrations/<capability>/status

    Enabling refuses when the provider's credentials are not present on this
    server — an integration switched on that cannot possibly work produces a
    school whose messages fail silently.

    Disabling is not deleting. Configuration, usage history and billing records
    all survive, because last term's messages still have to be explicable.
    """
    from core.models import Tenant
    from modules.integrations.services import (
        IntegrationConfigurationError,
        describe_tenant_integrations,
        set_integration_status,
    )

    if not Tenant.query.get(tenant_id):
        return not_found_response("Tenant")

    data = request.get_json(silent=True) or {}
    try:
        set_integration_status(
            tenant_id,
            capability=capability,
            status=data.get("status"),
            actor_user_id=g.current_user.id,
        )
        db.session.commit()
    except IntegrationConfigurationError as exc:
        db.session.rollback()
        return validation_error_response({"integration": str(exc)})

    return success_response(
        data={"integrations": describe_tenant_integrations(tenant_id)}
    )


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
    """PATCH /platform/tenants/<id>  Body: name?, contact_email?, phone?, address?, logo_url?, tagline?, board_affiliation?, timezone?"""
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
        timezone=data.get("timezone"),
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
    return success_response(
        data={
            "admin_user_id": result["admin_user_id"],
            # One-time reveal for the panel; see add_tenant_admin.
            "temp_password": result.get("temp_password"),
        },
        message="Admin created",
        status_code=201,
    )


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


# --- Tenant onboarding (config upload → preview → apply, target tenant explicit) ---

def _resolve_target_tenant(tenant_id):
    """Load an ACTIVE target tenant for a platform op, or None. Platform routes
    skip tenant middleware, so nothing is auto-scoped — the tenant is the path
    param.

    Only ACTIVE tenants are returned, matching every login path
    (resolve_tenant_for_auth requires status == active): we never seed, nor mint
    a login link into, a suspended or soft-deleted tenant. An operator lifts a
    suspension from the panel first, then onboards / opens admin-web.
    """
    from core.models import Tenant, TENANT_STATUS_ACTIVE

    return (
        Tenant.query.filter_by(id=tenant_id, status=TENANT_STATUS_ACTIVE).first()
    )


def _parse_uploaded_config():
    """Parse the request body into a config dict, or (None, error_response).

    Two transports, one contract:
      * JSON body {"config": {...}} — the panel onboarding form.
      * multipart 'file' field (YAML or JSON) — the scripts/seed_school.py
        break-glass path.
    """
    from modules.school_setup import seed_service

    if request.is_json:
        payload = request.get_json(silent=True) or {}
        config = payload.get("config")
        if not isinstance(config, dict):
            return None, error_response(
                "ValidationError",
                "config object is required in the JSON body",
                400,
            )
        return config, None

    file = request.files.get("file")
    if file is None:
        return None, error_response(
            "ValidationError",
            "provide a JSON body with a config object, or a multipart 'file' field",
            400,
        )
    try:
        return seed_service.parse_config_bytes(file.filename or "", file.read()), None
    except seed_service.UnsupportedConfigType as e:
        return None, error_response("UnsupportedFileType", str(e), 400)
    except Exception:
        return None, error_response(
            "ParseError", "Could not parse the file. Ensure it is valid YAML or JSON.", 400
        )


def _parse_resolve_payload():
    """Validate a template-resolve body, or (None, error_response).

    Kept out of the route so it is testable without a request context, matching
    _parse_uploaded_config's shape.
    """
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        # Valid JSON (e.g. a bare list or string) is still a malformed body for
        # this endpoint -- a client mistake is a 400, never a 500.
        return None, error_response(
            "ValidationError", "request body must be a JSON object", 400
        )
    board_code = payload.get("board_code")
    programme_code = payload.get("programme_code")
    grades = payload.get("grades")

    if not board_code or not isinstance(board_code, str):
        return None, error_response("ValidationError", "board_code is required", 400)
    if not programme_code or not isinstance(programme_code, str):
        return None, error_response(
            "ValidationError", "programme_code is required", 400
        )
    if not isinstance(grades, list) or not grades:
        return None, error_response(
            "ValidationError", "grades must be a non-empty list of integers", 400
        )
    try:
        grade_numbers = sorted({int(g) for g in grades})
    except (TypeError, ValueError):
        return None, error_response(
            "ValidationError", "grades must be a non-empty list of integers", 400
        )

    return (
        {
            "board_code": board_code,
            "programme_code": programme_code,
            "grades": grade_numbers,
            "stream": payload.get("stream"),
        },
        None,
    )


@platform_bp.route("/subject-templates", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def platform_list_subject_templates():
    """List the active board templates the onboarding form can start from."""
    from modules.school_setup.template_models import SubjectTemplateGroup

    groups = (
        SubjectTemplateGroup.query.filter_by(is_active=True)
        .order_by(SubjectTemplateGroup.name)
        .all()
    )
    return success_response(data=[g.to_dict() for g in groups])


@platform_bp.route("/subject-templates/resolve", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def platform_resolve_subject_template():
    """Expand a board template into config-shaped subjects + offerings.

    Read-only preview for the form's Subjects section. The result is never
    stored -- derive_config re-runs it at apply time.
    """
    from modules.school_setup import template_service

    payload, err = _parse_resolve_payload()
    if err is not None:
        return err

    try:
        resolved = template_service.resolve_template(
            payload["board_code"],
            payload["programme_code"],
            payload["grades"],
            stream=payload["stream"],
        )
    except template_service.TemplateResolutionError as e:
        return error_response("ValidationError", str(e), 400)

    return success_response(data=resolved)


@platform_bp.route("/tenants/<tenant_id>/seed/preview", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def platform_seed_preview(tenant_id):
    """POST /platform/tenants/<id>/seed/preview — read-only diff of an uploaded
    onboarding config against the target tenant. No writes."""
    from modules.school_setup import seed_service

    tenant = _resolve_target_tenant(tenant_id)
    if tenant is None:
        return not_found_response("Tenant")

    config, err = _parse_uploaded_config()
    if err is not None:
        return err

    from modules.school_setup import onboarding_service

    try:
        config = onboarding_service.derive_config(config)
    except onboarding_service.DerivationError as e:
        return error_response("ValidationError", str(e), 400)

    # Scope the preview's reads to the target tenant (the listener no-ops when
    # g.tenant_id is unset, which it is on platform routes).
    g.tenant_id = tenant.id
    preview = seed_service.preview_seed(
        tenant.id, config, active_subdomain=tenant.subdomain
    )
    return success_response(data=preview)


@platform_bp.route("/tenants/<tenant_id>/seed/apply", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def platform_seed_apply(tenant_id):
    """POST /platform/tenants/<id>/seed/apply — seed the target tenant from an
    uploaded onboarding config. Audited as tenant.seeded."""
    from modules.school_setup import seed_service

    tenant = _resolve_target_tenant(tenant_id)
    if tenant is None:
        return not_found_response("Tenant")

    config, err = _parse_uploaded_config()
    if err is not None:
        return err

    from modules.school_setup import onboarding_service

    try:
        config = onboarding_service.derive_config(config)
    except onboarding_service.DerivationError as e:
        return error_response("ValidationError", str(e), 400)

    g.tenant_id = tenant.id
    try:
        result = seed_service.seed_school(tenant.id, config, dry_run=False, complete=True)
    except seed_service.SeedValidationError as e:
        from flask import jsonify

        return (
            jsonify(
                {
                    "success": False,
                    "error": "ValidationError",
                    "message": "Config validation failed.",
                    "details": {"errors": e.errors},
                }
            ),
            400,
        )

    try:
        services.log_platform_action(
            platform_admin_id=g.current_user.id,
            action="tenant.seeded",
            tenant_id=tenant.id,
            metadata={
                "subdomain": tenant.subdomain,
                "classes_created": result.get("classes", {}).get("created"),
                "setup_complete": result.get("setup_complete"),
            },
        )
    except Exception:
        logger.exception("Failed to audit tenant.seeded for tenant %s", tenant.id)

    return success_response(
        data=result,
        message=(
            f"Seeded {result['classes']['created']} class(es) and "
            f"{result['class_subjects']['created']} subject link(s). "
            f"Setup complete: {result['setup_complete']}."
        ),
        status_code=201,
    )


@platform_bp.route("/tenants/<tenant_id>/onboarding-draft", methods=["GET"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def platform_get_onboarding_draft(tenant_id):
    """GET the in-progress onboarding config, or an empty draft if none exists."""
    from modules.school_setup.models import TenantOnboardingDraft

    tenant = _resolve_target_tenant(tenant_id)
    if tenant is None:
        return not_found_response("Tenant")

    draft = TenantOnboardingDraft.query.filter_by(tenant_id=tenant.id).first()
    return success_response(
        data={
            "config": draft.config if draft else None,
            "updated_at": draft.updated_at.isoformat() if draft else None,
        }
    )


@platform_bp.route("/tenants/<tenant_id>/onboarding-draft", methods=["PUT"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def platform_put_onboarding_draft(tenant_id):
    """Upsert the in-progress onboarding config. Autosaved by the panel form."""
    from modules.school_setup.models import TenantOnboardingDraft

    tenant = _resolve_target_tenant(tenant_id)
    if tenant is None:
        return not_found_response("Tenant")

    payload = request.get_json(silent=True) or {}
    config = payload.get("config")
    if not isinstance(config, dict):
        return error_response(
            "ValidationError", "config object is required in the JSON body", 400
        )

    draft = TenantOnboardingDraft.query.filter_by(tenant_id=tenant.id).first()
    if draft is None:
        draft = TenantOnboardingDraft(tenant_id=tenant.id)
        db.session.add(draft)
    draft.config = config
    draft.updated_by = g.current_user.id
    db.session.commit()
    return success_response(data={"updated_at": draft.updated_at.isoformat()})


@platform_bp.route("/tenants/<tenant_id>/onboarding-draft", methods=["DELETE"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def platform_delete_onboarding_draft(tenant_id):
    """Discard the draft — called after a successful apply, or on operator reset."""
    from modules.school_setup.models import TenantOnboardingDraft

    tenant = _resolve_target_tenant(tenant_id)
    if tenant is None:
        return not_found_response("Tenant")

    TenantOnboardingDraft.query.filter_by(tenant_id=tenant.id).delete()
    db.session.commit()
    return success_response(data={"deleted": True})


@platform_bp.route("/tenants/<tenant_id>/login-link", methods=["POST"])
@limiter.limit(PLATFORM_LIMIT)
@auth_required
@platform_admin_required
def create_tenant_login_link(tenant_id):
    """POST /platform/tenants/<id>/login-link — mint a one-time, single-use link
    that opens this tenant's admin-web as the super-admin (god session), no
    password re-entry. Audited as tenant.login_link_issued."""
    from modules.auth.handoff import issue, DEFAULT_TTL_SECONDS
    from config.settings import get_admin_web_login_link_url

    tenant = _resolve_target_tenant(tenant_id)
    if tenant is None:
        return not_found_response("Tenant")

    code = issue(g.current_user.id, tenant.id)
    if not code:
        return error_response(
            "ServiceUnavailable",
            "Login links are temporarily unavailable. Please try again shortly.",
            503,
        )

    try:
        services.log_platform_action(
            platform_admin_id=g.current_user.id,
            action="tenant.login_link_issued",
            tenant_id=tenant.id,
            metadata={"subdomain": tenant.subdomain},
        )
    except Exception:
        logger.exception("Failed to audit tenant.login_link_issued for tenant %s", tenant.id)

    return success_response(
        data={
            "url": get_admin_web_login_link_url(code, tenant.subdomain),
            "subdomain": tenant.subdomain,
            "expires_in": DEFAULT_TTL_SECONDS,
        }
    )
