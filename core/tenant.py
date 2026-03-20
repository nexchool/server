"""
Tenant resolution and enforcement for multi-tenant SaaS.

- Middleware: resolve tenant by subdomain or X-Tenant-ID header, set g.tenant_id / g.tenant.
- Auth: resolve_tenant_for_auth() for login/register etc. (body, header, subdomain, then default).
- Decorator: @tenant_required to enforce tenant context.
- Helper: get_tenant_id() for use in services.
"""

from functools import wraps
from typing import Optional, Tuple, Any, Dict

from flask import g, request, jsonify, current_app


def get_tenant_id():
    """Return current request's tenant_id from g. None if not in tenant context."""
    return getattr(g, "tenant_id", None)


def resolve_tenant_for_auth(
    request_body: Optional[Dict[str, Any]] = None,
    use_default: bool = True,
) -> Optional[Tuple[int, Any]]:
    """
    Resolve tenant for auth routes (login, register, etc.) when global middleware is skipped.
    Tries: (1) body tenant_id / tenantId / subdomain, (2) X-Tenant-ID header,
    (3) subdomain from Host, (4) if use_default, DEFAULT_TENANT_SUBDOMAIN from config.
    Sets g.tenant_id and g.tenant on success.
    Returns None on success, or (status_code, response) on failure (caller should return that).
    """
    from backend.core.models import Tenant
    from backend.core.models import TENANT_STATUS_ACTIVE

    if getattr(g, "tenant_id", None) is not None:
        return None

    tenant = None
    body = request_body or {}

    # 1. Request body (so login/register can send subdomain or tenant_id without UI tenant picker)
    tenant_id_from_body = body.get("tenant_id") or body.get("tenantId")
    if tenant_id_from_body:
        tenant = Tenant.query.get(tenant_id_from_body)
    if tenant is None and body.get("subdomain"):
        sub = (body.get("subdomain") or "").strip().lower()
        if sub:
            tenant = Tenant.query.filter_by(
                subdomain=sub,
                status=TENANT_STATUS_ACTIVE,
            ).first()

    # 2. Header
    if tenant is None:
        tenant_id_header = (request.headers.get("X-Tenant-ID") or "").strip()
        if tenant_id_header:
            tenant = Tenant.query.get(tenant_id_header)

    # 3. Subdomain from Host
    if tenant is None and request.host:
        parts = request.host.lower().split(".")
        if len(parts) >= 2 and parts[0] not in ("www", "api"):
            subdomain = parts[0]
            tenant = Tenant.query.filter_by(
                subdomain=subdomain,
                status=TENANT_STATUS_ACTIVE,
            ).first()
        elif len(parts) == 1 and use_default:
            default_sub = (current_app.config.get("DEFAULT_TENANT_SUBDOMAIN") or "default").strip().lower()
            tenant = Tenant.query.filter_by(
                subdomain=default_sub,
                status=TENANT_STATUS_ACTIVE,
            ).first()

    # 4. Default tenant from config (single domain / localhost)
    if tenant is None and use_default:
        default_sub = (current_app.config.get("DEFAULT_TENANT_SUBDOMAIN") or "default").strip().lower()
        if default_sub:
            tenant = Tenant.query.filter_by(
                subdomain=default_sub,
                status=TENANT_STATUS_ACTIVE,
            ).first()

    if tenant is None:
        return (
            400,
            jsonify(
                success=False,
                error="TenantRequired",
                message="Tenant is required. Provide subdomain in the request body, or X-Tenant-ID header, or use a tenant subdomain in the URL.",
            ),
        )

    if tenant.status != TENANT_STATUS_ACTIVE:
        code = 403
        msg = "Tenant is suspended" if tenant.status == "suspended" else "Tenant is not available"
        err = "TenantSuspended" if tenant.status == "suspended" else "TenantUnavailable"
        return (code, jsonify(success=False, error=err, message=msg))

    g.tenant_id = tenant.id
    g.tenant = tenant
    return None


def resolve_tenant():
    """
    Resolve tenant from request and set g.tenant_id and g.tenant.

    Resolution order:
    1. Header X-Tenant-ID (UUID string)
    2. Subdomain from Host (e.g. acme.school-erp.example.com -> acme)

    Aborts with 404 if tenant not found or 403 if tenant is suspended.
    Must run in a request context. No-op if g.tenant_id already set.
    """
    if getattr(g, "tenant_id", None) is not None:
        return

    from backend.core.models import Tenant
    from backend.core.models import TENANT_STATUS_ACTIVE

    tenant = None
    # 1. Header
    tenant_id_header = request.headers.get("X-Tenant-ID", "").strip()
    if tenant_id_header:
        tenant = Tenant.query.get(tenant_id_header)
    # 2. Subdomain
    if tenant is None and request.host:
        parts = request.host.lower().split(".")
        # Support: subdomain.domain.tld or subdomain.localhost
        if len(parts) >= 2 and parts[0] not in ("www", "api"):
            subdomain = parts[0]
            tenant = Tenant.query.filter_by(
                subdomain=subdomain,
                status=TENANT_STATUS_ACTIVE,
            ).first()
        # If single part (e.g. localhost), use default tenant by subdomain if configured
        elif len(parts) == 1:
            tenant = Tenant.query.filter_by(
                subdomain="default",
                status=TENANT_STATUS_ACTIVE,
            ).first()

    if tenant is None:
        return (
            jsonify(
                success=False,
                error="TenantNotFound",
                message="Tenant not found",
            ),
            404,
        )

    # Block suspended and deleted tenants (only active can access)
    if tenant.status != TENANT_STATUS_ACTIVE:
        error_code = "TenantSuspended" if tenant.status == "suspended" else "TenantUnavailable"
        message = "Tenant is suspended" if tenant.status == "suspended" else "Tenant is not available"
        return (
            jsonify(
                success=False,
                error=error_code,
                message=message,
            ),
            403,
        )

    g.tenant_id = tenant.id
    g.tenant = tenant


def tenant_required(fn):
    """
    Decorator that enforces tenant context.

    Ensures g.tenant_id is set (by calling resolve_tenant() if not).
    Returns 404/403 from resolve_tenant() when tenant not found or not active.
    Use on API routes that must run in a tenant context.

    Usage:
        @bp.route('/students')
        @tenant_required
        @auth_required
        def list_students():
            ...
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if getattr(g, "tenant_id", None) is None:
            result = resolve_tenant()
            if result is not None:
                return result
        return fn(*args, **kwargs)
    return wrapper
