"""What a school hands somebody when it opens an account for them.

Two things, and they are different: the **identifier** that will find the
account, and the **credential** that will prove it. Keeping them apart is the
whole reason `account_identifiers` and `account_credentials` are separate
tables, and this module is where a provisioning path — admissions, the bulk
importer — reaches for both without knowing how either is stored.

The rule that governs the credential half is A5:

    No issued credential is derived from any attribute of the person.

The two generators this replaces both broke it. `generate_student_password`
produced the first three letters of the child's name plus their birth year
(``SAH2003``); `default_student_import_password` produced their first name plus
``@123`` (``rahul@123``). Neither is a secret from anyone who knows the child,
and a class of nine-year-olds knows each other. They are left in place for the
paths this phase does not touch and are no longer used to issue anything.
"""

from __future__ import annotations

import secrets
from typing import Optional

from core.database import db
from core.school_time import utc_now

from .identifiers import IDENTIFIER_TYPE_ADMISSION_ID, normalize_identifier

#: The alphabet a credential is drawn from.
#:
#: `0/O` and `1/l/I` are absent because this is read off a printed slip and
#: typed by a child, and a password nobody can enter is a support call rather
#: than a security measure. What is left is 32 letters and 8 digits — 54 bits
#: of entropy over ten characters, which is far beyond what the lockout after
#: five wrong attempts leaves reachable.
CREDENTIAL_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"

#: Ten rather than eight: the specification allows 8–10, the extra characters
#: cost a child nothing to type once, and they are never typed again because
#: the credential must be replaced on first use.
CREDENTIAL_LENGTH = 10


def generate_initial_password(length: int = CREDENTIAL_LENGTH) -> str:
    """A credential that says nothing about the person it belongs to.

    `secrets`, not `random` — the latter is seeded predictably and is not for
    anything that guards an account. Nothing about the child is mixed in, not
    even as a prefix: a password that begins with a known string is a password
    with that many fewer characters.
    """
    return "".join(secrets.choice(CREDENTIAL_ALPHABET) for _ in range(length))


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

def issue_admission_identifier(account, admission_number: str, *, issued_by_user_id=None):
    """Let this account be found by the school's admission number.

    Returns the identifier row, or None when there is nothing to issue — no
    account, no admission number, or the school does not permit students to
    sign in this way. **Being told no is the ordinary case**, not an error:
    the method is off by default and a school turns it on deliberately.

    Idempotent. A student whose identifier already exists gets that one back
    rather than a second row, so re-running an import cannot produce two.
    """
    from .models import AccountIdentifier
    from .policy import is_method_allowed
    from .strategies.identifier_password import IdentifierPasswordStrategy

    if account is None or not admission_number or not str(admission_number).strip():
        return None

    # The school's decision, asked through the policy service rather than
    # re-implemented here. A tenant that has not enabled admission sign-in
    # gets no identifier issued, so the table does not fill up with
    # credentials for a door that is closed.
    if not is_method_allowed(account, IdentifierPasswordStrategy.key):
        return None

    normalized = normalize_identifier(IDENTIFIER_TYPE_ADMISSION_ID, admission_number)

    existing = (
        AccountIdentifier.query.filter_by(
            tenant_id=account.tenant_id,
            account_id=account.id,
            identifier_type=IDENTIFIER_TYPE_ADMISSION_ID,
        )
        .filter(AccountIdentifier.deleted_at.is_(None))
        .first()
    )
    if existing is not None:
        # An admission number that has changed is a credential operation with
        # its own rules, and this is not the place for it. What matters here
        # is that a second row is never created.
        return existing

    identifier = AccountIdentifier(
        tenant_id=account.tenant_id,
        account_id=account.id,
        identifier_type=IDENTIFIER_TYPE_ADMISSION_ID,
        identifier_value=str(admission_number).strip(),
        identifier_value_normalized=normalized,
        # The school issuing it is the verification. Nobody emails an
        # admission number to confirm it.
        is_verified=True,
        verified_at=utc_now(),
        is_primary=True,
        issued_by_user_id=issued_by_user_id,
    )
    db.session.add(identifier)
    return identifier


class MobileAlreadyInUse(Exception):
    """Another account in this school already signs in with that number."""


def issue_mobile_identifier(account, mobile: str, *, issued_by_user_id=None):
    """Let this account be found by a mobile number.

    Deliberately its own operation, and deliberately **never automatic**.
    `Person.phone_number` looks like the same thing and is not: it is typed by
    a clerk during admission, never verified, freely rewritten by spreadsheet
    imports, and — by design — shared, because a father and a mother are two
    people carrying one household number. Promoting it to an identifier would
    mint sign-in credentials nobody asked for, from data nobody proved, some
    of which is the same placeholder repeated across half a school.

    So a mobile identifier is issued when an operator says so, for one account,
    with the number they confirmed. `Person.phone_number` is a suggestion to
    show them, never a source of truth.

    Returns the identifier row, or None when there is nothing to issue — no
    account, no valid number, or the school has not enabled mobile sign-in.
    Raises :class:`MobileAlreadyInUse` when another account in the same school
    already holds it, rather than silently doing nothing: two people who share
    a phone is a real situation somebody has to decide about, and an operation
    that quietly succeeded without issuing anything would hide it.

    Idempotent for the same account: re-issuing the number it already has
    returns that row rather than creating a second.
    """
    from .identifiers import IDENTIFIER_TYPE_MOBILE, normalize_mobile
    from .models import AccountIdentifier
    from .policy import is_method_allowed
    from .strategies.mobile_otp import MobileOtpStrategy
    from .strategies.mobile_pin import MobilePinStrategy

    if account is None or not mobile:
        return None

    normalized = normalize_mobile(mobile)
    if not normalized:
        # Not a dialable number. No identifier is minted for "n/a", a landline
        # or a mistyped digit — an identifier that cannot receive a code is
        # only a way to fail later.
        return None

    # The school's decision, asked through the policy service rather than
    # re-implemented here — and asked about the *identifier*, not one method.
    #
    # Originally this asked only whether OTP was enabled, which was right while
    # OTP was the only thing a mobile number was for. It stopped being right
    # the moment a second method used the same identifier: a school that gives
    # its students PINs but not codes would have been unable to issue the
    # mobile numbers those PINs are signed in with.
    mobile_methods = (MobileOtpStrategy.key, MobilePinStrategy.key)
    if not any(is_method_allowed(account, method) for method in mobile_methods):
        return None

    live = AccountIdentifier.query.filter_by(
        tenant_id=account.tenant_id,
        identifier_type=IDENTIFIER_TYPE_MOBILE,
        identifier_value_normalized=normalized,
    ).filter(AccountIdentifier.deleted_at.is_(None))

    for existing in live.all():
        if existing.account_id == account.id:
            return existing
        raise MobileAlreadyInUse(
            "Another account at this school already signs in with that number."
        )

    identifier = AccountIdentifier(
        tenant_id=account.tenant_id,
        account_id=account.id,
        identifier_type=IDENTIFIER_TYPE_MOBILE,
        identifier_value=str(mobile).strip(),
        identifier_value_normalized=normalized,
        # **Not** verified by being issued, unlike an admission number. A
        # school knows the admission number it assigned; it only believes the
        # phone number it was told. Possession is proved the first time a code
        # sent to it is used, and `mark_mobile_verified` records that.
        is_verified=False,
        is_primary=True,
        issued_by_user_id=issued_by_user_id,
    )
    db.session.add(identifier)
    return identifier


def mark_mobile_verified(identifier) -> None:
    """Record that somebody proved they hold this number.

    Called after a code sent to it was used. Until then the identifier says,
    honestly, that nobody has demonstrated possession.
    """
    if identifier is None or identifier.is_verified:
        return
    identifier.is_verified = True
    identifier.verified_at = utc_now()


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def issue_pin_credential(
    account,
    raw_pin: str,
    *,
    issued_by_user_id: Optional[str] = None,
    is_provisional: bool = True,
):
    """Record the PIN a school just issued.

    A PIN is its own credential type, not a password wearing a different name.
    `account_credentials` has allowed `('password', 'pin')` since it was
    created and its unique index is on `(account_id, credential_type)`, so an
    account holds at most one live PIN and holding a password as well is the
    ordinary case rather than a conflict.

    Two consequences worth stating, both of which fall out of that design
    rather than needing code here:

    **A password change does not touch the PIN.** `person_link`'s sync hook
    mirrors `users.password_hash` into the *password* credential specifically,
    so rotating one secret leaves the other alone.

    **`must_change` is per credential.** A PIN that must be replaced does not
    make the account's password stale, and `users.force_password_reset` — which
    is about the password — is not touched here.

    Hashed by the same helper passwords use. A PIN is shorter, not less
    valuable, and a weaker hash chosen because the input is short is how a
    database leak becomes a million recovered PINs. The defence against the
    small keyspace is the online attempt limit, not the hash.
    """
    from werkzeug.security import generate_password_hash

    from .models import AccountCredential
    from .pin import validate_pin

    if account is None:
        return None

    # Validated here rather than trusted from the caller, so no path can store
    # a PIN the policy would have refused.
    checked = validate_pin(raw_pin)
    secret_hash = generate_password_hash(checked)

    existing = (
        AccountCredential.query.filter_by(account_id=account.id, credential_type="pin")
        .filter(AccountCredential.deleted_at.is_(None))
        .first()
    )
    if existing is not None:
        # The same credential, rotated — not a second row shadowing the first.
        # The unique index would refuse one anyway; doing it here means a reset
        # is an update rather than an IntegrityError somebody has to interpret.
        existing.secret_hash = secret_hash
        existing.hash_algorithm = _algorithm_of(secret_hash)
        existing.is_provisional = is_provisional
        existing.issued_by_user_id = issued_by_user_id
        existing.last_rotated_at = utc_now()
        existing.must_change = False
        db.session.flush()
        return existing

    credential = AccountCredential(
        tenant_id=account.tenant_id,
        account_id=account.id,
        credential_type="pin",
        secret_hash=secret_hash,
        hash_algorithm=_algorithm_of(secret_hash),
        is_provisional=is_provisional,
        issued_by_user_id=issued_by_user_id,
        must_change=False,
    )
    db.session.add(credential)
    db.session.flush()
    return credential


def _algorithm_of(secret_hash: str) -> str:
    """What produced a hash, recorded so verification can dispatch on it and a
    stronger algorithm can be adopted later without a migration."""
    return secret_hash.split("$", 1)[0][:40] if "$" in secret_hash else "unknown"


def live_pin_credential(account):
    """This account's PIN, if it has one."""
    from .models import AccountCredential

    if account is None:
        return None
    return (
        AccountCredential.query.filter_by(account_id=account.id, credential_type="pin")
        .filter(AccountCredential.deleted_at.is_(None))
        .first()
    )


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def issue_password_credential(
    account,
    raw_password: str,
    *,
    issued_by_user_id: Optional[str] = None,
    is_provisional: bool = True,
):
    """Record the password the school just issued, in both places it lives.

    `users.password_hash` remains authoritative and is written by the caller
    through `set_password`; this adds the `account_credentials` row that Phase
    0d's pipeline reads first. Both carry the same hash — the account is the
    one that computed it — so the two can never disagree about the secret.

    `must_change` follows the school's own setting: a credential somebody else
    chose is replaced on first use unless the school has said otherwise.
    `is_provisional` stays true regardless, because it records *who chose the
    secret*, which no setting changes.
    """
    from .models import AccountCredential
    from .policy import student_credential_policy
    from .policy_models import CREDENTIAL_FORCE_CHANGE

    if account is None or not account.password_hash:
        return None

    existing = (
        AccountCredential.query.filter_by(
            account_id=account.id, credential_type="password"
        )
        .filter(AccountCredential.deleted_at.is_(None))
        .first()
    )
    if existing is not None:
        # The account already has one. Keeping it in step with the column is
        # `person_link`'s job, not a second issuance.
        return existing

    must_change = (
        student_credential_policy(account.tenant_id) == CREDENTIAL_FORCE_CHANGE
    )

    credential = AccountCredential(
        tenant_id=account.tenant_id,
        account_id=account.id,
        credential_type="password",
        secret_hash=account.password_hash,
        hash_algorithm=_algorithm_of(account.password_hash),
        must_change=must_change and bool(account.force_password_reset),
        is_provisional=is_provisional,
        issued_by_user_id=issued_by_user_id,
        issued_at=utc_now(),
    )
    db.session.add(credential)
    return credential


def _algorithm_of(password_hash: str) -> str:
    """What produced this hash, read out of it rather than assumed.

    A werkzeug hash carries its method in the first `$`-separated field. One
    that carries no `$` is recorded as unknown rather than given an algorithm
    it does not have — the same rule the Phase 0b backfill used.
    """
    if password_hash and "$" in password_hash:
        return password_hash.split("$", 1)[0][:40]
    return "unknown"
