"""Issuing, rotating and revoking the pair a client holds.

Two tokens with two jobs. The **access token** proves who you are for fifteen
minutes and is checked on every request; the **refresh token** proves you may
have another one, is used rarely, and is worth far more to a thief.

Three properties this module exists to provide, none of which the previous
design had:

**Revocation is immediate.** An access token now names the session it came
from, and validation checks that session is still live. Before, revoking a
session only stopped future refreshes: the access token already in a client's
hands kept working until it expired — up to fifteen minutes by default, and up
to seven days for a school that had raised its session timeout. For an account
being suspended mid-incident that is not a window anybody should have to
explain.

**Refresh tokens rotate.** Every successful refresh spends the token and issues
its successor, so a stolen one is useful only until the real client next
refreshes.

**Reuse is detected, not merely refused.** Consumed generations are kept, so
presenting one means two parties hold copies. Which one is the thief is
unknowable from here, so the family is ended and both must sign in again.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import timedelta
from typing import Optional, Tuple

from core.database import db
from core.school_time import utc_now

from .refresh_models import RefreshToken, hash_refresh_token, new_refresh_token

logger = logging.getLogger(__name__)


class RefreshOutcome:
    """Why a refresh did or did not work.

    Distinguished internally so the audit record is precise, and collapsed by
    the route into one answer so a caller learns nothing from which it was.
    """

    OK = "ok"
    UNKNOWN = "unknown_token"
    EXPIRED = "expired"
    REUSED = "reuse_detected"
    #: Refused, but nothing revoked — see `_is_a_race`.
    RACED = "rotation_raced"
    SESSION_REVOKED = "session_revoked"
    ACCOUNT_INACTIVE = "account_inactive"
    TENANT_INACTIVE = "tenant_inactive"


#: How long after a token is spent its presentation is read as one client
#: racing itself rather than as a thief replaying a stolen token.
#:
#: Two tabs of one browser share a refresh token but not the promise that
#: renews it, so when an access token expires they can start two renewals
#: milliseconds apart. The loser presents a token the winner has just spent,
#: which is byte-for-byte what a replay looks like — and ending the session for
#: it signs the person out of both tabs for the crime of leaving two open.
#:
#: Fifteen seconds is chosen against what the two cases actually look like: a
#: racing tab is *always* inside it, because it began before the winner
#: finished; a thief working from a copied token is almost never inside it, and
#: gains nothing when they are, because the answer is still a refusal.
ROTATION_GRACE_SECONDS = int(os.getenv("REFRESH_ROTATION_GRACE_SECONDS", 15))


# ---------------------------------------------------------------------------
# Issuing
# ---------------------------------------------------------------------------

def issue_refresh_token(session, *, generation: int = 1, replaces=None) -> str:
    """Mint a token for this session and return it. Stored only as a digest.

    The plaintext is returned to the caller and never written anywhere — not a
    column, not a log, not an event. It exists in the client's storage and
    nowhere else.

    **A token expires with its session, never after it.** Taking the session's
    own expiry rather than a constant is what keeps the absolute cap in
    `session_policy` absolute: a token minted with an independent window could
    outlive the ceiling it was supposed to be bounded by, and renewing with it
    would quietly extend a session past the point where its holder is meant to
    prove who they are again. Callers therefore slide the session first and
    mint second.
    """
    token = new_refresh_token()
    row = RefreshToken(
        tenant_id=session.tenant_id,
        session_id=session.id,
        user_id=session.user_id,
        token_hash=hash_refresh_token(token),
        generation=generation,
        issued_at=utc_now(),
        expires_at=session.refresh_token_expires_at,
    )
    db.session.add(row)
    db.session.flush()

    if replaces is not None:
        replaces.replaced_by_id = row.id
        db.session.flush()

    return token


def live_token_for(session) -> Optional[RefreshToken]:
    """The generation a client should currently be holding."""
    return (
        RefreshToken.query.filter_by(session_id=session.id)
        .filter(RefreshToken.consumed_at.is_(None))
        .order_by(RefreshToken.generation.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Spending one
# ---------------------------------------------------------------------------

def rotate(token: str) -> Tuple[str, Optional[object], Optional[str]]:
    """Spend a refresh token and issue its successor.

    Returns `(outcome, session, new_token)`. Every refusal path returns the
    same shape so a caller cannot tell them apart by structure.

    The consuming UPDATE carries its conditions in the WHERE clause, so two
    clients racing on one token produce exactly one winner and the loser is
    treated as reuse — which is the correct reading: if two parties hold the
    same token, one of them should not.
    """
    from sqlalchemy import update

    from core.models import TENANT_STATUS_ACTIVE, Tenant
    from core.authentication import load_without_tenant_scope

    from .models import Session, User

    if not token:
        return RefreshOutcome.UNKNOWN, None, None

    digest = hash_refresh_token(token)

    # Loaded without tenant scope on purpose: a refresh arrives before any
    # tenant has been resolved, and the row itself names the tenant. Every
    # check below is then made against *that* tenant, so nothing crosses.
    row = load_without_tenant_scope(
        lambda: RefreshToken.query.filter_by(token_hash=digest).first()
    )
    if row is None:
        return RefreshOutcome.UNKNOWN, None, None

    session = load_without_tenant_scope(
        lambda: Session.query.filter_by(id=row.session_id).first()
    )

    if row.consumed_at is not None:
        if _is_a_race(row):
            # One client's second context, moments behind its own first. Refuse
            # it — the successor's plaintext exists only in the winner's
            # storage and cannot be handed out twice — but do not end the
            # session over it.
            _record_race(row, session)
            return RefreshOutcome.RACED, session, None

        # Somebody is replaying a token the family already rotated past. Which
        # party is the thief cannot be known from here, so the family ends and
        # both sign in again.
        _end_the_family(row, session)
        return RefreshOutcome.REUSED, session, None

    if row.expires_at <= utc_now():
        return RefreshOutcome.EXPIRED, session, None

    if session is None or session.revoked:
        return RefreshOutcome.SESSION_REVOKED, session, None

    user = load_without_tenant_scope(lambda: User.query.filter_by(id=row.user_id).first())
    if user is None or user.deleted_at is not None or user.is_suspended:
        # A suspended account cannot refresh its way back in. The session is
        # ended too, so the next attempt is not even a lookup.
        if session is not None:
            _revoke_session(session)
        return RefreshOutcome.ACCOUNT_INACTIVE, session, None

    tenant = load_without_tenant_scope(
        lambda: Tenant.query.filter_by(id=row.tenant_id).first()
    )
    if tenant is None or tenant.status != TENANT_STATUS_ACTIVE:
        # A school that has been suspended cannot be re-entered by anybody
        # holding a token from before. Refresh is not a loophole around it.
        return RefreshOutcome.TENANT_INACTIVE, session, None

    consumed = db.session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.id == row.id,
            RefreshToken.consumed_at.is_(None),
        )
        .values(consumed_at=utc_now())
    )
    if consumed.rowcount != 1:
        # Lost the race by microseconds: between the check above and this
        # UPDATE, somebody else consumed the row. That is the same situation
        # `_is_a_race` describes, caught at the only other place it can be
        # caught, and it gets the same answer — refuse, revoke nothing. A
        # replay old enough to be a theft cannot arrive here, because it would
        # have been consumed long ago and taken the branch above.
        _record_race(row, session)
        return RefreshOutcome.RACED, session, None

    db.session.refresh(row)

    # Using a session is what keeps it alive — the idle limit slides forward
    # from now, and the absolute cap does not move, so a session in daily use
    # stays open until the cap reaches it and not one renewal longer. This
    # happens *before* the replacement is minted, because the token takes its
    # expiry from the session it belongs to.
    from .session_policy import slid_expiry

    session.refresh_token_expires_at = slid_expiry(session)

    replacement = issue_refresh_token(
        session, generation=row.generation + 1, replaces=row
    )
    session.last_accessed_at = utc_now()
    db.session.flush()

    return RefreshOutcome.OK, session, replacement


def _is_a_race(row) -> bool:
    """Whether a spent token is one client overtaking itself, not a replay.

    All three conditions have to hold, and each rules out a different way of
    being wrong:

    **Spent moments ago.** Outside `ROTATION_GRACE_SECONDS` there is no race
    left to lose — the winner finished long since — so a presentation that late
    is somebody working from a copy.

    **Its successor exists.** A consumed row with nothing recorded as replacing
    it was consumed by something other than a rotation, and nothing here should
    be forgiving about that.

    **The successor is itself unspent.** This is the condition that matters. If
    the successor has already been used, the real client has moved on, and
    whoever is holding this older generation is not merely behind — they are
    somewhere the real client no longer is. That is a theft, and it ends the
    family.
    """
    from core.authentication import load_without_tenant_scope

    if row.consumed_at is None or not row.replaced_by_id:
        return False

    if utc_now() - row.consumed_at > timedelta(seconds=ROTATION_GRACE_SECONDS):
        return False

    successor = load_without_tenant_scope(
        lambda: RefreshToken.query.filter_by(id=row.replaced_by_id).first()
    )
    return successor is not None and successor.consumed_at is None


def _record_race(row, session) -> None:
    """Write down that a client raced itself. Never the token itself."""
    from .event_models import EVENT_REFRESH_RACE, record_event

    try:
        record_event(
            event_type=EVENT_REFRESH_RACE,
            tenant_id=row.tenant_id,
            account_id=row.user_id,
            session_id=row.session_id,
            reason=f"generation:{row.generation}",
        )
    except Exception:  # noqa: BLE001 - an unwritten audit line must not mask this
        logger.exception("could not record refresh rotation race")


def _end_the_family(row, session) -> None:
    """Revoke the session and every generation of its token."""
    if session is not None:
        _revoke_session(session)

    db.session.query(RefreshToken).filter(
        RefreshToken.session_id == row.session_id,
        RefreshToken.consumed_at.is_(None),
    ).update({"consumed_at": utc_now()}, synchronize_session=False)
    db.session.flush()

    _record_reuse(row, session)


def _revoke_session(session) -> None:
    if session.revoked:
        return
    session.revoked = True
    session.revoked_at = utc_now()
    db.session.flush()


def _record_reuse(row, session) -> None:
    """Write down that a token was replayed. Never the token itself."""
    from .event_models import record_event

    try:
        record_event(
            event_type="refresh_token_reuse_detected",
            tenant_id=row.tenant_id,
            account_id=row.user_id,
            session_id=row.session_id,
            reason=f"generation:{row.generation}",
        )
    except Exception:  # noqa: BLE001 - an unwritten audit line must not mask this
        logger.exception("could not record refresh token reuse")


# ---------------------------------------------------------------------------
# Revocation, felt immediately
# ---------------------------------------------------------------------------

def revoke_session_tokens(session_id: str) -> None:
    """Retire every unspent generation for a session.

    Called wherever a session is revoked, so that ending a session ends the
    ability to refresh it as well as the ability to use it.
    """
    db.session.query(RefreshToken).filter(
        RefreshToken.session_id == session_id,
        RefreshToken.consumed_at.is_(None),
    ).update({"consumed_at": utc_now()}, synchronize_session=False)


def session_for_token(token: str):
    """The live session a refresh token belongs to, without spending it.

    For the callers that need to *identify* the caller's own session rather
    than renew it — logout, and the force-reset that keeps the current session
    while ending the others. Before, they matched the token against a column;
    now the token is only ever stored as a digest, so the lookup goes through
    it.
    """
    from core.authentication import load_without_tenant_scope

    from .models import Session

    if not token:
        return None

    digest = hash_refresh_token(token)
    row = load_without_tenant_scope(
        lambda: RefreshToken.query.filter_by(token_hash=digest).first()
    )
    if row is None or row.consumed_at is not None:
        return None

    session = load_without_tenant_scope(
        lambda: Session.query.filter_by(id=row.session_id).first()
    )
    return session if session is not None and not session.revoked else None


def session_is_live(session_id: str) -> bool:
    """Whether an access token naming this session may still be honoured.

    Consulted on every authenticated request. It is a primary-key lookup on a
    table the request already touches, which is the price of revocation being
    immediate — and the trade the architecture review asked for explicitly:
    correctness over avoiding a query.
    """
    from core.authentication import load_without_tenant_scope

    from .models import Session

    if not session_id:
        # A token minted before this phase carries no session. Those are
        # accepted until they expire — the alternative is signing out everybody
        # holding one at the moment of deploy, for tokens that are valid.
        return True

    session = load_without_tenant_scope(
        lambda: Session.query.filter_by(id=session_id).first()
    )
    return session is not None and not session.revoked
