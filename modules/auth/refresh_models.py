"""The token that keeps somebody signed in, and the record of every one issued.

A refresh token is the most valuable secret in the system: it survives longer
than an access token, and whoever holds one can mint access indefinitely. So it
is treated like a credential rather than like a session field, which is what
this table exists to change.

Four properties, and each closes a specific hole the previous design had:

**Opaque and random.** The old token was a JWT whose payload was
`{sub, type, iat, exp}` with second-granularity timestamps — so two sign-ins by
one account inside one second produced *byte-identical* tokens. Two live
sessions could share a token, `logout` resolved it with `.first()` and revoked
an arbitrary one, and the token kept working. A random 48-byte value cannot
collide.

**Hashed at rest.** The old column stored the token verbatim, so a database
dump was a set of working credentials. Only a digest is kept here; the value
exists in the client's storage and nowhere else.

**Single-use, rotated.** Every successful refresh consumes the token and issues
its successor. A stolen token is useful only until the real client next
refreshes.

**A family, so reuse is detectable.** Consumed rows are kept rather than
deleted, which is the whole point: presenting a consumed token means either a
thief is using a token the real client already rotated, or the real client is
using one a thief rotated. Either way somebody has a copy they should not, and
the safe answer is to end the family.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

from core.database import db
from core.models import TenantBaseModel
from core.school_time import utc_now

#: 48 bytes from the OS CSPRNG, URL-safe. Long enough that guessing is not a
#: threat model, short enough to sit in a header.
REFRESH_TOKEN_BYTES = 48


def new_refresh_token() -> str:
    """A fresh opaque token. The only place one is minted."""
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """The stored verifier.

    A plain sha256, deliberately: unlike a password this is 48 bytes of
    uniform randomness, so there is nothing to brute-force and no salt to add
    — a per-row salt would only prevent the lookup this table is built around.
    """
    return hashlib.sha256((token or "").encode()).hexdigest()


class RefreshToken(TenantBaseModel):
    """One generation of one session's refresh token."""

    __tablename__ = "refresh_tokens"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    #: The family. Every generation of a session's token shares it, so
    #: detecting reuse of any one of them can end all of them.
    session_id = db.Column(
        db.String(36),
        db.ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: sha256 of the token. Unique — the guarantee the old design could not
    #: make, and the reason two sessions can no longer share a token.
    token_hash = db.Column(db.String(64), nullable=False, unique=True)

    #: 1 for the token issued at sign-in, incrementing on each rotation. Not
    #: used for lookup; it is what makes a support conversation about "how many
    #: times has this device refreshed" answerable.
    generation = db.Column(
        db.Integer, nullable=False, default=1, server_default=db.text("1")
    )

    issued_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    #: Set when the token is spent. Kept rather than deleted: a row that is
    #: gone cannot tell you somebody replayed it.
    consumed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    #: Which generation replaced it, so a family reads as a chain.
    replaced_by_id = db.Column(
        db.String(36),
        db.ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        db.Index("idx_refresh_tokens_session", "tenant_id", "session_id"),
        db.CheckConstraint("generation > 0", name="ck_refresh_tokens_generation"),
    )

    @property
    def is_live(self) -> bool:
        return self.consumed_at is None and self.expires_at > utc_now()

    def __repr__(self):
        state = "consumed" if self.consumed_at else "live"
        return f"<RefreshToken gen={self.generation} {state}>"
