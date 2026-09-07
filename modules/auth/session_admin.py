"""Seeing and ending the sessions an account has open.

Until now a session could be created and could expire, and everything in
between was invisible: there was no way to ask what an account had open, and
the only way to end one was a side effect of changing a password — or the
`logout` route's cookie branch, which is unauthenticated and ends *every*
session for whoever the token names.

So this adds the two operations the product was missing, and one explicit,
authenticated `logout everywhere` so that behaviour has a front door instead
of only a surprising back one. The old route is left exactly as it is.

**No secret leaves this module.** A session's refresh token is the credential
that session is made of, and a listing that included it would hand every
session to whoever could read one.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from core.database import db

from .event_models import (
    EVENT_SESSION_REVOKED,
    EVENT_SESSIONS_REVOKED_ALL,
    record_event,
)


def list_sessions(account, *, include_revoked: bool = False) -> List[Dict]:
    """What this account has open, and from where.

    Metadata only. `refresh_token` is not in the projection and there is no
    field here that could carry it.
    """
    from .models import Session

    query = Session.query.filter_by(user_id=account.id)
    if not include_revoked:
        query = query.filter(Session.revoked.is_(False))

    return [
        {
            "id": session.id,
            "login_method": session.login_method,
            "client_surface": session.client_surface,
            "ip_address": session.ip_address,
            "user_agent": session.user_agent,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "last_accessed_at": (
                session.last_accessed_at.isoformat()
                if session.last_accessed_at
                else None
            ),
            "expires_at": (
                session.refresh_token_expires_at.isoformat()
                if session.refresh_token_expires_at
                else None
            ),
            "revoked": session.revoked,
            "revoked_at": session.revoked_at.isoformat() if session.revoked_at else None,
        }
        for session in query.order_by(Session.created_at.desc()).all()
    ]


def revoke_session(account, session_id: str, *, actor_user_id: str = None) -> bool:
    """End one session, and only that one.

    Looked up by id **and** account, so a session id belonging to somebody
    else is simply not found rather than revoked. Returns False when there is
    nothing live to end, which the caller reports as a 404 — a revoked session
    and a session that never existed look the same from outside.
    """
    from .models import Session

    session = Session.query.filter_by(
        id=session_id, user_id=account.id, revoked=False
    ).first()
    if session is None:
        return False

    session.revoke()
    record_event(
        event_type=EVENT_SESSION_REVOKED,
        tenant_id=account.tenant_id,
        account_id=account.id,
        actor_user_id=actor_user_id,
        session_id=session.id,
    )
    db.session.flush()
    return True


def revoke_all_sessions(
    account, *, actor_user_id: str = None, keep_session_id: Optional[str] = None
) -> int:
    """End every session this account has open.

    `keep_session_id` spares the caller's own, which is what makes "sign me
    out everywhere else" possible without signing the operator out of the
    screen they are standing on.
    """
    from .models import Session

    query = Session.query.filter_by(user_id=account.id, revoked=False)
    if keep_session_id:
        query = query.filter(Session.id != keep_session_id)

    revoked = 0
    for session in query.all():
        session.revoke()
        revoked += 1

    record_event(
        event_type=EVENT_SESSIONS_REVOKED_ALL,
        tenant_id=account.tenant_id,
        account_id=account.id,
        actor_user_id=actor_user_id,
    )
    db.session.flush()
    return revoked


def current_session_id() -> Optional[str]:
    """Which session is making this request.

    Read from the access token's `sid` claim, which `authenticate_request`
    publishes on `g`. It used to be found by looking up the caller's refresh
    token, sent as a header on every request — a habit the clients dropped
    when refresh tokens began to rotate, because a token that may be spent
    once cannot ride along on everything. The access token names its session
    directly, so nothing has to be looked up and no credential has to be sent
    where it is not being spent.

    None when the caller holds a token minted before sessions were named, or
    when there is no authenticated caller at all. Every caller here treats
    that as "cannot identify" and does the cautious thing rather than guessing.
    """
    from flask import g

    return getattr(g, "auth_session_id", None)
