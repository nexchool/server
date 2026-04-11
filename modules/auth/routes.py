"""
Authentication Routes

API endpoints for user authentication, registration, and account management.

Routes:
- POST /register - Register new user
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
from .services import (
    authenticate_user,
    find_users_by_email_password,
    generate_access_token,
    create_session,
    logout_user as logout_user_service
)
from core.decorators import auth_required, tenant_required  # tenant_required still used for routes that run after middleware
from core.database import db
from core.extensions import limiter
from shared.helpers import success_response, error_response

logger = logging.getLogger(__name__)

PROFILE_PICTURE_MAX_BYTES = 5 * 1024 * 1024
PROFILE_PICTURE_ALLOWED_MIME = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/webp"}
)


# ==================== REGISTRATION ====================

@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Register a new user.
    
    Request Body:
        - email: User email (required)
        - password: User password (required)
        - name: User name (optional)
        
    Returns:
        201: User created successfully
        400: Validation error or user already exists
    """
    err = resolve_tenant_for_auth(request.get_json(silent=True) or {})
    if err:
        return err[1], err[0]

    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    name = data.get('name')

    # Validation
    if not email or not password:
        return error_response(
            error='ValidationError',
            message='Email and password are required',
            status_code=400
        )

    tenant_id = get_tenant_id()
    if not tenant_id:
        return error_response(
            error='TenantRequired',
            message='Tenant context is required',
            status_code=400
        )

    # Check if user already exists (tenant-scoped)
    if User.get_user_by_email(email, tenant_id=tenant_id):
        return error_response(
            error='UserExists',
            message='User already exists',
            status_code=400
        )

    # Create user (tenant-scoped)
    user = User()
    user.tenant_id = tenant_id
    user.email = email
    user.set_password(password)
    if name:
        user.name = name

    # Generate email verification token
    email_verification_token = user.generate_email_verification_token()
    user.save()

    # Auto-assign default role (handled by RBAC module).
    # seed_roles_for_tenant ensures the role exists and has all its permissions
    # before we try to assign it — guards against tenants seeded before global
    # permissions were created.
    from modules.rbac.services import assign_role_to_user_by_email
    from modules.rbac.role_seeder import seed_roles_for_tenant
    default_role = os.getenv("DEFAULT_USER_ROLE", "Student")
    seed_roles_for_tenant(tenant_id)
    assign_result = assign_role_to_user_by_email(email, default_role, tenant_id=tenant_id)

    if not assign_result['success']:
        # Log warning but don't fail registration
        print(f"Warning: Could not assign default role to {email}: {assign_result.get('error')}")

    # Send verification email via notification dispatcher
    from config.settings import get_email_verification_url
    from modules.notifications.services import notification_dispatcher
    from modules.notifications.enums import NotificationChannel

    verify_url = get_email_verification_url(email_verification_token, email)
    notification_dispatcher.dispatch(
        user_id=user.id,
        tenant_id=tenant_id,
        notification_type="EMAIL_VERIFICATION",
        channels=[NotificationChannel.EMAIL.value],
        title="Verify your email",
        body=None,
        extra_data={"verify_url": verify_url, "email": email},
    )

    return success_response(
        data={'email': email},
        message=f'User {email} registered successfully! Please verify your email.',
        status_code=201
    )


# ==================== LOGIN ====================

# Lockout duration when max_login_attempts exceeded (tenant logins only)
LOGIN_LOCKOUT_MINUTES = 15


@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    """
    Login with email and password.

    Single app for all schools: if the request has no tenant (no tenant_id/subdomain in body,
    no X-Tenant-ID, no subdomain in host), we search across all tenants for a user with that
    email and password. If exactly one match -> login success. If multiple matches -> return
    list of schools so the app can show "Which school?" and send tenant_id on second attempt.

    If tenant is provided (body, header, or host), we authenticate only in that tenant (current behavior).
    """
    from datetime import datetime, timedelta

    data = request.get_json() or {}
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
            if user_by_email.login_locked_until and user_by_email.login_locked_until > datetime.utcnow():
                return error_response(
                    error='TooManyAttempts',
                    message='Account temporarily locked due to too many failed attempts. Try again later.',
                    status_code=429
                )
        user = authenticate_user(email, password, tenant_id=tenant_id)
        if not user:
            if user_by_email and not getattr(user_by_email, 'is_platform_admin', False):
                from modules.platform.services import get_platform_setting
                max_attempts_str = get_platform_setting('max_login_attempts')
                max_attempts = int(max_attempts_str) if max_attempts_str and str(max_attempts_str).isdigit() else 5
                user_by_email.failed_login_count = (user_by_email.failed_login_count or 0) + 1
                if user_by_email.failed_login_count >= max_attempts:
                    user_by_email.login_locked_until = datetime.utcnow() + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
                    user_by_email.failed_login_count = 0
                user_by_email.save()
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
            if user.login_locked_until and user.login_locked_until > datetime.utcnow():
                return error_response(
                    error='TooManyAttempts',
                    message='Account temporarily locked due to too many failed attempts. Try again later.',
                    status_code=429
                )

    # Common success path (user and tenant are set)
    if not user.email_verified:
        return error_response(
            error='EmailNotVerified',
            message='Please verify your email before logging in',
            status_code=401
        )

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

    user.last_login_at = datetime.utcnow()
    user.save()

    access_minutes = None
    if not getattr(user, 'is_platform_admin', False):
        try:
            from modules.platform.services import get_platform_setting
            mins = get_platform_setting('session_timeout_minutes')
            if mins and str(mins).isdigit():
                access_minutes = max(5, min(10080, int(mins)))
        except Exception:
            pass

    access_token = generate_access_token(user, access_minutes=access_minutes)
    session = create_session(user, request)

    from core.plan_features import get_tenant_enabled_features
    enabled_features = get_tenant_enabled_features(tenant.id) if tenant else []

    response, status_code = success_response(
        data={
            'access_token': access_token,
            'refresh_token': session.refresh_token,
            'tenant_id': str(user.tenant_id),
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


# ==================== LOGOUT ====================

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    Logout user by revoking the session.
    Tenant from X-Tenant-ID header or default.
    
    Headers:
        - X-Refresh-Token: Refresh token (optional; required for mobile/client)
    Cookies:
        - auth-token: Access token (optional; used by panel when no header)
        
    Returns:
        200: Logout successful
        400: Missing both refresh token and auth-token cookie
    """
    err = resolve_tenant_for_auth()
    if err:
        return err[1], err[0]

    refresh_token = request.headers.get("X-Refresh-Token")
    access_token_cookie = request.cookies.get("auth-token")

    if refresh_token:
        logout_user_service(refresh_token)
    elif access_token_cookie:
        from modules.auth.services import validate_jwt_token
        payload = validate_jwt_token(access_token_cookie, token_type="access")
        if payload:
            from modules.auth.services import revoke_all_user_sessions
            revoke_all_user_sessions(str(payload["sub"]))
    else:
        return error_response(
            error='ValidationError',
            message='Refresh token or auth cookie is required',
            status_code=400
        )

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

    # Auto-login: create session
    access_token = generate_access_token(user)
    session = create_session(user, request)

    # Redirect to app with tokens
    return redirect(get_app_verification_success_url(
        access_token=access_token,
        refresh_token=session.refresh_token,
        user_id=user.id,
        email=user.email
    ))


# ==================== PASSWORD RESET ====================

@auth_bp.route('/password/forgot', methods=['POST'])
def forgot_password():
    """
    Request password reset email.
    Tenant from body (subdomain/tenant_id), X-Tenant-ID header, or default.
    """
    err = resolve_tenant_for_auth(request.get_json(silent=True) or {})
    if err:
        return err[1], err[0]

    from config.settings import get_reset_password_url
    from modules.notifications.services import notification_dispatcher
    from modules.notifications.enums import NotificationChannel

    data = request.get_json()
    email = data.get('email')

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

        # Send reset email via notification dispatcher
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

    from core.plan_features import get_tenant_enabled_features
    enabled_features = get_tenant_enabled_features(user.tenant_id)
    return success_response(data={'enabled_features': enabled_features}, status_code=200)


# ==================== PROFILE ====================

@auth_bp.route('/profile', methods=['GET'])
@auth_required
def get_profile():
    """Get current user profile. Tenant from X-Tenant-ID header or default."""
    err = resolve_tenant_for_auth()
    if err:
        return err[1], err[0]

    user = g.current_user

    from core.plan_features import get_tenant_enabled_features
    from modules.rbac.services import get_user_permissions, get_user_roles
    permissions = get_user_permissions(user.id)
    roles = get_user_roles(user.id)
    enabled_features = get_tenant_enabled_features(user.tenant_id) if user.tenant_id else []

    return success_response(
        data={
            'user': {
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'email_verified': user.email_verified,
                'profile_picture_url': profile_picture_public_url(user.profile_picture_url),
                'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None,
                'created_at': user.created_at.isoformat(),
            },
            'roles': roles,
            'permissions': permissions,
            'enabled_features': enabled_features,
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
