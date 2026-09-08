"""What happened at the door.

Before this, `modules/auth/` wrote exactly one audit record in the whole
module — the platform admin's god-login entry. Nothing recorded who signed in,
from where, by which method, or why an attempt failed. With one way in that is
a weakness; with the several the identity work is heading toward, one of which
will cost money per attempt, it is untenable.

**A table of its own, not `TenantAuditLog`.** That model requires
`actor_name`, `actor_role`, `module`, `action`, `resource_type` and
`description` to be non-null, and a failed sign-in has no known actor and may
have no resolvable tenant — so it would mean inventing four values for the
most common event in the system. It is also tenant-scoped, which would stop
the platform reading across schools to notice one attacker working through
several of them. Both are the reasons this is separate.

**Identifiers are hashed.** An events table holding every address anyone ever
typed at a login screen is a directory of the school. The hash is enough to
correlate repeated attempts on one identifier, which is what the table is for,
and useless as a mailing list.
"""

from __future__ import annotations

import hashlib
import uuid

from core.database import db
from core.school_time import utc_now

# --- what happened ---------------------------------------------------------
#
# The full vocabulary is declared here so later phases add rows rather than
# invent a parallel one. Phase 0d emits the first two; the rest arrive with
# the flows that produce them.

EVENT_LOGIN_SUCCESS = "login_success"
EVENT_LOGIN_FAILURE = "login_failure"
EVENT_CHALLENGE_ISSUED = "challenge_issued"
EVENT_CHALLENGE_VERIFIED = "challenge_verified"
EVENT_LOGOUT = "logout"
EVENT_CREDENTIAL_ISSUED = "credential_issued"
EVENT_CREDENTIAL_RESET = "credential_reset"
EVENT_IDENTIFIER_ISSUED = "identifier_issued"
#: Distinct from the above on purpose. An identifier issued alongside a new
#: account is routine; one added to a student who was already here is a school
#: turning admission-number sign-in on for people it had already admitted, and
#: an operator reading the log wants to tell those apart.
EVENT_IDENTIFIER_BACKFILLED = "admission_identifier_backfilled"
EVENT_IDENTIFIER_RETIRED = "identifier_retired"
EVENT_POLICY_CHANGED = "policy_changed"
EVENT_CREDENTIAL_FORCE_CHANGE = "credential_force_change"
EVENT_SESSION_REVOKED = "session_revoked"
EVENT_SESSIONS_REVOKED_ALL = "sessions_revoked_all"
# --- the session and token lifecycle, completed ---
EVENT_SESSION_CREATED = "session_created"
EVENT_REFRESH_SUCCESS = "refresh_success"
EVENT_REFRESH_FAILURE = "refresh_failure"
EVENT_REFRESH_ROTATED = "refresh_token_rotated"
EVENT_REFRESH_REUSE = "refresh_token_reuse_detected"
#: Two of one client's own contexts renewed at the same moment — the second
#: presented a token the first had just spent. It reads exactly like a replay
#: and is not one, so it is refused without ending the session, and recorded
#: here so that "how often does this happen" is a question with an answer.
#: See `_is_a_race` in `tokens.py` for what separates the two.
EVENT_REFRESH_RACE = "refresh_race_detected"
# --- the account lifecycle ---
EVENT_ACCOUNT_SUSPENDED = "account_suspended"
EVENT_ACCOUNT_REACTIVATED = "account_reactivated"
EVENT_ACCOUNT_LOCKED = "account_locked"
EVENT_CREDENTIAL_CHANGED = "credential_changed"
# --- policy ---
EVENT_METHOD_ENABLED = "authentication_method_enabled"
EVENT_METHOD_DISABLED = "authentication_method_disabled"

EVENT_TYPES = (
    EVENT_LOGIN_SUCCESS,
    EVENT_LOGIN_FAILURE,
    EVENT_CHALLENGE_ISSUED,
    EVENT_CHALLENGE_VERIFIED,
    EVENT_LOGOUT,
    EVENT_CREDENTIAL_ISSUED,
    EVENT_CREDENTIAL_RESET,
    EVENT_IDENTIFIER_ISSUED,
    EVENT_IDENTIFIER_BACKFILLED,
    EVENT_IDENTIFIER_RETIRED,
    EVENT_POLICY_CHANGED,
    EVENT_CREDENTIAL_FORCE_CHANGE,
    EVENT_SESSION_REVOKED,
    EVENT_SESSIONS_REVOKED_ALL,
    EVENT_SESSION_CREATED,
    EVENT_REFRESH_SUCCESS,
    EVENT_REFRESH_FAILURE,
    EVENT_REFRESH_ROTATED,
    EVENT_REFRESH_REUSE,
    EVENT_REFRESH_RACE,
    EVENT_ACCOUNT_SUSPENDED,
    EVENT_ACCOUNT_REACTIVATED,
    EVENT_ACCOUNT_LOCKED,
    EVENT_CREDENTIAL_CHANGED,
    EVENT_METHOD_ENABLED,
    EVENT_METHOD_DISABLED,
)

# --- why it failed ----------------------------------------------------------
#
# Recorded, never returned. The API answers with one coarse `InvalidCredentials`
# whatever the cause, so that it cannot be used to find out which addresses
# exist; the precise reason lives here, where only an operator sees it.

REASON_NO_IDENTIFIER_MATCH = "no_identifier_match"
REASON_CREDENTIAL_MISMATCH = "credential_mismatch"
REASON_ACCOUNT_LOCKED = "account_locked"
REASON_ACCOUNT_SUSPENDED = "account_suspended"
REASON_ACCOUNT_DELETED = "account_deleted"
REASON_EMAIL_NOT_VERIFIED = "email_not_verified"
REASON_NO_PERMISSIONS = "no_permissions"
REASON_POLICY_DENIED = "policy_denied"
REASON_MAINTENANCE_MODE = "maintenance_mode"
REASON_TENANT_UNRESOLVED = "tenant_unresolved"
REASON_TENANT_INACTIVE = "tenant_inactive"
REASON_UNKNOWN_METHOD = "unknown_method"
REASON_MISSING_CREDENTIALS = "missing_credentials"
REASON_TENANT_CHOICE_REQUIRED = "tenant_choice_required"

# --- why an administrative operation did nothing ----------------------------
#
# A credential operation that skipped a student is not a failure, and the
# reason is what makes a bulk result readable.

REASON_NO_ACCOUNT = "no_account"
REASON_ALREADY_HAD_CREDENTIAL = "already_had_credential"
REASON_ALREADY_HAD_IDENTIFIER = "already_had_identifier"
REASON_METHOD_NOT_ENABLED = "method_not_enabled"
#: There is no credential of that kind to act on.
REASON_NO_CREDENTIAL = "no_credential"
#: The method's own limiter declined before the proof was compared.
REASON_THROTTLED = "throttled"


def hash_identifier(value: str) -> str:
    """A correlation key for an identifier, never the identifier.

    sha256 of the normalized value, the same device `handoff.py` uses so a
    database dump yields nothing usable. Two attempts on one address share a
    hash; nobody reading the table learns the address.
    """
    if not value:
        return ""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


class AuthEvent(db.Model):
    """One thing that happened at the door.

    Append-only. Not a `TenantBaseModel`: `tenant_id` is nullable because a
    failed attempt that named no school has no tenant to record, and because
    the platform must be able to read across schools to see one attacker
    working through several — which a tenant-scoped model would prevent.
    """

    __tablename__ = "auth_events"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    tenant_id = db.Column(
        db.String(36),
        db.ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    account_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    #: What kind of string was presented, and a hash of it. Never the value.
    identifier_type = db.Column(db.String(30), nullable=True)
    identifier_value_hash = db.Column(db.String(64), nullable=True, index=True)

    method_key = db.Column(db.String(40), nullable=False)
    event_type = db.Column(db.String(40), nullable=False, index=True)
    #: The internal taxonomy. Never returned to a client.
    reason = db.Column(db.String(40), nullable=True)

    client_surface = db.Column(db.String(30), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)

    #: Who performed this, when somebody acted on somebody else's account.
    #: `SET NULL` because a departed administrator's account may be removed
    #: and the record that they reset a credential must outlive them.
    actor_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    session_id = db.Column(
        db.String(36),
        db.ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )

    __table_args__ = (
        db.Index("idx_auth_events_tenant_created", "tenant_id", "created_at"),
        db.Index("idx_auth_events_account_created", "account_id", "created_at"),
        db.Index(
            "idx_auth_events_identifier_created",
            "identifier_value_hash",
            "created_at",
        ),
    )

    def __repr__(self):
        return f"<AuthEvent {self.event_type}/{self.method_key} {self.created_at}>"


def record_event(
    *,
    event_type: str,
    tenant_id=None,
    account_id=None,
    actor_user_id=None,
    method_key: str = "administrative",
    reason=None,
    identifier_type=None,
    identifier_value=None,
    session_id=None,
):
    """Write down that an administrator did something to somebody's sign-in.

    The same table the pipeline writes to, so "what happened to this account"
    is one query rather than two. `method_key` is `administrative` for these:
    nobody authenticated, an operator acted.

    Who acted goes in `actor_user_id`. It used to be encoded into the event's
    `user_agent` slot as `actor:<id>`, because there was no column — honest
    about being a workaround, registered as debt 55, and retired by migration
    133, which also moved the rows that carried it.

    Never called with a password. There is no parameter for one.
    """
    from core.database import db
    from flask import has_request_context, request

    event = AuthEvent(
        tenant_id=tenant_id,
        account_id=account_id,
        identifier_type=identifier_type,
        identifier_value_hash=(
            hash_identifier(identifier_value) if identifier_value else None
        ),
        method_key=method_key[:40],
        event_type=event_type,
        reason=reason,
        client_surface=(
            request.headers.get("X-Client-Surface") if has_request_context() else None
        ),
        ip_address=request.remote_addr if has_request_context() else None,
        # The real user agent now that the slot is no longer carrying an
        # actor id. Which is the point of migration 133: `user_agent` says
        # what the request came from, `actor_user_id` says who sent it.
        user_agent=(
            request.headers.get("User-Agent") if has_request_context() else None
        ),
        actor_user_id=actor_user_id,
        session_id=session_id,
    )
    db.session.add(event)
    return event
