"""Suspending somebody's access, and giving it back.

A school suspends a person's *access*, never their record. A suspended pupil
is still enrolled, still on the register, still in last term's results and
still visible to every member of staff who needs them — they simply cannot
sign in. Conflating the two would make a security action into a data action,
and there is no undo for that.

The same distinction runs through staff, and matters more there. **Suspending
an account is not ending an employment.** Authority in this system is held by
the employment (ADR-013), so ending one removes what a teacher may do;
suspending their account removes only their ability to authenticate, and the
employment, the authority and the teaching record are untouched. A school
locking out a teacher pending an enquiry wants the second, not the first, and
using account suspension as a stand-in for the employment domain would leave a
teacher who is still on the payroll looking like one who has left.

Suspension takes effect **immediately**, which is the point of doing it here
rather than by setting a column somewhere: sessions are revoked, refresh
tokens are retired, and the access token already in somebody's browser stops
working on its next request.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.database import db
from core.school_time import utc_now

logger = logging.getLogger(__name__)


class AccountStatusError(Exception):
    """The operation cannot be performed on that account."""


def suspend_account(account, *, actor_user_id: Optional[str] = None, reason: str = None):
    """Stop this account signing in, now.

    Four things, and the order matters only in that all of them happen: the
    flag is set, every session is revoked, every unspent refresh token is
    retired, and the act is recorded with who did it.

    Idempotent — suspending an already-suspended account re-revokes anything
    that has appeared since and is otherwise a no-op, which is what an
    operator clicking twice should get.
    """
    from .services import revoke_all_user_sessions

    if account is None:
        raise AccountStatusError("There is no such account at this school.")
    if getattr(account, "is_platform_admin", False):
        # A school cannot lock the platform operator out of its own tenancy;
        # that is A3, and it is the same exemption the policy service makes.
        raise AccountStatusError("A platform operator's access is not a school's to withdraw.")

    account.is_suspended = True
    db.session.flush()

    revoked = revoke_all_user_sessions(account.id)

    _record(
        "account_suspended",
        account,
        actor_user_id=actor_user_id,
        reason=reason,
    )
    logger.info(
        "account suspended (tenant=%s account=%s sessions=%d)",
        account.tenant_id,
        account.id,
        revoked,
    )
    return {"account_id": account.id, "is_suspended": True, "sessions_revoked": revoked}


def reactivate_account(account, *, actor_user_id: Optional[str] = None):
    """Let this account sign in again — but not resume where it left off.

    **No session is restored.** The tokens that existed before the suspension
    stay dead, and the person signs in fresh. That is deliberate: reviving a
    session would resurrect whatever device held it, including the one the
    suspension was about, and "reactivated" would mean something different
    depending on how long ago the suspension happened. A fresh sign-in makes
    the state after reactivation identical for everybody.

    Credentials and identifiers are untouched — the password and PIN they had
    before still work.
    """
    if account is None:
        raise AccountStatusError("There is no such account at this school.")

    account.is_suspended = False
    db.session.flush()

    _record("account_reactivated", account, actor_user_id=actor_user_id)
    logger.info(
        "account reactivated (tenant=%s account=%s)", account.tenant_id, account.id
    )
    return {"account_id": account.id, "is_suspended": False, "sessions_restored": 0}


def describe_access(account) -> dict:
    """What an operator needs to see before deciding. Carries no secret."""
    from .models import AccountCredential, AccountIdentifier, Session
    from .policy import allowed_methods

    if account is None:
        return {"has_account": False}

    credentials = {
        credential.credential_type: {
            "issued": True,
            "is_provisional": credential.is_provisional,
            "must_change": credential.must_change,
            "last_rotated_at": (
                credential.last_rotated_at.isoformat()
                if credential.last_rotated_at
                else None
            ),
        }
        for credential in AccountCredential.query.filter_by(account_id=account.id)
        .filter(AccountCredential.deleted_at.is_(None))
        .all()
    }

    identifiers = [
        {"type": row.identifier_type, "value": row.identifier_value,
         "is_verified": row.is_verified}
        for row in AccountIdentifier.query.filter_by(account_id=account.id)
        .filter(AccountIdentifier.deleted_at.is_(None))
        .order_by(AccountIdentifier.identifier_type)
        .all()
    ]

    return {
        "has_account": True,
        "account_id": account.id,
        "email": account.email,
        "is_suspended": bool(account.is_suspended),
        "is_locked": bool(
            account.login_locked_until and account.login_locked_until > utc_now()
        ),
        "must_change_password": bool(account.force_password_reset),
        "last_login_at": (
            account.last_login_at.isoformat() if account.last_login_at else None
        ),
        "identifiers": identifiers,
        "credentials": credentials,
        # What this account may actually sign in with, from the school's
        # policy and this person's relationships — not a guess from the
        # identifiers they happen to hold.
        "allowed_methods": allowed_methods(account),
        "active_sessions": Session.query.filter_by(
            user_id=account.id, revoked=False
        ).count(),
    }


def _record(event_type: str, account, *, actor_user_id=None, reason=None):
    from .event_models import record_event

    try:
        record_event(
            event_type=event_type,
            tenant_id=account.tenant_id,
            account_id=account.id,
            actor_user_id=actor_user_id,
            reason=reason,
        )
    except Exception:  # noqa: BLE001 - an unwritten audit line must not fail this
        logger.exception("could not record an account status event")
