"""
Authentication Services

Business logic for authentication, JWT token management, and sessions.
"""

import jwt
from datetime import timedelta
import os
import uuid
from typing import Optional, Tuple, Dict, List

from flask import Request

from .models import User, Session
from core.database import db
from core.models import Tenant
from core.models import TENANT_STATUS_ACTIVE
from core.school_time import utc_now


# JWT Configuration
#: The development fallback, named so that `ProductionConfig` can refuse to
#: start on it. It is in a public repository, so a deployment signing tokens
#: with it can have its tokens forged by anybody who has read this line.
INSECURE_JWT_SECRET = "your_default_secret_key"

JWT_SECRET = os.getenv("JWT_SECRET_KEY", INSECURE_JWT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_ACCESS_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", 15))
JWT_REFRESH_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES_DAYS", 7))


# ==================== JWT Token Generation ====================

def generate_access_token(
    user: User,
    access_minutes: Optional[int] = None,
    *,
    tenant_id: Optional[str] = None,
    method: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """
    Generate a short-lived access token for API authentication.

    Args:
        user: User object
        access_minutes: Optional override for token expiry (e.g. from platform settings).
                        If None, uses JWT_ACCESS_MINUTES from env.
    Returns:
        JWT access token string
    """
    minutes = access_minutes if access_minutes is not None else JWT_ACCESS_MINUTES
    payload = {
        "sub": str(user.id),
        # Unique per token. Not used for lookup today; it is what makes a
        # single token nameable in an audit record, and what a future
        # per-token denylist would key on.
        "jti": str(uuid.uuid4()),
        # Kept through the deprecation window, and tolerant of an account that
        # has none — which identifier-only accounts will be. Its removal is a
        # later phase, after a full mobile release cycle.
        "email": user.email,
        "is_platform_admin": bool(getattr(user, "is_platform_admin", False)),
        "type": "access",
        "iat": utc_now(),
        "exp": utc_now() + timedelta(minutes=minutes),
    }

    # The school this token acts in, and how its holder proved who they are.
    # `amr` is the standard name for the latter. Both are read from the
    # pipeline's request context rather than passed down through
    # `_finalize_login`, which this phase must not modify.
    resolved_tenant_id, method = _token_context(user, tenant_id, method)
    if resolved_tenant_id:
        payload["tid"] = str(resolved_tenant_id)
    if method:
        payload["amr"] = method

    # Which session this token belongs to. Validation checks that session is
    # still live, which is what makes revoking one felt immediately rather
    # than at the token's own expiry.
    session_id = session_id or _session_from_context()
    if session_id:
        payload["sid"] = str(session_id)

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _session_from_context() -> Optional[str]:
    """The session this request is acting under, when there is one.

    Read from the request context rather than threaded through every caller,
    for the same reason `amr` and `tid` are: `_finalize_login` must not be
    modified, and it is what mints the token at sign-in.
    """
    from flask import g, has_request_context

    if not has_request_context():
        return None
    return getattr(g, "auth_session_id", None)


def _token_context(user, tenant_id, method):
    """The tenant and method to stamp on a token, from the caller or context."""
    from flask import g, has_request_context

    from .pipeline import current_context

    context = current_context()
    method = method or context.get("login_method")

    if tenant_id is None:
        # The *entered* tenant scopes the request, and for a platform admin
        # signing into another school it is not their own.
        if has_request_context():
            tenant_id = getattr(g, "tenant_id", None)
        tenant_id = tenant_id or getattr(user, "tenant_id", None)

    return tenant_id, method


def generate_refresh_token(user: User) -> str:
    """
    Generate a long-lived refresh token for obtaining new access tokens.
    
    Args:
        user: User object
        
    Returns:
        JWT refresh token string
        
    Token Payload:
        - sub: User ID
        - type: 'refresh'
        - iat: Issued at timestamp
        - exp: Expiration timestamp
    """
    payload = {
        "sub": str(user.id),
        "type": "refresh",
        "iat": utc_now(),
        "exp": utc_now() + timedelta(days=JWT_REFRESH_DAYS),
    }

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


# ==================== JWT Token Validation ====================

def validate_jwt_token(token: str, token_type: str = "access") -> Optional[Dict]:
    """
    Validate and decode a JWT token.
    
    Args:
        token: JWT token string
        token_type: Expected token type ('access' or 'refresh')
        
    Returns:
        Decoded token payload if valid, None otherwise
        
    Validation Rules:
        - Token must be valid JWT
        - Token must not be expired
        - Token type must match expected type
    """
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM]
        )

        # Verify token type
        if payload.get("type") != token_type:
            return None

        return payload

    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ==================== Session Management ====================

def create_session(
    user: User,
    request: Request = None,
    *,
    login_method: Optional[str] = None,
    client_surface: Optional[str] = None,
    authenticated_identifier_id: Optional[str] = None,
) -> Session:
    """
    Create a new session for a user.
    
    Args:
        user: User object
        request: Flask request object (for device metadata)
        
    Returns:
        Created Session object with refresh token
    """
    
    # What opened this session. Supplied explicitly by a caller that knows, or
    # read from the pipeline's request context — which is how it reaches here
    # without `_finalize_login`, out of scope for this phase, having to pass
    # it. A caller that is not a sign-in (email-verification auto-login) knows
    # none of it and leaves the column defaults alone, exactly as before.
    from .pipeline import current_context

    context = current_context()
    login_method = login_method or context.get("login_method")
    client_surface = client_surface or context.get("client_surface")
    authenticated_identifier_id = authenticated_identifier_id or context.get(
        "authenticated_identifier_id"
    )

    # Create session (tenant-scoped). The refresh token is no longer a column
    # on this row: it lives in `refresh_tokens`, hashed, unique and rotating,
    # and is minted below once the session has an id to belong to.
    # How long this session may live is a property of where it was opened, not
    # a constant: a phone in a pocket and a platform operator's console are not
    # the same risk and no longer get the same window. See `session_policy`.
    from .session_policy import initial_expiry

    session = Session(
        user_id=user.id,
        tenant_id=user.tenant_id,
        refresh_token=None,
        refresh_token_expires_at=initial_expiry(client_surface),
    )
    if login_method:
        session.login_method = login_method
    if client_surface:
        session.client_surface = client_surface
    if authenticated_identifier_id:
        session.authenticated_identifier_id = authenticated_identifier_id

    # Add device metadata if request provided
    if request:
        session.ip_address = request.remote_addr
        session.user_agent = request.headers.get("User-Agent", "")
        session.device_info = request.headers.get("User-Agent", "")
    
    # One transaction, both rows — and this is the whole of it.
    #
    # `session.save()` used to stand here, and it commits. The refresh token was
    # then minted below with `add` + `flush` and nothing ever committed again on
    # the login path, so the token's verifier row was discarded when the session
    # was removed at teardown. The client walked away holding a refresh token
    # the database had never heard of: every session died with its first access
    # token, fifteen minutes in, on every surface at once.
    #
    # The flush is what gives the session its id, which the token has to name.
    # The commit that follows carries both or neither, which is the only
    # correct relationship between a session and the credential that renews it.
    db.session.add(session)
    db.session.flush()

    # Carried back on the object rather than stored — `issued_refresh_token` is
    # read once by the caller that builds the login response, and the plaintext
    # is never persisted anywhere.
    from .tokens import issue_refresh_token

    session.issued_refresh_token = issue_refresh_token(session)
    db.session.commit()

    # So that an access token minted later in this same request can name the
    # session it belongs to.
    from flask import g, has_request_context

    if has_request_context():
        g.auth_session_id = session.id

    return session


def revoke_all_user_sessions(user_id: str) -> int:
    """
    Revoke all sessions for a user (logout from all devices).
    
    Args:
        user_id: User ID
        
    Returns:
        Number of sessions revoked
    """
    sessions = Session.query.filter_by(user_id=user_id, revoked=False).all()
    count = 0
    
    for session in sessions:
        session.revoke()
        count += 1
    
    return count


# ==================== Authentication ====================

def authenticate_user(
    email: str,
    password: str,
    tenant_id: Optional[str] = None,
) -> Optional[User]:
    """
    Authenticate a user by email and password within a tenant.

    Args:
        email: User email
        password: Plain text password
        tenant_id: Tenant ID (required in multi-tenant; from g.tenant_id)

    Returns:
        User object if authentication successful, None otherwise
    """
    user = User.get_user_by_email(email, tenant_id=tenant_id)

    if not user:
        return None

    if not user.check_password(password):
        return None

    return user


def authenticate_platform_admin(email: str, password: str) -> Optional[User]:
    """
    Authenticate a platform super-admin by email + password across all tenants.

    A platform admin's User row is not tied to the target tenant, so this search
    is intentionally NOT tenant-scoped. Used for "god-login": a platform admin
    signs into any tenant's admin-web with their own credentials.

    Returns the matching platform-admin User (is_platform_admin=True,
    deleted_at IS NULL, password valid), or None. If multiple platform-admin rows
    share the email, the first match (ordered by id) is returned deterministically.
    """
    # A god-login request has already resolved the *entered* tenant, so
    # g.tenant_id is set. The do_orm_execute listener in core/database.py would
    # auto-scope this query to that tenant and never find the platform admin
    # (who lives in their own tenant). Temporarily clear g.tenant_id for this
    # intentional cross-tenant lookup, then restore it.
    from flask import has_request_context, g

    had_tenant = False
    saved_tenant_id = None
    if has_request_context() and getattr(g, "tenant_id", None) is not None:
        had_tenant = True
        saved_tenant_id = g.tenant_id
        g.tenant_id = None
    try:
        candidates = (
            User.query.filter_by(email=email, is_platform_admin=True)
            .filter(User.deleted_at.is_(None))
            .order_by(User.id)
            .all()
        )
    finally:
        if had_tenant:
            g.tenant_id = saved_tenant_id

    for user in candidates:
        if user.check_password(password):
            return user
    return None


def find_users_by_email_password(
    email: str,
    password: str,
) -> List[Tuple[User, Tenant]]:
    """
    Find all (user, tenant) pairs where the user has this email and password matches.
    Used when the app sends only email+password (no tenant) so we can identify
    which tenant(s) the user belongs to. Call only when g.tenant_id is None so
    User query is not tenant-scoped.

    Returns:
        List of (user, tenant) for active tenants only. Empty if no match.
    """
    users = User.query.filter_by(email=email).filter(User.deleted_at.is_(None)).all()
    matches: List[Tuple[User, Tenant]] = []
    for u in users:
        if not u.check_password(password):
            continue
        tenant = Tenant.query.get(u.tenant_id)
        if tenant and tenant.status == TENANT_STATUS_ACTIVE:
            matches.append((u, tenant))
    return matches


#: How long an account stays locked after too many wrong passwords, and how
#: many are allowed when a school has not configured its own limit. They live
#: beside `record_failed_login` because they are that rule's constants — the
#: login routes import them rather than restating them.
LOGIN_LOCKOUT_MINUTES = 15
DEFAULT_MAX_LOGIN_ATTEMPTS = 5


def accounts_for_email(email: str) -> List[User]:
    """Every live account with this email, in whichever school it belongs to.

    The companion to `find_users_by_email_password` for the case that one
    cannot answer: the password was wrong, so there is no match to return, and
    something still has to be counted against.
    """
    return (
        User.query.filter_by(email=email).filter(User.deleted_at.is_(None)).all()
    )


def record_failed_login(user: User, *, max_attempts: int) -> None:
    """Count one wrong password, and lock the account once it passes the limit.

    **One owner for both login paths.** Login branches on whether the body
    named a school, and only the branch that did used to count — so omitting
    `tenant_id` bought unlimited guesses against any account, bounded only by a
    per-IP rate limit that a rotating-IP attacker ignores. The rule lives here
    now so the two paths cannot drift again.

    Platform admins are skipped: they authenticate against every tenant, so a
    stranger guessing at one school could otherwise lock them out of all of
    them.
    """
    if getattr(user, "is_platform_admin", False):
        return

    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= max_attempts:
        user.login_locked_until = utc_now() + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
        user.failed_login_count = 0
    user.save()


def max_login_attempts() -> int:
    """How many wrong passwords a school allows before locking an account."""
    from modules.platform.services import get_platform_setting

    configured = get_platform_setting("max_login_attempts")
    if configured and str(configured).isdigit():
        return int(configured)
    return DEFAULT_MAX_LOGIN_ATTEMPTS


def logout_user(refresh_token: str) -> bool:
    """
    Logout user by revoking the session.
    
    Args:
        refresh_token: Refresh token of the session to revoke
        
    Returns:
        True if logout successful, False otherwise
    """
    from .tokens import session_for_token

    # Resolved through the token table rather than a column match, and
    # without tenant scope: a logout arrives before any tenant is resolved,
    # and scoping the lookup to a defaulted tenant is what used to make a
    # logout silently revoke nothing and return 200 anyway.
    session = session_for_token(refresh_token)
    if not session:
        # Idempotent: an already-revoked session is not an error to the person
        # trying to sign out of it. They wanted to be signed out; they are.
        return True

    session.revoke()
    return True


# ---------------------------------------------------------------------------
# Self-serve password change (nexchool Slice 4)
# ---------------------------------------------------------------------------

class PasswordChangeError(Exception):
    """Raised when password change fails for a domain reason.

    The route layer maps codes to HTTP statuses:
        current_password_invalid → 401
        password_weak            → 422
        password_unchanged       → 422
    """

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _is_password_strong(password: str) -> bool:
    """Strength rule: at least 8 chars AND at least one digit."""
    if not isinstance(password, str) or len(password) < 8:
        return False
    if not any(c.isdigit() for c in password):
        return False
    return True


def change_password(
    *,
    user_id: str,
    current_password: str,
    new_password: str,
    revoke_other_sessions: bool = False,
    current_session_id: Optional[str] = None,
) -> Dict:
    """Change an authenticated user's password.

    Args:
        user_id: ID of the authenticated user.
        current_password: Existing password (must match).
        new_password: Proposed new password.
        revoke_other_sessions: When True, revoke every other un-revoked
            Session for this user except current_session_id.
        current_session_id: If supplied, this session is preserved when
            revoke_other_sessions=True.

    Returns:
        {"revoked_sessions": int}

    Raises:
        PasswordChangeError with .code in:
            - "current_password_invalid"
            - "password_weak"
            - "password_unchanged"
    """
    user = User.query.get(user_id)
    if user is None or not user.check_password(current_password):
        raise PasswordChangeError("current_password_invalid")

    if current_password == new_password:
        raise PasswordChangeError("password_unchanged")

    if not _is_password_strong(new_password):
        raise PasswordChangeError("password_weak")

    user.set_password(new_password)

    revoked = 0
    if revoke_other_sessions:
        # Guard against the route layer forgetting to pass current_session_id.
        # Without it, the loop below would revoke the caller's own session and
        # log them out immediately after password change.
        if not current_session_id:
            raise PasswordChangeError(
                code="current_session_required",
                message=(
                    "revoke_other_sessions=True requires current_session_id "
                    "so the active session is preserved."
                ),
            )
        q = Session.query.filter_by(user_id=user.id, revoked=False).filter(
            Session.id != current_session_id
        )
        for session in q.all():
            session.revoke()
            revoked += 1

    db.session.commit()
    return {"revoked_sessions": revoked}
