"""Request authentication, shared by every transport.

Authentication answers one question: which User is making this request?

Both transports authenticate through :func:`authenticate_request` — REST via
``core.decorators.auth.auth_required``, GraphQL via ``graphql_api.context`` — so
token validation, refresh, tenant isolation and account-status revocation exist
exactly once. Transports only translate the outcome into their own error shape.

Authentication is not authorization: this module resolves identity, never what
that identity may do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

from flask import g, has_request_context, request
from core.school_time import utc_now


def load_without_tenant_scope(loader: Callable[[], Any]) -> Any:
    """Run ``loader()`` with tenant scoping disabled, then restore g.tenant_id.

    Auth identity comes from the token/session, not the request's tenant. A
    platform admin god-logging into another tenant has ``g.tenant_id`` set to the
    *entered* tenant while their User/Session rows live in their home tenant, so a
    tenant-scoped identity lookup would 401 ("User not found") on every tenant
    route. Clearing ``g.tenant_id`` for just the lookup keeps identity resolution
    tenant-agnostic; ``_acts_outside_own_tenant`` re-imposes isolation afterwards.
    """
    saved_tenant_id = getattr(g, "tenant_id", None)
    if saved_tenant_id is not None:
        g.tenant_id = None
    try:
        return loader()
    finally:
        if saved_tenant_id is not None:
            g.tenant_id = saved_tenant_id


def _acts_outside_own_tenant(user) -> bool:
    """True if a non-platform user's token is being used in another tenant.

    Now that identity is resolved unscoped, this re-imposes tenant isolation: a
    normal user may only act within their own tenant, while a platform admin may
    operate in any tenant (god-login).
    """
    current_tenant_id = getattr(g, "tenant_id", None)
    return (
        current_tenant_id is not None
        and getattr(user, "tenant_id", None) != current_tenant_id
        and not getattr(user, "is_platform_admin", False)
    )


def _account_inactive(user) -> bool:
    """True if the user is soft-deleted or suspended.

    A live access token outlives suspension/soft-delete (~15 min) unless we
    re-check status on every request. Rejecting here makes revocation take
    effect at once instead of only on the next refresh.
    """
    return (
        getattr(user, "deleted_at", None) is not None
        or getattr(user, "is_suspended", False)
    )


@dataclass(frozen=True)
class AuthenticatedRequest:
    """Outcome of authenticating one request.

    ``new_access_token`` is set only when the access token was expired and a
    valid refresh token minted a replacement; transports must return it to the
    client (REST: ``X-New-Access-Token`` header).

    ``new_refresh_token`` comes with it, because refresh tokens now rotate: the
    one the client sent has been spent, and a client that kept using it would
    be replaying a consumed token — which the server treats as theft. Both
    headers must be honoured together or neither.
    """

    user: Optional[Any] = None
    new_access_token: Optional[str] = None
    new_refresh_token: Optional[str] = None
    error: Optional[str] = None

    @property
    def failed(self) -> bool:
        return self.error is not None


def _read_access_token() -> Optional[str]:
    """Access token from the Authorization header, or the panel's auth cookie."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1]
    return request.cookies.get("auth-token")


def authenticate_request() -> AuthenticatedRequest:
    """Identify the caller, refreshing an expired access token when possible.

    Sets ``g.current_user`` on success. Every failure is a 401-equivalent; the
    message is deliberately coarse so a caller cannot probe account existence.
    """
    # Imported here to avoid a circular import at module load.
    from modules.auth.models import User, Session
    from modules.auth.services import generate_access_token, validate_jwt_token

    access_token = _read_access_token()
    if not access_token:
        return AuthenticatedRequest(error="Missing access token")

    payload = validate_jwt_token(access_token, token_type="access")
    if payload:
        user = load_without_tenant_scope(lambda: User.query.get(payload["sub"]))
        if not user or _acts_outside_own_tenant(user):
            return AuthenticatedRequest(error="User not found")
        if _account_inactive(user):
            # 401 (not 403) routes admin-web through logout+redirect-to-login,
            # where re-login surfaces the proper AccountSuspended reason.
            return AuthenticatedRequest(error="Session expired")

        # The session this token came from must still be live. Without this a
        # revocation is only a promise about the *future*: the token already
        # in somebody's hands kept working until it expired, which for a
        # suspended account mid-incident is not a window anybody should have
        # to explain. It costs a primary-key lookup per request, deliberately.
        from modules.auth.tokens import session_is_live

        if not session_is_live(payload.get("sid")):
            return AuthenticatedRequest(error="Session expired")

        g.current_user = user
        g.auth_session_id = payload.get("sid")
        return AuthenticatedRequest(user=user)

    # Access token expired — fall back to the refresh token.
    refresh_token = request.headers.get("X-Refresh-Token")
    if not refresh_token:
        return AuthenticatedRequest(error="Access token expired")

    # Rotation happens here: the presented token is spent and its successor is
    # issued. Every refusal — unknown, expired, replayed, revoked session,
    # suspended account, suspended school — comes back as one coarse error, so
    # a caller holding a bad token learns only that it is bad.
    from modules.auth.tokens import RefreshOutcome, rotate

    outcome, session, replacement = rotate(refresh_token)
    if outcome != RefreshOutcome.OK or session is None:
        return AuthenticatedRequest(error="Invalid refresh token")

    user = load_without_tenant_scope(lambda: User.query.get(session.user_id))
    if not user or _acts_outside_own_tenant(user):
        return AuthenticatedRequest(error="Session not found")

    g.current_user = user
    g.auth_session_id = session.id
    session.last_accessed_at = utc_now()
    session.save()

    new_access_token = generate_access_token(
        user,
        tenant_id=session.tenant_id,
        method=session.login_method,
        session_id=session.id,
    )

    return AuthenticatedRequest(
        user=user,
        new_access_token=new_access_token,
        new_refresh_token=replacement,
    )


# ---------------------------------------------------------------------------
# Mandatory password change
# ---------------------------------------------------------------------------

#: What an account locked into a password change may still reach. Everything
#: else is refused until the password is set.
#:
#: The list is exactly the way out and the client's ability to render it:
#: change the password, read your own profile and the feature list the app
#: boots with, or leave. `tenant-branding` and `login` are unauthenticated and
#: never reach this check at all.
PASSWORD_RESET_EXEMPT_PATHS = frozenset({
    "/api/auth/password/force-reset",
    "/api/auth/logout",
    "/api/auth/profile",
    "/api/auth/enabled-features",
})

#: What a holder locked into a *PIN* change may still reach. A different set,
#: because a different credential is being replaced: the PIN change endpoint
#: rather than the password one. `profile` and `logout` are common to both —
#: an app has to be able to render who is signed in, and to sign out.
PIN_CHANGE_EXEMPT_PATHS = frozenset({
    "/api/auth/pin/change",
    "/api/auth/logout",
    "/api/auth/profile",
    "/api/auth/enabled-features",
})

PIN_CHANGE_ERROR = "PinChangeRequired"
PIN_CHANGE_MESSAGE = (
    "Set a new PIN before continuing. The one you signed in with was issued "
    "by your school and must be changed."
)

#: Distinct on purpose: a client has to tell "change your password" apart from
#: "you lack a permission", and both are 403.
PASSWORD_RESET_ERROR = "PasswordResetRequired"
PASSWORD_RESET_MESSAGE = (
    "Set a new password before continuing. The one you signed in with was "
    "issued by your school and must be changed."
)


def password_change_is_outstanding(user, path: Optional[str] = None) -> bool:
    """Is this caller locked into a password change on this request?

    `force_password_reset` is set by seven provisioning paths — teacher and
    student creation, both bulk imports, sub-admin creation, and the
    platform-admin resets — and was read only by the login and profile
    payloads. That made it advice to the client: the account still received a
    fully privileged token and could ignore the redirect, keeping a temporary
    password an administrator chose. For a bulk-imported account that password
    is derived from the person's own name.

    `path` defaults to the current request's. Pass it explicitly from a
    transport that has no meaningful path of its own — GraphQL serves every
    operation from one URL, so it exempts nothing: password operations are
    REST (backend-architecture.md lists them as infrastructure), which leaves
    no legitimate GraphQL call to make while locked out.
    """
    if user is None or not getattr(user, "force_password_reset", False):
        return False
    if path is None:
        path = request.path if has_request_context() else None
    return path not in PASSWORD_RESET_EXEMPT_PATHS


def pin_change_is_outstanding(user, path: Optional[str] = None) -> bool:
    """Is this caller locked into a PIN change on this request?

    The PIN's own flag, on its own credential row, and read only when the
    request is actually acting under a PIN sign-in — which is the whole
    subtlety. A pupil who signs in with their password should not be stopped
    because a PIN they have not used is provisional; the requirement is about
    the credential in use, not about the account.

    Until this existed the flag was written and read by nothing. A school that
    clicked "Ask for a new PIN" got a stored boolean and no behaviour: the
    child kept signing in with the PIN the school had just decided was
    compromised.
    """
    if user is None:
        return False

    if not has_request_context():
        return False

    # Only a session opened with a PIN is subject to it.
    method = getattr(g, "auth_login_method", None)
    if method is None:
        session_id = getattr(g, "auth_session_id", None)
        if not session_id:
            return False
        from modules.auth.models import Session

        session = load_without_tenant_scope(
            lambda: Session.query.filter_by(id=session_id).first()
        )
        method = session.login_method if session else None
        g.auth_login_method = method

    if method != "mobile_pin":
        return False

    from modules.auth.provisioning import live_pin_credential

    credential = live_pin_credential(user)
    if credential is None or not credential.must_change:
        return False

    if path is None:
        path = request.path if has_request_context() else None
    return path not in PIN_CHANGE_EXEMPT_PATHS
