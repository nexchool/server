"""
Authentication Routes

API endpoints for user authentication, registration, and account management.

Routes:
- POST /login - Login user
- POST /logout - Logout user
- GET /email/validate - Validate email verification token
- POST /password/forgot - Request password reset
- POST /password/reset - Reset password with token
"""

from flask import request, jsonify, redirect, g, current_app
from urllib.parse import quote
import logging
import os

from core.tenant import get_tenant_id, resolve_tenant_for_auth
from shared.s3_utils import (
    normalize_stored_file_value_for_db,
    profile_picture_public_url,
    upload_file,
)
from shared.storage_constants import PROFILE_PICTURES, TENANTS
from . import auth_bp
from .models import User, Session
from . import services
from .services import (
    authenticate_user,
    find_users_by_email_password,
    generate_access_token,
    create_session,
    logout_user as logout_user_service,
    # The lockout rule and its constants have one owner in `services`, so the
    # two login paths cannot drift apart again.
    LOGIN_LOCKOUT_MINUTES,  # noqa: F401 (re-exported)
)
from core.decorators import auth_required, tenant_required, require_permission  # tenant_required still used for routes that run after middleware
from core.database import db
from core.extensions import actor_rate_key, limiter
from shared.helpers import success_response, error_response, not_found_response
from core.school_time import utc_now
from core.theme import resolve_theme

logger = logging.getLogger(__name__)

PROFILE_PICTURE_MAX_BYTES = 5 * 1024 * 1024
PROFILE_PICTURE_ALLOWED_MIME = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/webp"}
)


# ==================== REGISTRATION ====================

# Public self-registration was removed (2026-08-30). `POST /api/auth/register`
# was unauthenticated and unrated, and resolved its tenant with use_default=True
# — a request naming no school landed in DEFAULT_TENANT_SUBDOMAIN, which prod
# sets to `default`. It created a real account, granted it DEFAULT_USER_ROLE
# ("Student"), and emailed the verification link to the address the caller had
# just typed, so a stranger verified themselves into a live school.
#
# There is no self-service signup in this product and never was: a school issues
# credentials. Students arrive by bulk import or admission, staff through the
# admin console, tenants through the panel — and under ADR-011 a household shares
# the pupil's login, so there is not even a parent to sign up.
#
# The Expo app's Sign Up link and register screen are removed with it.


# ==================== TENANT BRANDING (public) ====================

@auth_bp.route('/tenant-branding', methods=['GET'])
def tenant_branding():
    """
    GET /api/auth/tenant-branding

    Returns public branding info for the resolved tenant. No authentication required.
    Tenant is resolved from X-Tenant-Subdomain header (sent automatically by admin-web),
    X-Tenant-ID header, or Host subdomain — in that order.

    Used by the admin-web login page to show the school name before the user signs in.

    Responses:
      200: { data: { name, subdomain, logo_url, tagline, login_variant } }
      404: no tenant could be resolved from the request
    """
    from modules.auth.policy import published_auth_methods

    err = resolve_tenant_for_auth(use_default=False)
    if err:
        return error_response('No school found for this address', status_code=404)

    tenant = g.tenant
    flags = tenant.feature_flags or {}
    # Opt-in: default to "default" so tenants without the flag keep the standard
    # login. Deliberately NOT is_feature_enabled() — that treats a missing key as
    # enabled, which would flip every school onto a custom layout.
    login_variant = flags.get('login_variant') or 'default'
    return success_response(data={
        'name': tenant.name,
        'subdomain': tenant.subdomain,
        'logo_url': tenant.logo_url,
        'tagline': tenant.tagline,
        'login_variant': login_variant,
        # Which ways in this school allows, so the sign-in screen can offer
        # them. The union across the kinds of person a school has, never per
        # person — which methods a school offers is visible on its login page
        # anyway; which method a *particular* human may use is not, and is
        # never published here.
        'auth': {'methods': published_auth_methods(tenant.id)},
        # The school's colours, resolved to the token set the mobile app draws
        # with. Null for a school that has never been themed, which the app
        # reads as "use the palette you shipped with" — see core/theme.py.
        # Public on purpose: the sign-in screen is branded before anyone has
        # signed in, and none of this is secret.
        'theme': resolve_theme(tenant),
    })


# ==================== LOGIN ====================



@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    """Sign in.

    Two implementations live behind this route during the pipeline migration.
    `auth_pipeline_enabled` chooses between them, and it exists so that
    authentication can be returned to the path it used before Phase 0d without
    a deployment. Missing means enabled: the pipeline is the intended path, and
    a setting nobody has written must never be able to turn sign-in off.

    Both produce the same responses. `_login_through_pipeline` is the new one;
    `_login_legacy` below is the previous implementation, unchanged, kept as
    the rollback target rather than deleted.
    """
    from .pipeline import pipeline_enabled

    if pipeline_enabled():
        return _login_through_pipeline()
    return _login_legacy()


def _login_through_pipeline():
    """Sign in through the strategy pipeline.

    The route's whole job is translation: build the request, run the pipeline,
    turn its outcome into HTTP, and hand a success to the existing
    finalization — which is untouched by this phase.
    """
    from .pipeline import (
        AuthenticationRequest,
        AuthenticationService,
        clear_context,
        publish_context,
    )

    attempt = AuthenticationRequest.from_flask(request)
    outcome = AuthenticationService().authenticate(attempt)

    if outcome.needs_tenant_choice:
        return success_response(
            data={
                'requires_tenant_choice': True,
                'tenants': [
                    {'id': t.id, 'name': t.name, 'subdomain': t.subdomain}
                    for t in outcome.tenant_choices
                ],
            },
            message='Choose your school',
            status_code=200,
        )

    if not outcome.succeeded:
        # A tenant that could not be resolved keeps the resolver's own
        # response, so its wording and status are exactly what they were.
        prepared = getattr(outcome, '_tenant_response', None)
        if prepared is not None:
            return prepared[1], prepared[0]
        return error_response(
            error=outcome.error,
            message=outcome.message,
            status_code=outcome.status_code,
        )

    # The entered school scopes everything after this point.
    g.tenant_id = outcome.tenant.id if outcome.tenant else None
    g.tenant = outcome.tenant

    # Using a code sent to a number is the proof of possession that issuing the
    # identifier deliberately did not claim. Recorded here, once the pipeline
    # has accepted the attempt and before finalization — which stays untouched.
    if outcome.method_key == 'mobile_otp' and outcome.identifier is not None:
        from .provisioning import mark_mobile_verified

        mark_mobile_verified(outcome.identifier)

    publish_context(outcome)
    try:
        return _finalize_login(
            outcome.account, outcome.tenant, is_god_login=outcome.is_god_login
        )
    finally:
        clear_context()


def _login_legacy():
    """
    Login with email and password.

    Single app for all schools: if the request has no tenant (no tenant_id/subdomain in body,
    no X-Tenant-ID, no subdomain in host), we search across all tenants for a user with that
    email and password. If exactly one match -> login success. If multiple matches -> return
    list of schools so the app can show "Which school?" and send tenant_id on second attempt.

    If tenant is provided (body, header, or host), we authenticate only in that tenant (current behavior).
    """
    from datetime import datetime, timedelta

    # silent=True: a missing/malformed/non-JSON body degrades to {} and falls to the
    # email/password validation below (clean 400), rather than raising 415/400 here.
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip()
    password = data.get('password')
    tenant_id_in_body = data.get('tenant_id') or data.get('tenantId')
    subdomain_in_body = (data.get('subdomain') or '').strip()

    if not email or not password:
        return error_response(
            error='ValidationError',
            message='Email and password are required',
            status_code=400
        )

    user = None
    tenant = None
    is_god_login = False

    if tenant_id_in_body or subdomain_in_body:
        # Tenant specified: resolve tenant then authenticate in that tenant only
        err = resolve_tenant_for_auth(data)
        if err:
            return err[1], err[0]
        tenant_id = get_tenant_id()
        user_by_email = User.get_user_by_email(email, tenant_id=tenant_id)
        if user_by_email and not getattr(user_by_email, 'is_platform_admin', False):
            from modules.platform.services import get_platform_settings
            settings = get_platform_settings()
            if settings.get('maintenance_mode') == 'true':
                return error_response(
                    error='MaintenanceMode',
                    message='Logins are temporarily disabled. Please try again later.',
                    status_code=503
                )
            if user_by_email.login_locked_until and user_by_email.login_locked_until > utc_now():
                return error_response(
                    error='TooManyAttempts',
                    message='Account temporarily locked due to too many failed attempts. Try again later.',
                    status_code=429
                )
        user = authenticate_user(email, password, tenant_id=tenant_id)
        if not user:
            # God-login: a real tenant user with this email keeps today's
            # behavior (precedence). Only when no tenant user authenticated do
            # we try the platform super-admin, who can enter any tenant with
            # their own credentials.
            from .services import authenticate_platform_admin
            platform_admin = authenticate_platform_admin(email, password)
            if platform_admin:
                user = platform_admin
                is_god_login = True
            else:
                # No god access: run the normal failed-login lockout. Skip it
                # for the platform-admin email path (no tenant user_by_email).
                if user_by_email:
                    from modules.auth.services import (
                        max_login_attempts,
                        record_failed_login,
                    )
                    record_failed_login(
                        user_by_email, max_attempts=max_login_attempts()
                    )
                return error_response(
                    error='InvalidCredentials',
                    message='Invalid email or password',
                    status_code=401
                )
        tenant = getattr(g, "tenant", None)
    else:
        # No tenant: search across all tenants (single app for all schools)
        matches = find_users_by_email_password(email, password)
        if len(matches) == 0:
            # Count the guess. This branch is chosen by the *body* alone, so
            # without this an attacker omits `tenant_id` and guesses forever
            # against any account — the per-IP rate limit being the only thing
            # left, which a rotating-IP attacker ignores. Every school this
            # email belongs to counts it, the same way naming one school does.
            from modules.auth.services import (
                accounts_for_email,
                max_login_attempts,
                record_failed_login,
            )
            limit = max_login_attempts()
            for account in accounts_for_email(email):
                record_failed_login(account, max_attempts=limit)
            return error_response(
                error='InvalidCredentials',
                message='Invalid email or password',
                status_code=401
            )
        if len(matches) > 1:
            return success_response(
                data={
                    'requires_tenant_choice': True,
                    'tenants': [
                        {'id': t.id, 'name': t.name, 'subdomain': t.subdomain}
                        for _, t in matches
                    ]
                },
                message='Choose your school',
                status_code=200
            )
        user, tenant = matches[0]
        g.tenant_id = tenant.id
        g.tenant = tenant
        # Apply maintenance and lockout for this tenant user
        if not getattr(user, 'is_platform_admin', False):
            from modules.platform.services import get_platform_settings
            settings = get_platform_settings()
            if settings.get('maintenance_mode') == 'true':
                return error_response(
                    error='MaintenanceMode',
                    message='Logins are temporarily disabled. Please try again later.',
                    status_code=503
                )
            if user.login_locked_until and user.login_locked_until > utc_now():
                return error_response(
                    error='TooManyAttempts',
                    message='Account temporarily locked due to too many failed attempts. Try again later.',
                    status_code=429
                )

    # Common success path (user and tenant are set)
    return _finalize_login(user, tenant, is_god_login)


def _finalize_login(user, tenant, is_god_login):
    """Issue tokens, session, and cookie for an already-authenticated user in a
    resolved tenant, and build the admin-web login response.

    Shared by password login (above) and the one-time login-link redemption, so
    both paths return an identical shape and honor the same god-login gates.
    """
    from datetime import datetime

    # Block suspended accounts on both login paths (tenant-specified and
    # cross-tenant search) before any token is issued. Platform admins are
    # not suspended in practice, so a single gate on is_suspended is enough.
    if getattr(user, 'is_suspended', False):
        return error_response(
            error='AccountSuspended',
            message='This account has been suspended. Contact your school administrator.',
            status_code=403
        )

    # Platform super-admin entering a tenant (god-login) bypasses the email
    # verification and permission gates — their authority is the platform flag,
    # not a tenant role. is_platform_admin is authoritative here.
    is_platform_admin = getattr(user, 'is_platform_admin', False)

    if not is_platform_admin and not user.email_verified:
        return error_response(
            error='EmailNotVerified',
            message='Please verify your email before logging in',
            status_code=401
        )

    # Backfill tenant role permissions when DEFAULT_ROLES gains new entries
    # (idempotent). Ensures admins keep parity with seed_rbac after upgrades.
    if not is_platform_admin and getattr(user, "tenant_id", None):
        from modules.rbac.role_seeder import seed_roles_for_tenant

        seed_roles_for_tenant(user.tenant_id)

    if is_platform_admin:
        # God-mode: synthetic permission so the UI unlocks everything without a
        # tenant role. Plan-gated features are not applied to the super-admin.
        permissions = ["system.manage"]
        enabled_features = []
    else:
        from modules.rbac.services import get_user_permissions
        permissions = get_user_permissions(user.id)
        if not permissions or len(permissions) == 0:
            return error_response(
                error='NoPermissions',
                message='No permissions assigned. Contact administrator.',
                status_code=403
            )

    if not getattr(user, 'is_platform_admin', False):
        user.failed_login_count = 0
        user.login_locked_until = None

    user.last_login_at = utc_now()
    user.save()

    access_minutes = None
    if not getattr(user, 'is_platform_admin', False):
        try:
            from modules.platform.services import get_platform_setting
            mins = get_platform_setting('session_timeout_minutes')
            if mins and str(mins).isdigit():
                access_minutes = max(5, min(10080, int(mins)))
        except Exception:
            # Falling back to the default token lifetime is the right
            # behaviour — a login must not fail because a setting could not be
            # read. But it used to `pass`, so if this started failing every
            # session would quietly ignore the configured timeout and nobody
            # would know. Degrade, and say so.
            logger.warning(
                'Could not read session_timeout_minutes; using the default '
                'token lifetime', exc_info=True,
            )

    # The session first, then the token — the one ordering change this phase
    # makes inside `_finalize_login`, and it is load-bearing rather than
    # tidiness. An access token names the session it came from, and validation
    # checks that session is still live; a token minted before its session
    # existed would carry no name, and revoking the session would go on being
    # a promise about the future instead of taking effect now.
    session = create_session(user, request)
    access_token = generate_access_token(
        user, access_minutes=access_minutes, session_id=session.id
    )

    if not is_platform_admin:
        from core.feature_flags import get_tenant_enabled_features
        enabled_features = get_tenant_enabled_features(tenant.id) if tenant else []
    # For platform admins, enabled_features was already set to [] above.

    # The resolved (entered) tenant scopes every subsequent admin-web request,
    # so report it here — not the user's home tenant_id. For a normal user
    # these are the same value.
    resolved_tenant_id = str(tenant.id) if tenant else (
        str(user.tenant_id) if getattr(user, 'tenant_id', None) else None
    )

    # Setup state for the entered tenant (drives the SetupGate in admin-web).
    is_setup_complete = bool(getattr(tenant, 'is_setup_complete', False)) if tenant else False

    from modules.rbac.services import is_subadmin_user
    is_subadmin = (
        is_subadmin_user(user.id, tenant.id)
        if (tenant and not is_platform_admin)
        else False
    )

    # Branch (school-unit) scope for the frontend. None = unrestricted (all
    # branches), incl. platform admins. get_allowed_unit_ids() reads
    # g.current_user / g.tenant_id, which aren't set on the login path, so seed
    # them first; convert the set to a sorted JSON-serializable list.
    g.current_user = user
    from core.branch_scope import get_allowed_unit_ids
    _allowed_units = get_allowed_unit_ids()
    allowed_unit_ids = sorted(_allowed_units) if _allowed_units is not None else None

    # Audit the god entry — best effort; never fail login if audit write fails.
    if is_god_login and tenant:
        try:
            from modules.platform.services import log_platform_action
            log_platform_action(
                platform_admin_id=user.id,
                action="tenant.admin_web_entered",
                tenant_id=tenant.id,
                metadata={"subdomain": tenant.subdomain},
            )
        except Exception:
            logger.exception("Failed to audit god-login for tenant %s", tenant.id)

    response, status_code = success_response(
        data={
            'access_token': access_token,
            'refresh_token': session.issued_refresh_token,
            'tenant_id': resolved_tenant_id,
            'subdomain': tenant.subdomain if tenant else None,
            'tenant_name': tenant.name if tenant else None,
            'user': {
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'email_verified': user.email_verified,
                'profile_picture_url': profile_picture_public_url(user.profile_picture_url),
            },
            'permissions': permissions,
            'enabled_features': enabled_features,
            'is_platform_admin': is_platform_admin,
            'is_subadmin': is_subadmin,
            'is_setup_complete': is_setup_complete,
            'force_password_reset': bool(user.force_password_reset),
            'allowed_unit_ids': allowed_unit_ids,
        },
        message='Login successful',
        status_code=200
    )

    jwt_expires = current_app.config.get('JWT_ACCESS_TOKEN_EXPIRES')
    cookie_minutes = access_minutes if access_minutes is not None else (
        int(jwt_expires.total_seconds() / 60) if jwt_expires else 15
    )
    response.set_cookie(
        key='auth-token',
        value=access_token,
        max_age=cookie_minutes * 60,
        httponly=True,
        samesite=current_app.config.get('SESSION_COOKIE_SAMESITE', 'Lax'),
        secure=current_app.config.get('SESSION_COOKIE_SECURE', not current_app.debug),
    )
    return response, status_code


@auth_bp.route('/login-link/redeem', methods=['POST'])
@limiter.limit("20 per minute")
def login_link_redeem():
    """Redeem a one-time platform-admin handoff code for a tenant god-login session.

    Public by design: possession of a valid, unexpired, single-use code IS the
    credential — only a platform admin can mint one via
    ``POST /api/platform/tenants/<id>/login-link``. The code is consumed
    atomically on first use. Returns the same shape as password login so
    admin-web's session handling is unchanged.
    """
    from .handoff import redeem as redeem_handoff
    from core.authentication import load_without_tenant_scope
    from core.models import Tenant, TENANT_STATUS_ACTIVE

    data = request.get_json(silent=True) or {}
    code = (data.get('code') or '').strip()
    payload = redeem_handoff(code)
    if not payload:
        return error_response(
            error='InvalidLoginLink',
            message='This login link is invalid or has expired. Generate a new one from the panel.',
            status_code=401,
        )

    # Identity comes from the code, not the request tenant. Load the platform
    # admin unscoped (their User row lives in their home tenant) and the target.
    user = load_without_tenant_scope(
        lambda: User.query.filter_by(
            id=payload['admin_id'], is_platform_admin=True
        ).filter(User.deleted_at.is_(None)).first()
    )
    # Only ACTIVE tenants, mirroring resolve_tenant_for_auth on the password
    # login path — a suspended/deleted tenant blocks login for everyone,
    # super-admin included. Un-suspend from the panel first.
    tenant = (
        Tenant.query.filter_by(
            id=payload['tenant_id'], status=TENANT_STATUS_ACTIVE
        ).first()
    )
    if not user or not tenant:
        return error_response(
            error='InvalidLoginLink',
            message='This login link is invalid or has expired. Generate a new one from the panel.',
            status_code=401,
        )

    g.tenant_id = tenant.id
    g.tenant = tenant
    return _finalize_login(user, tenant, is_god_login=True)


# ==================== LOGOUT ====================

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    Logout user by revoking the session.
    Tenant from X-Tenant-ID header or default.
    
    Whichever token the caller holds identifies **one** session, and that one
    session ends. Three ways in, in order of directness:

        Authorization: Bearer <access token>   every current client
        auth-token cookie                      the panel, cross-origin
        X-Refresh-Token                        older builds

    The access token is preferred because it names its session in a `sid`
    claim, so nothing has to be looked up — and because the refresh token is
    no longer sent on ordinary requests: once a refresh token may be spent
    only once, a client cannot attach it to everything.

    **Never every session.** The cookie branch used to call
    `revoke_all_user_sessions`, which meant an unauthenticated request
    carrying only a cookie could sign somebody out of every device they owned
    — and because the production cookie is `SameSite=None`, any site could
    cause it. Signing a person out of their phone from a page they merely
    visited is not a logout, it is a denial of service with a friendly name.
    Signing out everywhere is still available, deliberately, at
    `DELETE /api/auth/sessions`, which is authenticated.

    Returns:
        200: Logout successful
        400: No token of any kind
    """
    err = resolve_tenant_for_auth()
    if err:
        return err[1], err[0]

    from modules.auth.services import validate_jwt_token

    refresh_token = request.headers.get("X-Refresh-Token")
    header = request.headers.get("Authorization") or ""
    access_token = (
        header[7:].strip() if header.lower().startswith("bearer ") else None
    ) or request.cookies.get("auth-token")

    session_id = None
    if access_token:
        payload = validate_jwt_token(access_token, token_type="access")
        if payload:
            session_id = payload.get("sid")

    if session_id:
        from core.authentication import load_without_tenant_scope

        session = load_without_tenant_scope(
            lambda: Session.query.filter_by(id=session_id, revoked=False).first()
        )
        if session is not None:
            session.revoke()
            from modules.auth.tokens import revoke_session_tokens

            revoke_session_tokens(session.id)
            db.session.commit()
    elif refresh_token:
        logout_user_service(refresh_token)
    elif not access_token:
        return error_response(
            error='ValidationError',
            message='A token is required to sign out.',
            status_code=400
        )
    # An access token that is present but unreadable — expired, or from a
    # build before sessions were named — is not an error to report. There is
    # nothing to end, and the client is about to discard it anyway.

    response, status_code = success_response(
        message='User logged out successfully',
        status_code=200
    )
    response.delete_cookie('auth-token')
    return response, status_code


# ==================== EMAIL VERIFICATION ====================

@auth_bp.route('/email/validate', methods=['GET'])
def validate_email():
    """
    Validate email verification token and auto-login user.
    
    Query Parameters:
        - token: Verification token (required)
        - email: User email (required)
    Tenant from X-Tenant-ID header, Host subdomain, or default.
    """
    err = resolve_tenant_for_auth()
    if err:
        from config.settings import get_app_verification_error_url
        return redirect(get_app_verification_error_url(quote("Tenant is required")))

    from config.settings import get_app_verification_success_url, get_app_verification_error_url
    from modules.rbac.services import get_user_permissions

    token = request.args.get('token')
    email = request.args.get('email')

    # Validation
    if not token:
        return redirect(get_app_verification_error_url(quote('Token is required')))
    
    if not email:
        return redirect(get_app_verification_error_url(quote('Email is required')))

    # Get user (tenant-scoped)
    user = User.get_user_by_email(email, tenant_id=get_tenant_id())
    if not user:
        return redirect(get_app_verification_error_url(quote('User not found')))
    
    # Check if already verified
    if user.email_verified:
        return redirect(get_app_verification_error_url(quote('Email already verified. Please login.')))
    
    # Validate token
    if user.verification_token != token:
        return redirect(get_app_verification_error_url(quote('Invalid or expired token')))
    
    # Mark as verified
    user.verification_token = None
    user.email_verified = True
    user.save()

    # Send welcome email via notification dispatcher
    from modules.notifications.services import notification_dispatcher
    from modules.notifications.enums import NotificationChannel

    features = [
        "Access to exclusive content",
        "Personalized recommendations",
        "Priority customer support",
    ]
    notification_dispatcher.dispatch(
        user_id=user.id,
        tenant_id=get_tenant_id(),
        notification_type="WELCOME",
        channels=[NotificationChannel.EMAIL.value],
        title="Welcome!",
        body=None,
        extra_data={"email": email, "features": features},
    )

    # Check user permissions before auto-login
    permissions = get_user_permissions(user.id)
    if not permissions or len(permissions) == 0:
        return redirect(get_app_verification_error_url(
            quote('Email verified successfully, but no permissions assigned. Contact administrator.')
        ))

    # Auto-login: the session first, so the token can name it. See
    # `_finalize_login` for why the order matters.
    session = create_session(user, request)
    access_token = generate_access_token(user, session_id=session.id)

    # Redirect to app with tokens
    return redirect(get_app_verification_success_url(
        access_token=access_token,
        refresh_token=session.issued_refresh_token,
        user_id=user.id,
        email=user.email
    ))


# ==================== PASSWORD RESET ====================

@auth_bp.route('/password/forgot', methods=['POST'])
@limiter.limit("5 per minute")
def forgot_password():
    """
    Request password reset email.
    Tenant from body (subdomain/tenant_id), X-Tenant-ID header, or default.
    """
    err = resolve_tenant_for_auth(request.get_json(silent=True) or {})
    if err:
        return err[1], err[0]

    from config.settings import get_reset_password_url, get_admin_web_reset_url
    from modules.notifications.services import notification_dispatcher
    from modules.notifications.enums import NotificationChannel

    data = request.get_json()
    email = data.get('email')
    platform = (data or {}).get('platform')

    if not email:
        return error_response(
            error='ValidationError',
            message='Email is required',
            status_code=400
        )

    # Get user in current tenant (but don't reveal if exists or not)
    user = User.get_user_by_email(email, tenant_id=get_tenant_id())

    if user:
        # Generate reset token
        token = user.generate_reset_password_token()
        user.save()

        # Send reset email via notification dispatcher. Web (admin-web/panel)
        # needs a browser link; mobile clients keep the app deep link.
        if platform == "web":
            reset_url = get_admin_web_reset_url(token, email, g.tenant.subdomain)
        else:
            reset_url = get_reset_password_url(token, email)
        notification_dispatcher.dispatch(
            user_id=user.id,
            tenant_id=get_tenant_id(),
            notification_type="PASSWORD_RESET",
            channels=[NotificationChannel.EMAIL.value],
            title="Reset your password",
            body=None,
            extra_data={
                "reset_url": reset_url,
                "expires_in": os.getenv("RESET_TOKEN_EXP_MINUTES", 30),
            },
        )

    # Always return success (security best practice - don't reveal if email exists)
    return success_response(
        message='If the email exists, a reset link has been sent',
        status_code=200
    )


@auth_bp.route('/password/reset', methods=['POST'])
@limiter.limit("5 per minute")
def reset_password():
    """
    Reset password using reset token.
    Tenant from body (subdomain/tenant_id), X-Tenant-ID header, or default.
    
    Request Body:
        - email: User email (required)
        - token: Reset token (required)
        - new_password: New password (required)
        
    Returns:
        200: Password reset successful
        400: Invalid or expired token
    """
    err = resolve_tenant_for_auth(request.get_json(silent=True) or {})
    if err:
        return err[1], err[0]

    data = request.get_json()
    email = data.get('email')
    token = data.get('token')
    new_password = data.get('new_password')

    # Validation
    if not email or not token or not new_password:
        return error_response(
            error='ValidationError',
            message='Email, token, and new password are required',
            status_code=400
        )

    # Get user in current tenant and validate token
    user = User.get_user_by_email(email, tenant_id=get_tenant_id())
    if not user or not user.is_reset_token_valid(token):
        return error_response(
            error='InvalidToken',
            message='Invalid or expired token',
            status_code=400
        )

    # Enforce the same strength rule as the self-serve change flow.
    from .services import _is_password_strong
    if not _is_password_strong(new_password):
        return error_response(
            error='password_weak',
            message='Password must be at least 8 characters and include a digit',
            status_code=422
        )

    # Update password
    user.set_password(new_password)
    user.reset_password_token = None
    user.reset_password_sent_at = None
    user.save()

    # Revoke all sessions (force re-login on all devices)
    sessions = Session.query.filter_by(user_id=user.id, revoked=False).all()
    for session in sessions:
        session.revoke()

    return success_response(
        message='Password reset successful',
        status_code=200
    )


@auth_bp.route('/password/force-reset', methods=['POST'])
@auth_required
@limiter.limit("5 per minute")
def force_reset_password():
    """Set a new password for the authenticated user and clear the force flag.

    Used for the mandatory first-login change after an admin provisions or
    resets an account (force_password_reset=True). Preserves the caller's
    current session — the one their access token names — and revokes the
    rest, so that a password somebody else may have seen stops working
    everywhere except here.

    Body:
        - new_password (required, must pass strength rule)

    Responses:
        200: password updated, force_password_reset cleared
        401: not authenticated
        422: new_password missing or weak
    """
    from .services import _is_password_strong

    data = request.get_json(silent=True) or {}
    new_password = data.get('new_password')

    if not new_password or not _is_password_strong(new_password):
        return error_response(
            error='password_weak',
            message='Password must be at least 8 characters and include a digit',
            status_code=422
        )

    user = g.current_user
    user.set_password(new_password)
    user.force_password_reset = False

    # Revoke every other active session; keep the caller's current one.
    # Only when that one can be identified — otherwise skip revocation rather
    # than sign the caller out of the session they are setting the password
    # from, which would strand them.
    from .session_admin import current_session_id
    from .tokens import revoke_session_tokens

    current = current_session_id()

    if current is not None:
        others = Session.query.filter_by(user_id=user.id, revoked=False).filter(
            Session.id != current
        )
        for session in others.all():
            session.revoke()
            revoke_session_tokens(session.id)
    else:
        logger.warning(
            "force-reset: no current session identified; skipping "
            "other-session revocation for user %s", user.id
        )

    user.save()

    return success_response(
        message='Password updated successfully',
        status_code=200
    )


# ==================== ENABLED FEATURES (lightweight, for app-focus refresh) ====================

@auth_bp.route('/enabled-features', methods=['GET'])
@auth_required
def get_enabled_features():
    """
    Lightweight endpoint returning only plan-enabled features for the current tenant.
    Used by the client when app returns to foreground to reflect plan changes without full re-login.
    """
    err = resolve_tenant_for_auth()
    if err:
        return err[1], err[0]

    user = g.current_user
    if not user or not user.tenant_id:
        return success_response(data={'enabled_features': []}, status_code=200)

    from core.feature_flags import get_tenant_enabled_features
    enabled_features = get_tenant_enabled_features(user.tenant_id)
    return success_response(data={'enabled_features': enabled_features}, status_code=200)


# ==================== TENANT BRANDING (public) ====================

# ==================== PROFILE ====================

@auth_bp.route('/profile', methods=['GET'])
@auth_required
def get_profile():
    """Get current user profile. Tenant from X-Tenant-ID header or default."""
    err = resolve_tenant_for_auth()
    if err:
        return err[1], err[0]

    user = g.current_user

    from core.models import Tenant
    from core.feature_flags import get_tenant_enabled_features
    from modules.rbac.services import get_user_permissions, get_user_roles, is_subadmin_user

    is_platform_admin = getattr(user, 'is_platform_admin', False)

    # The active tenant for a profile refresh is the per-request resolved tenant
    # (admin-web sends X-Tenant-Subdomain / X-Tenant-ID). For a platform admin
    # in god-login this differs from their home tenant_id.
    active_tenant_id = get_tenant_id() or user.tenant_id

    roles = get_user_roles(user.id)

    if is_platform_admin:
        # Keep god-mode in the UI across a profile refresh.
        permissions = ["system.manage"]
        enabled_features = []
        is_subadmin = False
    else:
        permissions = get_user_permissions(user.id)
        enabled_features = get_tenant_enabled_features(active_tenant_id) if active_tenant_id else []
        is_subadmin = is_subadmin_user(user.id, active_tenant_id) if active_tenant_id else False

    tenant_name = None
    is_setup_complete = False
    if active_tenant_id:
        t = Tenant.query.get(active_tenant_id)
        if t:
            tenant_name = t.name
            is_setup_complete = bool(t.is_setup_complete)

    # Branch (school-unit) scope. None = unrestricted (all branches), incl.
    # platform admins. g.current_user / g.tenant_id are already set here.
    from core.branch_scope import get_allowed_unit_ids
    _allowed_units = get_allowed_unit_ids()
    allowed_unit_ids = sorted(_allowed_units) if _allowed_units is not None else None

    return success_response(
        data={
            'user': {
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'email_verified': user.email_verified,
                'profile_picture_url': profile_picture_public_url(user.profile_picture_url),
                'default_unit_id': user.default_unit_id,
                'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None,
                'created_at': user.created_at.isoformat(),
            },
            'tenant_name': tenant_name,
            'roles': roles,
            'permissions': permissions,
            'enabled_features': enabled_features,
            'is_platform_admin': is_platform_admin,
            'is_subadmin': is_subadmin,
            'is_setup_complete': is_setup_complete,
            'force_password_reset': bool(user.force_password_reset),
            'allowed_unit_ids': allowed_unit_ids,
        },
        status_code=200
    )


@auth_bp.route('/profile', methods=['PUT'])
@auth_required
def update_profile():
    """Update current user profile. Tenant from X-Tenant-ID header or default."""
    err = resolve_tenant_for_auth(request.get_json(silent=True) or {})
    if err:
        return err[1], err[0]

    user = g.current_user
    data = request.get_json() or {}

    # Update allowed fields
    if 'name' in data:
        user.name = data['name']
        # A person's name belongs to the person, not to one of their logins
        # (ADR-001) — it is what the student and teacher records show.
        from modules.people.service import revise_identity

        revise_identity(user.person, {"full_name": data['name']})
    
    if 'profile_picture_url' in data:
        user.profile_picture_url = normalize_stored_file_value_for_db(data['profile_picture_url'])

    user.save()

    return success_response(
        data={
            'user': {
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'profile_picture_url': profile_picture_public_url(user.profile_picture_url),
            }
        },
        message='Profile updated successfully',
        status_code=200
    )


def _upload_profile_picture_handler():
    """Shared implementation: multipart file field 'file' or 'picture'."""
    err = resolve_tenant_for_auth({})
    if err:
        return err[1], err[0]

    tenant_id = get_tenant_id()
    if not tenant_id:
        return error_response('ValidationError', 'Tenant context required', 400)

    file = request.files.get('file') or request.files.get('picture')
    if not file or not getattr(file, 'filename', None):
        return error_response('ValidationError', 'Image file is required', 400)

    stream = getattr(file, 'stream', file)
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    if size > PROFILE_PICTURE_MAX_BYTES:
        return error_response(
            'FileTooLarge',
            'Image must be 5 MB or smaller',
            400,
        )
    if size == 0:
        return error_response('ValidationError', 'File is empty', 400)

    raw_ct = getattr(file, 'content_type', '') or ''
    content_type = raw_ct.split(';')[0].strip().lower()
    if content_type not in PROFILE_PICTURE_ALLOWED_MIME:
        return error_response(
            'UnsupportedFileType',
            'Allowed image types: JPEG, PNG, WebP',
            400,
        )

    ext = '.jpg'
    if 'png' in content_type:
        ext = '.png'
    elif 'webp' in content_type:
        ext = '.webp'

    user = g.current_user
    safe_name = f'avatar{ext}'

    try:
        folder = f"{TENANTS}/{tenant_id}/{PROFILE_PICTURES}/users/{user.id}"
        _, object_key = upload_file(
            stream,
            folder=folder,
            original_filename=safe_name,
            content_type=content_type,
        )
    except Exception as e:
        logger.exception('Profile picture upload failed: %s', e)
        return error_response(
            'StorageError',
            'Could not upload image. Please try again.',
            503,
        )

    if len(object_key) > 255:
        logger.error('Profile picture object key exceeds column length: %s', len(object_key))
        return error_response(
            'StorageError',
            'Upload failed due to server configuration.',
            503,
        )

    user.profile_picture_url = object_key
    user.save()

    return success_response(
        data={'profile_picture_url': profile_picture_public_url(user.profile_picture_url)},
        message='Profile photo updated',
        status_code=200,
    )


@auth_bp.route('/profile/picture', methods=['POST'])
@auth_required
def upload_profile_picture():
    """Upload profile photo (legacy path). Prefer POST /upload-profile-picture."""
    return _upload_profile_picture_handler()


@auth_bp.route('/upload-profile-picture', methods=['POST'])
@auth_required
def upload_profile_picture_short():
    """Upload profile photo. multipart: file or picture."""
    return _upload_profile_picture_handler()


# ==================== SELF-SERVE PASSWORD CHANGE ====================

@auth_bp.route('/password/change', methods=['POST'])
@auth_required
def change_password():
    """Change the authenticated user's password.

    Body:
        - current_password (required)
        - new_password (required)
        - revoke_other_sessions (optional, bool — default False)

    Responses:
        200: {data: {revoked_sessions: int}}
        400: missing fields
        401: current password is wrong
        422: new password is weak or identical to current
    """
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password")
    new_password = data.get("new_password")
    revoke = bool(data.get("revoke_other_sessions", False))

    if not current_password or not new_password:
        return error_response(
            error="ValidationError",
            message="current_password and new_password are required",
            status_code=400,
        )

    try:
        result = services.change_password(
            user_id=g.current_user.id,
            current_password=current_password,
            new_password=new_password,
            revoke_other_sessions=revoke,
        )
    except services.PasswordChangeError as e:
        status = 401 if e.code == "current_password_invalid" else 422
        return error_response(
            error=e.code,
            message=str(e) or e.code,
            status_code=status,
        )

    return success_response(data=result)


@auth_bp.route('/refresh', methods=['POST'])
@limiter.limit("30 per minute")
def refresh_tokens():
    """Trade a refresh token for a fresh pair.

    An explicit endpoint, because the implicit one — send an expired access
    token plus `X-Refresh-Token` to any route and read the replacement off a
    response header — is invisible in the API surface and gave a client no way
    to renew without first making a request that fails. The implicit path
    still works; this is the one a client should use.

    **The token sent here is spent.** Every refresh rotates: the response
    carries a new refresh token and the old one is dead the moment this
    returns. A client that keeps the old one will, on its next attempt, be
    replaying a consumed token — which is indistinguishable from a thief doing
    the same, so the session ends.

    Every refusal is one answer. Unknown, expired, replayed, revoked session,
    suspended account, suspended school: all `401 InvalidRefreshToken`. The
    real reason is recorded.
    """
    from .tokens import RefreshOutcome, rotate

    data = request.get_json(silent=True) or {}
    token = (
        request.headers.get('X-Refresh-Token')
        or data.get('refresh_token')
        or ''
    ).strip()

    if not token:
        return error_response(
            error='ValidationError',
            message='A refresh token is required.',
            status_code=400,
        )

    outcome, session, replacement = rotate(token)
    if outcome != RefreshOutcome.OK or session is None:
        db.session.commit()  # a reuse detection revokes; that must persist
        return error_response(
            error='InvalidRefreshToken',
            message='Please sign in again.',
            status_code=401,
        )

    user = User.query.filter_by(id=session.user_id).first()
    if user is None:
        db.session.rollback()
        return error_response(
            error='InvalidRefreshToken',
            message='Please sign in again.',
            status_code=401,
        )

    access_token = services.generate_access_token(
        user,
        tenant_id=session.tenant_id,
        method=session.login_method,
        session_id=session.id,
    )
    db.session.commit()

    return success_response(
        data={
            'access_token': access_token,
            'refresh_token': replacement,
            'expires_in': services.JWT_ACCESS_MINUTES * 60,
        },
        message='Token refreshed',
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Account access — suspend and reactivate
#
# Access, never the record. A suspended pupil is still enrolled, still on the
# register and still in last term's results; they simply cannot sign in.
# ---------------------------------------------------------------------------

@auth_bp.route('/accounts/<account_id>/suspend', methods=['POST'])
@tenant_required
@auth_required
@require_permission('user.manage')
def suspend_account_access(account_id):
    """Stop this account signing in, immediately.

    Sessions are revoked, refresh tokens retired, and the access token already
    in their browser stops working on its next request. Nothing about their
    record changes.
    """
    from .account_status import AccountStatusError, describe_access, suspend_account

    account = _account_in_my_school(account_id)
    if account is None:
        return not_found_response('Account')

    if account.id == g.current_user.id:
        # Suspending yourself locks you out of the screen you would need to
        # undo it.
        return error_response(
            error='ValidationError',
            message='You cannot suspend your own access.',
            status_code=400,
        )

    data = request.get_json(silent=True) or {}
    try:
        result = suspend_account(
            account,
            actor_user_id=g.current_user.id,
            reason=(data.get('reason') or '').strip() or None,
        )
        db.session.commit()
    except AccountStatusError as exc:
        db.session.rollback()
        return error_response('ValidationError', str(exc), 400)

    return success_response(data={**result, 'access': describe_access(account)})


@auth_bp.route('/accounts/<account_id>/reactivate', methods=['POST'])
@tenant_required
@auth_required
@require_permission('user.manage')
def reactivate_account_access(account_id):
    """Let this account sign in again.

    **No session is restored.** The tokens from before the suspension stay
    dead and the person signs in fresh — so "reactivated" means the same thing
    however long the suspension lasted. Their password and PIN still work.
    """
    from .account_status import AccountStatusError, describe_access, reactivate_account

    account = _account_in_my_school(account_id)
    if account is None:
        return not_found_response('Account')

    try:
        result = reactivate_account(account, actor_user_id=g.current_user.id)
        db.session.commit()
    except AccountStatusError as exc:
        db.session.rollback()
        return error_response('ValidationError', str(exc), 400)

    return success_response(data={**result, 'access': describe_access(account)})


@auth_bp.route('/accounts/<account_id>/access', methods=['GET'])
@tenant_required
@auth_required
@require_permission('user.manage')
def read_account_access(account_id):
    """What an operator needs before deciding. Carries no secret."""
    from .account_status import describe_access

    account = _account_in_my_school(account_id)
    if account is None:
        return not_found_response('Account')
    return success_response(data=describe_access(account))


# ---------------------------------------------------------------------------
# Mobile OTP
#
# Only the *request* half is a new endpoint. Verification is an ordinary sign-in
# through `POST /api/auth/login` with `method=mobile_otp`, so it runs every gate
# the pipeline already owns — maintenance, policy, lockout, account status,
# disambiguation, events, finalization — rather than a second copy of them.
# ---------------------------------------------------------------------------

@auth_bp.route('/otp/request', methods=['POST'])
@limiter.limit("10 per minute")
def request_mobile_otp():
    """Send a sign-in code to a mobile number.

    **Answers the same way whatever happens.** A number that belongs to
    nobody, a school that has not enabled the method, a suspended account, a
    number shared by two people and a code that was genuinely sent all produce
    one response. Anything else would answer, for free, the question an
    attacker is asking: *is this number a NexSchool customer?*

    The precise reason is recorded internally — see `otp.py` — so an operator
    investigating can tell those cases apart. The caller cannot.

    Rate limits are enforced inside the service, across the number, the school
    and the address, because a per-IP limit alone is no defence against
    somebody with a list of addresses ringing one victim's phone all night.
    """
    from .otp import request_otp

    data = request.get_json(silent=True) or {}
    mobile = (data.get('mobile') or data.get('identifier') or '').strip()

    # The school must be **named**, not merely resolvable. `resolve_tenant_for_auth`
    # falls back to the tenant with subdomain "default" when nothing names one
    # — a documented behaviour the login path deliberately keeps — and here
    # that fallback would be a hole: a request with no school would send a code
    # to whoever happens to hold that number at the default school. So the
    # naming is checked first, and an unnamed school is an error.
    named = bool(
        data.get('tenant_id')
        or data.get('tenantId')
        or (data.get('subdomain') or '').strip()
        or request.headers.get('X-Tenant-ID')
        or request.headers.get('X-Tenant-Subdomain')
    )
    if not named:
        return error_response(
            error='TenantRequired',
            message='Tenant is required for this sign-in method.',
            status_code=400,
        )

    failure = resolve_tenant_for_auth(data)
    if failure:
        return failure[1], failure[0]

    tenant_id = get_tenant_id()
    if not tenant_id:
        return error_response(
            error='TenantRequired',
            message='Tenant is required for this sign-in method.',
            status_code=400,
        )

    if not mobile:
        return error_response(
            error='ValidationError',
            message='A mobile number is required.',
            status_code=400,
        )

    result = request_otp(
        tenant_id=tenant_id,
        mobile=mobile,
        ip_address=request.remote_addr,
        client_surface=(request.headers.get('X-Client-Surface') or '').strip()[:30] or None,
    )

    # One response for every outcome — with one exception. Being throttled is
    # told plainly, because a client that does not know it is rate limited
    # simply retries, and because the caller learns nothing from it that they
    # did not already know: they are the one who sent the requests.
    if not result.accepted and result.reason == 'throttled':
        return error_response(
            error='TooManyRequests',
            message='Too many codes have been requested. Please wait and try again.',
            status_code=429,
            details=(
                {'retry_after_seconds': result.retry_after_seconds}
                if result.retry_after_seconds
                else None
            ),
        )

    payload = {'sent': True}
    if result.accepted and result.challenge is not None:
        # The challenge id and its expiry — nothing that identifies a person,
        # and nothing that says whether an account exists. A refused request
        # returns no id at all, which a client treats as "wait for the code".
        payload.update(result.challenge.to_dict())
        payload.pop('attempts_remaining', None)

    return success_response(
        data=payload,
        message='If that number can sign in here, a code is on its way.',
        status_code=200,
    )


@auth_bp.route('/pin/change', methods=['POST'])
@auth_required
@limiter.limit("5 per minute")
def change_pin():
    """Replace the PIN on the signed-in account.

    The holder's own operation, so it needs the current PIN as well as the new
    one — being signed in is not by itself permission to change a second
    credential, and somebody who walked away from an unlocked phone should not
    lose their PIN to whoever picked it up.

    Clears `must_change` on the PIN and nothing else. A password that must also
    be changed stays that way: they are separate credentials with separate
    flags, and discharging one requirement is not discharging the other.
    """
    from werkzeug.security import check_password_hash

    from .pin import InvalidPin, WeakPin
    from .provisioning import issue_pin_credential, live_pin_credential

    data = request.get_json(silent=True) or {}
    current = data.get('current_pin') or ''
    replacement = data.get('new_pin') or ''

    credential = live_pin_credential(g.current_user)
    if credential is None:
        return error_response(
            error='NoPinCredential',
            message='This account has no PIN to change.',
            status_code=404,
        )

    if not current or not check_password_hash(credential.secret_hash, current):
        return error_response(
            error='InvalidCredentials',
            message='That PIN is not correct.',
            status_code=401,
        )

    try:
        issue_pin_credential(
            g.current_user,
            replacement,
            issued_by_user_id=g.current_user.id,
            # Chosen by the holder, not issued by the school — which is what
            # `is_provisional` records, and it is now false.
            is_provisional=False,
        )
        db.session.commit()
    except (InvalidPin, WeakPin) as exc:
        db.session.rollback()
        return error_response(error='WeakPin', message=str(exc), status_code=422)
    except Exception as exc:
        db.session.rollback()
        logger.exception('PIN change failed')
        return error_response('InternalError', 'Could not change the PIN.', 500)

    return success_response(message='PIN changed')


# ---------------------------------------------------------------------------
# Parent logins
#
# Provisioning is a school operation and needs `user.manage`; reading one's own
# children needs only a session, because the answer is derived from who is
# signed in rather than from anything they send.
# ---------------------------------------------------------------------------

@auth_bp.route('/parents/<person_id>/login', methods=['POST'])
@tenant_required
@auth_required
@limiter.limit("30 per minute", key_func=actor_rate_key)
@require_permission('user.manage')
def provision_parent(person_id):
    """Give a parent their own way to sign in.

    Explicit and audited. Importing a spreadsheet of fathers creates fathers,
    not logins — a school that has chosen separate parent logins still asks
    for each one deliberately.

    Reuses the account this person already has if there is one (a teacher who
    becomes a parent keeps one account), and issues a password only when there
    was none. The plaintext comes back in this response and exists nowhere
    else.
    """
    from modules.people.models import Person

    from .parents import ParentProvisioningError, provision_parent_login

    person = Person.query.filter_by(
        id=person_id, tenant_id=get_tenant_id()
    ).filter(Person.deleted_at.is_(None)).first()
    if person is None:
        return not_found_response('Person')

    data = request.get_json(silent=True) or {}

    try:
        result = provision_parent_login(
            person,
            email=(data.get('email') or '').strip(),
            actor_user_id=g.current_user.id,
        )
        db.session.commit()
    except ParentProvisioningError as exc:
        db.session.rollback()
        return error_response(
            error='ParentLoginNotProvisioned', message=str(exc), status_code=422
        )

    payload = {
        'account_id': result.account.id,
        'email': result.account.email,
        'created_account': result.created_account,
        'reused_existing_account': result.reused_existing_account,
    }
    if result.password:
        # Once, and never again — the same contract every issued credential
        # in this codebase follows.
        payload['password'] = result.password

    return success_response(data=payload)


@auth_bp.route('/parents/me/children', methods=['GET'])
@tenant_required
@auth_required
def my_children():
    """The students the signed-in account is a parent of.

    Derived from the family relationship, not from anything the caller sends,
    so there is no id here for somebody to substitute. A person who is not a
    parent gets an empty list rather than an error — that is a true answer,
    and distinguishing it would say who is a parent at this school.
    """
    from .parents import children_of_account

    children = children_of_account(g.current_user)
    return success_response(
        data={
            'children': [
                {
                    'id': student.id,
                    'admission_number': student.admission_number,
                    'name': student.display_name,
                    'class_id': student.class_id,
                }
                for student in children
            ]
        }
    )


# ---------------------------------------------------------------------------
# Session administration
#
# Two audiences, one model. A person managing their own sessions needs no
# permission beyond being signed in; an operator managing somebody else's
# needs `user.manage` and can only reach accounts in their own school.
# ---------------------------------------------------------------------------

@auth_bp.route('/sessions', methods=['GET'])
@auth_required
def list_my_sessions():
    """Where am I signed in?

    Metadata only — a session's refresh token is the credential that session
    is made of, and a listing carrying it would hand every session to whoever
    could read one.
    """
    from modules.auth.session_admin import list_sessions

    return success_response(data={'sessions': list_sessions(g.current_user)})


@auth_bp.route('/sessions/<session_id>', methods=['DELETE'])
@auth_required
def revoke_my_session(session_id):
    """Sign out of one place.

    The session is matched by id *and* account, so somebody else's session id
    is simply not found rather than revoked.
    """
    from modules.auth.session_admin import revoke_session

    if not revoke_session(
        g.current_user, session_id, actor_user_id=g.current_user.id
    ):
        return not_found_response('Session')
    db.session.commit()
    return success_response(message='Session revoked')


@auth_bp.route('/sessions', methods=['DELETE'])
@auth_required
def revoke_my_other_sessions():
    """Sign out everywhere else.

    The front door for signing out everywhere. It is the *only* way to do it:
    the unauthenticated `logout` route ends one session, deliberately, so that
    nobody can sign somebody else out of every device they own.

    The caller's own session is kept by default, so asking to be signed out
    elsewhere does not sign them out of the screen they asked from. Which one
    is theirs comes from their access token's `sid` claim — see
    `current_session_id`.
    """
    from modules.auth.session_admin import current_session_id, revoke_all_sessions

    keep_current = str(
        (request.args.get('keep_current') or 'true')
    ).lower() not in ('false', '0', 'no')

    current = current_session_id()
    revoked = revoke_all_sessions(
        g.current_user,
        actor_user_id=g.current_user.id,
        keep_session_id=current if (current and keep_current) else None,
    )
    db.session.commit()
    return success_response(data={'revoked': revoked})


@auth_bp.route('/accounts/<account_id>/sessions', methods=['GET'])
@tenant_required
@auth_required
@require_permission('user.manage')
def list_account_sessions(account_id):
    """Where is this account signed in? For an operator, about somebody else."""
    from modules.auth.session_admin import list_sessions

    account = _account_in_my_school(account_id)
    if account is None:
        return not_found_response('Account')

    return success_response(data={'sessions': list_sessions(account)})


@auth_bp.route('/accounts/<account_id>/sessions/<session_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_permission('user.manage')
def revoke_account_session(account_id, session_id):
    """End one of somebody else's sessions."""
    from modules.auth.session_admin import revoke_session

    account = _account_in_my_school(account_id)
    if account is None:
        return not_found_response('Account')

    if not revoke_session(account, session_id, actor_user_id=g.current_user.id):
        return not_found_response('Session')
    db.session.commit()
    return success_response(message='Session revoked')


@auth_bp.route('/accounts/<account_id>/sessions', methods=['DELETE'])
@tenant_required
@auth_required
@require_permission('user.manage')
def revoke_account_sessions(account_id):
    """Sign this account out everywhere."""
    from modules.auth.session_admin import revoke_all_sessions

    account = _account_in_my_school(account_id)
    if account is None:
        return not_found_response('Account')

    revoked = revoke_all_sessions(account, actor_user_id=g.current_user.id)
    db.session.commit()
    return success_response(data={'revoked': revoked})


def _account_in_my_school(account_id):
    """The account, if it belongs to the school making the request.

    A platform administrator's account is deliberately not reachable this way.
    They are not a member of the school they are operating in, and a school
    administrator ending the operator's session is not a capability any school
    has been given.
    """
    account = User.query.filter_by(
        id=account_id, tenant_id=get_tenant_id()
    ).filter(User.deleted_at.is_(None)).first()
    if account is None or account.is_platform_admin:
        return None
    return account
