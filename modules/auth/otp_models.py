"""The one-time code a school sends to a phone, while it is in flight.

An OTP is a **factor**, not a credential. `account_credentials` holds things an
account keeps — a password, one day a PIN — and its own docstring says an OTP
"is issued, verified and destroyed in flight, and gets no row here." This table
is that flight: it exists so the code can be checked once, expired, counted
against and then thrown away, and for no longer than that.

What is stored is a **hash**, never the code. A support engineer reading this
table cannot sign in as anybody, and neither can a database dump.

The mobile number is stored hashed too, and that is a departure from the rest
of the auth schema worth stating. `account_identifiers` keeps the number in
clear because a school's office has to recognise it. Here there is no operator
reading rows to recognise a person — the row exists for ninety seconds and is
only ever matched against a number somebody just typed — so keeping it in
clear would be storing personal data for no purpose it serves.
"""

from __future__ import annotations

import uuid

from core.database import db
from core.models import TenantBaseModel
from core.school_time import utc_now

# --- the life of one code ----------------------------------------------------
#
# Short, and each state earns its place. There is no `delivered`: a provider
# accepting a message is not a handset receiving one (Phase 3), and a status
# claiming otherwise would be a lie the system could never check.

#: Created, not yet handed to a provider.
STATUS_CREATED = "created"
#: A provider accepted it. Not "delivered" — see above.
STATUS_SENT = "sent"
#: The provider refused it. No code will arrive; the challenge is over.
STATUS_FAILED = "failed"
#: Verified and spent. Terminal, and the reason replay cannot work.
STATUS_CONSUMED = "consumed"
#: A newer code was issued for the same number. The old one stops working the
#: instant the new one exists, so a person reading two messages cannot use the
#: first.
STATUS_SUPERSEDED = "superseded"

STATUSES = (
    STATUS_CREATED,
    STATUS_SENT,
    STATUS_FAILED,
    STATUS_CONSUMED,
    STATUS_SUPERSEDED,
)

#: The statuses a code may still be verified against. Expiry and attempts are
#: checked separately — they are conditions, not states, and storing them as
#: states would mean a background job had to write them to be true.
VERIFIABLE_STATUSES = (STATUS_CREATED, STATUS_SENT)

#: Why a code was sent. One constant, so a bill can be explained back to the
#: feature that caused it and so `purpose` is not spelled three ways.
PURPOSE_AUTHENTICATION = "authentication_otp"


class MobileOtpChallenge(TenantBaseModel):
    """One code, sent to one number, for one sign-in attempt."""

    __tablename__ = "mobile_otp_challenges"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    #: Which account the code will sign in, resolved when the challenge was
    #: issued. Bound at issue time so that verification cannot be redirected to
    #: a different account by anything the caller sends.
    account_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The identifier row that resolved it, recorded on the session afterwards
    #: so support can answer which number was used.
    identifier_id = db.Column(
        db.String(36),
        db.ForeignKey("account_identifiers.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: sha256 of the normalized E.164 number. Enough to find the challenge for
    #: a number somebody just typed; not enough to read anybody's number back.
    mobile_hash = db.Column(db.String(64), nullable=False)
    #: sha256 of the code, salted per challenge. Never the code.
    code_hash = db.Column(db.String(64), nullable=False)
    #: Per-challenge salt, so two challenges with the same code do not share a
    #: hash and a rainbow table over six digits is useless.
    code_salt = db.Column(db.String(32), nullable=False)

    purpose = db.Column(
        db.String(40), nullable=False, default=PURPOSE_AUTHENTICATION,
        server_default=PURPOSE_AUTHENTICATION,
    )
    status = db.Column(
        db.String(20), nullable=False, default=STATUS_CREATED,
        server_default=STATUS_CREATED,
    )

    #: How many wrong codes have been tried against this challenge, and how
    #: many are allowed. The limit is stored rather than read from config at
    #: verification time so that changing the setting cannot retroactively give
    #: a live challenge more guesses.
    attempts = db.Column(
        db.Integer, nullable=False, default=0, server_default=db.text("0")
    )
    max_attempts = db.Column(db.Integer, nullable=False)

    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    consumed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    #: The provider's id for the message, from Phase 3's normalized result.
    #: Support's only way to ask a vendor what happened to one send.
    provider_reference = db.Column(db.String(120), nullable=True)
    #: Why the send failed, as a Phase 3 normalized code. Never a vendor string.
    failure_code = db.Column(db.String(40), nullable=True)

    #: Which challenge replaced this one, when a resend superseded it.
    superseded_by_id = db.Column(
        db.String(36),
        db.ForeignKey("mobile_otp_challenges.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Hashed, like the number. Enough to rate-limit and to investigate abuse,
    #: not a log of where a person was.
    request_ip_hash = db.Column(db.String(64), nullable=True)
    client_surface = db.Column(db.String(30), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        # The verification read path: this school, this number, still live.
        db.Index(
            "idx_mobile_otp_lookup", "tenant_id", "mobile_hash", "status", "expires_at"
        ),
        db.Index("idx_mobile_otp_account", "tenant_id", "account_id"),
        db.CheckConstraint(
            "status IN " + str(tuple(STATUSES)), name="ck_mobile_otp_status"
        ),
        db.CheckConstraint("attempts >= 0", name="ck_mobile_otp_attempts"),
        db.CheckConstraint("max_attempts > 0", name="ck_mobile_otp_max_attempts"),
    )

    def is_expired(self, *, now=None) -> bool:
        return (now or utc_now()) >= self.expires_at

    def is_exhausted(self) -> bool:
        return self.attempts >= self.max_attempts

    @property
    def is_verifiable(self) -> bool:
        """Whether a code may still be checked against this challenge.

        Status, expiry and attempts together — the three ways a challenge can
        stop being usable, asked as one question so no caller checks two of
        them and forgets the third.
        """
        return (
            self.status in VERIFIABLE_STATUSES
            and not self.is_expired()
            and not self.is_exhausted()
        )

    def to_dict(self):
        """What a caller may be told about a challenge.

        No hash, no salt, no number, no code — and no account id either, which
        would turn an unauthenticated request into a way to find out whether a
        number belongs to somebody.
        """
        return {
            "challenge_id": self.id,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "attempts_remaining": max(self.max_attempts - self.attempts, 0),
        }

    def __repr__(self):
        return f"<MobileOtpChallenge {self.id} {self.status}>"
