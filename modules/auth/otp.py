"""Issuing a one-time code, and spending it exactly once.

The whole of OTP's security is in two properties, and everything in this file
exists to hold one of them:

**The code is never stored.** A salted hash is. So a database dump, a support
engineer, a log file and a backup all contain nothing that can sign anybody in.

**The code is spent once.** Verification is a single conditional UPDATE that
consumes the challenge in the same statement that checks it, so two requests
arriving with the same correct code cannot both win. A Python-level "if not
consumed: consume" would let both through, and under a real race it would.

Sending is Phase 3's business, not this module's. This asks the channel-
agnostic messaging layer for a message — over whichever of `sms` or
`whatsapp` the school has chosen — and never learns which company carried
it, what it cost, or how that company reports failure.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy import update

from core.database import db
from core.school_time import utc_now

from .otp_models import (
    PURPOSE_AUTHENTICATION,
    STATUS_CONSUMED,
    STATUS_CREATED,
    STATUS_FAILED,
    STATUS_SENT,
    STATUS_SUPERSEDED,
    VERIFIABLE_STATUSES,
    MobileOtpChallenge,
)

logger = logging.getLogger(__name__)

# --- the shape of a code -----------------------------------------------------

#: Six digits: what a person can read off a screen and type without a mistake,
#: and what every SMS OTP anybody has used looks like. The brute-force defence
#: is the attempt limit, not the length — a million combinations is far too few
#: to survive unlimited guessing and far more than enough to survive five.
OTP_LENGTH = 6
#: How long a code is good for. One value, read from here by everything.
OTP_TTL_SECONDS = 300
#: Wrong guesses allowed against one code.
MAX_VERIFICATION_ATTEMPTS = 5


def generate_code(length: int = OTP_LENGTH) -> str:
    """A uniformly random decimal code from a cryptographic source.

    `secrets.randbelow(10**length)` rather than `randbelow(...) % 10**length`
    or `random.randint` — the first is uniform by construction, the second has
    modulo bias, and the third is a Mersenne Twister whose next output can be
    predicted from its previous ones. Zero-padded, so `000042` is as likely as
    any other value and the code is always the same length.
    """
    return f"{secrets.randbelow(10 ** length):0{length}d}"


def _hash_code(code: str, salt: str) -> str:
    """The stored verifier. Salted per challenge, so two challenges sharing a
    code do not share a hash and six digits cannot be reversed from a table."""
    return hmac.new(salt.encode(), (code or "").encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class OtpRequestResult:
    """What happened when a code was asked for.

    `challenge` and `reason` are the internal truth; the route decides what a
    caller is told, and deliberately tells them the same thing either way. See
    `routes.py` — distinguishing "sent" from "that number is nobody" is the
    enumeration oracle this whole flow is shaped to avoid.
    """

    accepted: bool
    challenge: Optional[MobileOtpChallenge] = None
    reason: Optional[str] = None
    retry_after_seconds: Optional[int] = None


REASON_NO_ACCOUNT = "no_account_for_mobile"
REASON_AMBIGUOUS = "mobile_resolves_to_several_accounts"
REASON_METHOD_NOT_ALLOWED = "method_not_allowed"
REASON_THROTTLED = "throttled"
REASON_DELIVERY_FAILED = "delivery_failed"
REASON_ACCOUNT_UNUSABLE = "account_unusable"


def request_otp(
    *,
    tenant_id: str,
    mobile: str,
    ip_address: Optional[str] = None,
    client_surface: Optional[str] = None,
    purpose: str = PURPOSE_AUTHENTICATION,
) -> OtpRequestResult:
    """Send a code to this number, if everything says we should.

    Tenant-scoped throughout: the number is looked up inside the school that
    was named, never across schools. A number that is nobody's here may well be
    somebody's elsewhere, and finding that out is not this endpoint's job.
    """
    from .identifiers import IDENTIFIER_TYPE_MOBILE, normalize_mobile
    from .otp_throttle import check_request_allowed, hash_value, record_request_sent

    normalized = normalize_mobile(mobile)
    if not normalized:
        # Not a number at all. Refused before anything is spent or counted.
        return OtpRequestResult(accepted=False, reason=REASON_NO_ACCOUNT)

    mobile_hash = hash_value(normalized)

    # Throttle first, before the lookup. A refused request must cost nothing —
    # not a query, not an SMS, and not a timing difference that says whether
    # the number is known.
    decision = check_request_allowed(
        tenant_id=tenant_id, mobile_hash=mobile_hash, ip_address=ip_address
    )
    if not decision.allowed:
        _record(
            event_type="otp_rate_limited",
            tenant_id=tenant_id,
            reason=decision.reason,
            identifier_value=normalized,
        )
        return OtpRequestResult(
            accepted=False,
            reason=REASON_THROTTLED,
            retry_after_seconds=decision.retry_after_seconds,
        )

    matches = _accounts_for_mobile(tenant_id, normalized)
    if not matches:
        return OtpRequestResult(accepted=False, reason=REASON_NO_ACCOUNT)
    if len(matches) > 1:
        # Never `.first()`. A number that means two people means we do not know
        # who is asking, and guessing would sign somebody into a stranger's
        # account. See `docs/modules/identity-management.md`.
        logger.warning(
            "OTP refused: a mobile resolves to %d accounts (tenant=%s)",
            len(matches),
            tenant_id,
        )
        return OtpRequestResult(accepted=False, reason=REASON_AMBIGUOUS)

    account, identifier = matches[0]

    if not _account_can_sign_in(account):
        return OtpRequestResult(accepted=False, reason=REASON_ACCOUNT_UNUSABLE)

    from .policy import is_method_allowed
    from .strategies.mobile_otp import MobileOtpStrategy

    if not is_method_allowed(account, MobileOtpStrategy.key, client_surface or "any"):
        # The school has not turned this on. Refused before a message is sent,
        # so a disabled method cannot be used to spend a school's money.
        return OtpRequestResult(accepted=False, reason=REASON_METHOD_NOT_ALLOWED)

    challenge = _create_challenge(
        tenant_id=tenant_id,
        account=account,
        identifier=identifier,
        mobile_hash=mobile_hash,
        purpose=purpose,
        ip_address=ip_address,
        client_surface=client_surface,
    )
    code = challenge._plaintext_code  # noqa: SLF001 - in memory only, never stored

    sent = _deliver(
        tenant_id=tenant_id,
        challenge=challenge,
        destination=normalized,
        code=code,
        purpose=purpose,
    )
    if not sent:
        return OtpRequestResult(accepted=False, reason=REASON_DELIVERY_FAILED)

    # Counted only now, because only now did it cost anything.
    record_request_sent(
        tenant_id=tenant_id, mobile_hash=mobile_hash, ip_address=ip_address
    )
    return OtpRequestResult(accepted=True, challenge=challenge)


def _accounts_for_mobile(tenant_id: str, normalized: str):
    """Every account this school has issued that number to.

    Returns a list rather than one row on purpose. A partial unique index
    currently makes more than one impossible within a school — but the caller
    handles the plural case anyway, so that relaxing the index for households
    later cannot turn this into an arbitrary choice by omission.
    """
    from .identifiers import IDENTIFIER_TYPE_MOBILE
    from .models import AccountIdentifier, User

    rows = (
        db.session.query(User, AccountIdentifier)
        .join(AccountIdentifier, AccountIdentifier.account_id == User.id)
        .filter(
            AccountIdentifier.tenant_id == tenant_id,
            AccountIdentifier.identifier_type == IDENTIFIER_TYPE_MOBILE,
            AccountIdentifier.identifier_value_normalized == normalized,
            AccountIdentifier.deleted_at.is_(None),
            User.tenant_id == tenant_id,
            User.deleted_at.is_(None),
        )
        .order_by(User.id)
        .all()
    )
    return rows


def _account_can_sign_in(account) -> bool:
    """The cheap checks, so a code is not sent to somebody who cannot use it.

    Deliberately not the full set: account status, verification and permissions
    are the pipeline's and are enforced at verification, where they already
    live. This only avoids spending money on a message that could never work.
    """
    return not account.is_suspended and account.deleted_at is None


def _create_challenge(
    *, tenant_id, account, identifier, mobile_hash, purpose, ip_address, client_surface
) -> MobileOtpChallenge:
    """Mint a code, store its hash, and retire whatever came before it.

    Superseding is what makes a resend safe to offer: the moment a new code
    exists the old one stops working, so somebody holding two messages cannot
    use the first and an attacker cannot keep an old code alive by asking for
    new ones.
    """
    from .otp_throttle import hash_value

    now = utc_now()

    superseded = (
        MobileOtpChallenge.query.filter(
            MobileOtpChallenge.tenant_id == tenant_id,
            MobileOtpChallenge.mobile_hash == mobile_hash,
            MobileOtpChallenge.purpose == purpose,
            MobileOtpChallenge.status.in_(VERIFIABLE_STATUSES),
        )
        .with_for_update()
        .all()
    )

    code = generate_code()
    salt = secrets.token_hex(16)
    challenge = MobileOtpChallenge(
        tenant_id=tenant_id,
        account_id=account.id,
        identifier_id=identifier.id if identifier is not None else None,
        mobile_hash=mobile_hash,
        code_hash=_hash_code(code, salt),
        code_salt=salt,
        purpose=purpose,
        status=STATUS_CREATED,
        max_attempts=MAX_VERIFICATION_ATTEMPTS,
        expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
        request_ip_hash=hash_value(ip_address) if ip_address else None,
        client_surface=(client_surface or None),
    )
    db.session.add(challenge)
    db.session.flush()

    for old in superseded:
        old.status = STATUS_SUPERSEDED
        old.superseded_by_id = challenge.id
    db.session.flush()

    # Carried in memory to the sender and never assigned to a column. The
    # underscore says it is not part of the row.
    challenge._plaintext_code = code  # noqa: SLF001
    return challenge


def _deliver(*, tenant_id, challenge, destination, code, purpose) -> bool:
    """Hand the message to Phase 3, down whichever wire the school chose.

    Marks the challenge `sent` only when a provider accepted it. A provider
    that refused means no code will ever arrive, so leaving the challenge
    verifiable would strand somebody waiting for a message that is not coming.
    """
    from modules.integrations.messaging import send_message

    from .otp_message import build_otp_message, otp_variables
    from .policy import otp_delivery_channel

    result = send_message(
        tenant_id=tenant_id,
        channel=otp_delivery_channel(tenant_id),
        purpose=purpose,
        destination=destination,
        variables=otp_variables(code),
        body=build_otp_message(code),
        # One logical send. A retry carrying the same key must not become a
        # second message.
        idempotency_key=f"otp:{challenge.id}",
    )

    if not result.success:
        challenge.status = STATUS_FAILED
        challenge.failure_code = result.error_code
        db.session.flush()
        _record(
            event_type="otp_delivery_failed",
            tenant_id=tenant_id,
            account_id=challenge.account_id,
            reason=result.error_code,
        )
        return False

    # `sent`, not `delivered`. A provider accepting a request is not a handset
    # receiving a message, and Phase 3 is careful about the difference.
    challenge.status = STATUS_SENT
    challenge.sent_at = utc_now()
    challenge.provider_reference = result.provider_message_id
    db.session.flush()

    _record(
        event_type="challenge_issued",
        tenant_id=tenant_id,
        account_id=challenge.account_id,
    )
    return True


# ---------------------------------------------------------------------------
# Spending it
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OtpVerificationResult:
    verified: bool
    challenge: Optional[MobileOtpChallenge] = None
    reason: Optional[str] = None


REASON_NO_CHALLENGE = "no_live_challenge"
REASON_WRONG_CODE = "wrong_code"
REASON_EXPIRED = "expired"
REASON_EXHAUSTED = "attempts_exhausted"


def verify_code(
    *,
    tenant_id: str,
    mobile: str,
    code: str,
    account_id: Optional[str] = None,
    challenge_id: Optional[str] = None,
    purpose: str = PURPOSE_AUTHENTICATION,
) -> OtpVerificationResult:
    """Check a code and spend it, atomically.

    The consuming UPDATE carries every condition in its WHERE clause —
    unconsumed, unexpired, under the attempt limit, right hash. So the check
    and the spend are one statement, and two requests arriving together with
    the same correct code produce exactly one winner: whichever the database
    serializes first matches zero rows on its second try.

    A wrong code increments the attempt counter and does not reveal how many
    are left; the challenge simply stops working when they run out.
    """
    from .otp_throttle import hash_value

    normalized_mobile = _normalized(mobile)
    if not normalized_mobile or not code:
        return OtpVerificationResult(verified=False, reason=REASON_NO_CHALLENGE)

    mobile_hash = hash_value(normalized_mobile)

    query = MobileOtpChallenge.query.filter(
        MobileOtpChallenge.tenant_id == tenant_id,
        MobileOtpChallenge.mobile_hash == mobile_hash,
        MobileOtpChallenge.purpose == purpose,
        MobileOtpChallenge.status.in_(VERIFIABLE_STATUSES),
    )
    if account_id:
        query = query.filter(MobileOtpChallenge.account_id == account_id)
    if challenge_id:
        # When the caller names a challenge it must be *this* one. A named
        # challenge that does not match is refused rather than ignored.
        query = query.filter(MobileOtpChallenge.id == challenge_id)

    challenge = query.order_by(MobileOtpChallenge.created_at.desc()).first()
    if challenge is None:
        return OtpVerificationResult(verified=False, reason=REASON_NO_CHALLENGE)

    if challenge.is_expired():
        return OtpVerificationResult(
            verified=False, challenge=challenge, reason=REASON_EXPIRED
        )
    if challenge.is_exhausted():
        return OtpVerificationResult(
            verified=False, challenge=challenge, reason=REASON_EXHAUSTED
        )

    expected = _hash_code(code, challenge.code_salt)
    # Constant time, so the number of matching leading characters cannot be
    # measured from how long the answer took.
    if not hmac.compare_digest(expected, challenge.code_hash):
        _count_attempt(challenge)
        _record(
            event_type="otp_verification_failed",
            tenant_id=tenant_id,
            account_id=challenge.account_id,
            reason=REASON_WRONG_CODE,
        )
        return OtpVerificationResult(
            verified=False, challenge=challenge, reason=REASON_WRONG_CODE
        )

    now = utc_now()
    consumed = db.session.execute(
        update(MobileOtpChallenge)
        .where(
            MobileOtpChallenge.id == challenge.id,
            MobileOtpChallenge.tenant_id == tenant_id,
            # Every reason the challenge could have stopped being usable, in
            # the statement that spends it. This is the single-use guarantee.
            MobileOtpChallenge.status.in_(VERIFIABLE_STATUSES),
            MobileOtpChallenge.expires_at > now,
            MobileOtpChallenge.attempts < MobileOtpChallenge.max_attempts,
            MobileOtpChallenge.code_hash == expected,
        )
        .values(
            status=STATUS_CONSUMED,
            verified_at=now,
            consumed_at=now,
            updated_at=now,
        )
    )

    if consumed.rowcount != 1:
        # Somebody else won the race, or it expired between the read and the
        # write. Either way this caller did not spend it.
        return OtpVerificationResult(
            verified=False, challenge=challenge, reason=REASON_NO_CHALLENGE
        )

    db.session.refresh(challenge)
    _record(
        event_type="challenge_verified",
        tenant_id=tenant_id,
        account_id=challenge.account_id,
    )
    return OtpVerificationResult(verified=True, challenge=challenge)


def _count_attempt(challenge) -> None:
    """One more wrong guess, counted in the database rather than in Python.

    An in-memory increment would lose count under concurrent guesses, which is
    exactly the situation the counter exists for.
    """
    db.session.execute(
        update(MobileOtpChallenge)
        .where(MobileOtpChallenge.id == challenge.id)
        .values(attempts=MobileOtpChallenge.attempts + 1, updated_at=utc_now())
    )
    db.session.flush()
    db.session.refresh(challenge)


def _normalized(mobile: str) -> str:
    from .identifiers import normalize_mobile

    return normalize_mobile(mobile)


def _record(*, event_type, tenant_id, account_id=None, reason=None, identifier_value=None):
    """Write down what happened, without writing down anything sensitive.

    Never the code, never the message, and the number only through the event
    table's own hashing — which for a mobile means the keyed digest, not the
    bare sha256 that suits an email address.
    """
    from .event_models import record_event

    try:
        record_event(
            event_type=event_type,
            tenant_id=tenant_id,
            account_id=account_id,
            method_key="mobile_otp",
            reason=reason,
            identifier_type="mobile" if identifier_value else None,
            identifier_value=identifier_value,
        )
    except Exception:  # noqa: BLE001 - an unwritten audit line must not fail a login
        logger.exception("could not record an OTP event")
