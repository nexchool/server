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

from flask import g, request
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
    """

    user: Optional[Any] = None
    new_access_token: Optional[str] = None
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
    from modules.auth.services import validate_jwt_token, refresh_access_token

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
        g.current_user = user
        return AuthenticatedRequest(user=user)

    # Access token expired — fall back to the refresh token.
    refresh_token = request.headers.get("X-Refresh-Token")
    if not refresh_token:
        return AuthenticatedRequest(error="Access token expired")

    new_access_token = refresh_access_token(refresh_token, request)
    if not new_access_token:
        return AuthenticatedRequest(error="Invalid refresh token")

    session = load_without_tenant_scope(
        lambda: Session.query.filter_by(
            refresh_token=refresh_token,
            revoked=False,
        ).first()
    )
    if not session:
        return AuthenticatedRequest(error="Session not found")

    user = load_without_tenant_scope(lambda: User.query.get(session.user_id))
    if not user or _acts_outside_own_tenant(user):
        return AuthenticatedRequest(error="Session not found")

    # Defense in depth: the refresh path already revokes sessions on
    # suspend/delete, but re-check so a stale-but-unrevoked session can never
    # re-mint access for an inactive account.
    if _account_inactive(user):
        return AuthenticatedRequest(error="Session expired")

    g.current_user = user
    session.last_accessed_at = utc_now()
    session.save()

    return AuthenticatedRequest(user=user, new_access_token=new_access_token)
