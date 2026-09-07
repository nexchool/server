"""Issuing, resetting and reporting on the credentials a school hands out.

Phase 1b gave students a way in. This is the half a school actually operates:
a child forgets a password in the second week of term, and somebody in the
office has to be able to give them a new one without a developer.

Everything here is **operator-triggered**. Nothing runs on boot, nothing runs
on deploy, and nothing touches a student the operator did not name. That is
not caution for its own sake — a function in this module can invalidate a
password, and one that ran by itself would do it to a whole school.

Three rules the whole module is built around:

**A plaintext password exists for one response and is then gone.** It is
returned by the operation that generated it and never stored, logged, audited
or retrievable afterwards. There is deliberately no read path that can produce
one, so a leak needs a code change rather than a request.

**Reset is destructive and never a default.** Issuing fills a gap; resetting
takes a working password away and ends the sessions using it. The two are
separate operations with separate names, and the bulk one does the first
unless it is explicitly asked for the second.

**A student is reached through their studentship, never by account id.** Every
entry point takes a `Student` the caller resolved inside their own tenant, so
an operator cannot reach another school's account by guessing an id.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

from core.database import db
from core.school_time import utc_now

from .event_models import (
    EVENT_CREDENTIAL_FORCE_CHANGE,
    EVENT_CREDENTIAL_ISSUED,
    EVENT_CREDENTIAL_RESET,
    EVENT_IDENTIFIER_BACKFILLED,
    EVENT_IDENTIFIER_ISSUED,
    REASON_ALREADY_HAD_CREDENTIAL,
    REASON_ALREADY_HAD_IDENTIFIER,
    REASON_METHOD_NOT_ENABLED,
    REASON_NO_CREDENTIAL,
    REASON_NO_ACCOUNT,
    record_event,
)
from .identifiers import IDENTIFIER_TYPE_ADMISSION_ID
from .provisioning import generate_initial_password, issue_admission_identifier

logger = logging.getLogger(__name__)

#: What a student was skipped for. Not failures — a school reading a bulk
#: result needs to tell "could not" from "did not need to".
SKIP_NO_ACCOUNT = REASON_NO_ACCOUNT
SKIP_ALREADY_HAD_CREDENTIAL = REASON_ALREADY_HAD_CREDENTIAL
SKIP_ALREADY_HAD_IDENTIFIER = REASON_ALREADY_HAD_IDENTIFIER
SKIP_METHOD_NOT_ENABLED = REASON_METHOD_NOT_ENABLED
SKIP_NO_CREDENTIAL = REASON_NO_CREDENTIAL


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def credential_status(student) -> Dict:
    """What an operator needs to answer "can this child sign in?".

    Carries no secret of any kind: not the hash, not the password, not a
    token. There is no field here that could ever hold one.
    """
    from .models import AccountCredential, AccountIdentifier

    account = student.user if student.user_id else None
    if account is None:
        return {
            "student_id": student.id,
            "admission_number": student.admission_number,
            "has_account": False,
            "identifiers": [],
            "credential": None,
            # Said out loud rather than left to be inferred: no email means no
            # account (ADR-003), and that is a decision the school made, not a
            # fault to be repaired here.
            "reason": SKIP_NO_ACCOUNT,
        }

    identifiers = (
        AccountIdentifier.query.filter_by(account_id=account.id)
        .filter(AccountIdentifier.deleted_at.is_(None))
        .order_by(AccountIdentifier.identifier_type)
        .all()
    )
    credential = (
        AccountCredential.query.filter_by(
            account_id=account.id, credential_type="password"
        )
        .filter(AccountCredential.deleted_at.is_(None))
        .first()
    )

    return {
        "student_id": student.id,
        "admission_number": student.admission_number,
        "has_account": True,
        "email": account.email,
        "is_suspended": bool(account.is_suspended),
        "last_login_at": (
            account.last_login_at.isoformat() if account.last_login_at else None
        ),
        "identifiers": [
            {
                "type": identifier.identifier_type,
                "value": identifier.identifier_value,
                "is_verified": identifier.is_verified,
                "is_primary": identifier.is_primary,
            }
            for identifier in identifiers
        ],
        "credential": (
            {
                "type": credential.credential_type,
                "is_provisional": credential.is_provisional,
                "must_change": credential.must_change,
                "issued_at": (
                    credential.issued_at.isoformat() if credential.issued_at else None
                ),
                "last_rotated_at": (
                    credential.last_rotated_at.isoformat()
                    if credential.last_rotated_at
                    else None
                ),
            }
            if credential is not None
            else None
        ),
        # The account's own flag, which is what the API actually enforces.
        "must_change_password": bool(account.force_password_reset),
        # The PIN is its own credential, alongside the password rather than
        # instead of it — one account may hold both, and neither reset touches
        # the other.
        "pin": _describe_pin(account),
    }


def _describe_pin(account) -> Dict:
    """Whether this child can sign in with a PIN, and since when.

    No hash, no digits, no length beyond the published policy — there is no
    field here that could carry a PIN, which is why there is no read path in
    the product that can produce one.
    """
    from .pin import PIN_LENGTH
    from .provisioning import live_pin_credential

    credential = live_pin_credential(account)
    if credential is None:
        return {"issued": False, "length": PIN_LENGTH}

    return {
        "issued": True,
        "length": PIN_LENGTH,
        "is_provisional": credential.is_provisional,
        "must_change": credential.must_change,
        "issued_at": credential.issued_at.isoformat() if credential.issued_at else None,
        "last_rotated_at": (
            credential.last_rotated_at.isoformat()
            if credential.last_rotated_at
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def issue_credential(student, *, actor_user_id: str = None, reset: bool = False) -> Dict:
    """Give this student a password, or replace the one they have.

    `reset=False` fills a gap and refuses to overwrite a working credential —
    which is what makes the bulk operation safe to retry. `reset=True` is the
    destructive one: the old password stops working and every session opened
    with it is ended.

    The plaintext is in the return value and nowhere else, ever.
    """
    from .provisioning import issue_password_credential
    from .services import revoke_all_user_sessions

    account = student.user if student.user_id else None
    if account is None:
        return _skipped(student, SKIP_NO_ACCOUNT)

    existing = _live_credential(account)
    if existing is not None and not reset:
        return _skipped(student, SKIP_ALREADY_HAD_CREDENTIAL)

    password = generate_initial_password()

    # The account computes the hash; the credential row copies it, so the two
    # can never disagree about the secret. `person_link` keeps them in step
    # from here on.
    account.set_password(password)
    account.force_password_reset = _should_force_change(account.tenant_id)
    account.failed_login_count = 0
    account.login_locked_until = None

    if existing is None:
        issue_password_credential(
            account, password, issued_by_user_id=actor_user_id, is_provisional=True
        )
    else:
        # Not a second row: the same credential, rotated. `person_link` copies
        # the new hash across on flush; what belongs here is the provenance.
        existing.is_provisional = True
        existing.issued_by_user_id = actor_user_id
        existing.last_rotated_at = utc_now()

    revoked = 0
    if reset:
        # The old password is gone, so anything still signed in with it must
        # go too — otherwise "reset the password" leaves the old way in open.
        revoked = revoke_all_user_sessions(account.id)

    identifier = _ensure_admission_identifier(account, student, actor_user_id)
    db.session.flush()

    record_event(
        event_type=EVENT_CREDENTIAL_RESET if reset else EVENT_CREDENTIAL_ISSUED,
        tenant_id=account.tenant_id,
        account_id=account.id,
        actor_user_id=actor_user_id,
    )

    return {
        "student_id": student.id,
        "status": "reset" if reset else "issued",
        "admission_number": student.admission_number,
        # The one moment this exists outside the operator's screen.
        "password": password,
        "must_change": bool(account.force_password_reset),
        "sessions_revoked": revoked,
        "admission_identifier_issued": identifier is not None,
    }


def issue_pin(student, *, actor_user_id: str = None, reset: bool = False) -> Dict:
    """Give this student a PIN, or replace the one they have.

    Deliberately the same shape as `issue_credential` — `reset` is the
    destructive one and is never the default, so a student who already has a
    working PIN is skipped rather than locked out.

    What it does **not** touch is as important as what it does. The password,
    the admission identifier, the email credential and every OTP challenge are
    all left exactly as they were: these are separate ways into the same
    account, and replacing one is not a reason to disturb another.

    The plaintext is in the return value and nowhere else, ever.
    """
    from .pin import generate_pin
    from .provisioning import issue_pin_credential, live_pin_credential
    from .services import revoke_all_user_sessions
    from .strategies.mobile_pin import MobilePinStrategy

    account = student.user if student.user_id else None
    if account is None:
        return _skipped(student, SKIP_NO_ACCOUNT)

    from .policy import is_method_allowed

    if not is_method_allowed(account, MobilePinStrategy.key):
        # The school has not enabled PIN sign-in for this child. Issuing one
        # anyway would fill the table with credentials for a door that is shut.
        return _skipped(student, SKIP_METHOD_NOT_ENABLED)

    existing = live_pin_credential(account)
    if existing is not None and not reset:
        return _skipped(student, SKIP_ALREADY_HAD_CREDENTIAL)

    pin = generate_pin()
    issue_pin_credential(
        account, pin, issued_by_user_id=actor_user_id, is_provisional=True
    )

    revoked = 0
    if reset:
        # The old PIN is gone, so anything still signed in with it must go too
        # — the same rule a password reset follows, and for the same reason.
        # Access tokens live out their remaining minutes exactly as they do
        # there; this phase does not change token semantics.
        revoked = revoke_all_user_sessions(account.id)

    db.session.flush()
    record_event(
        event_type=EVENT_CREDENTIAL_RESET if reset else EVENT_CREDENTIAL_ISSUED,
        tenant_id=account.tenant_id,
        account_id=account.id,
        actor_user_id=actor_user_id,
        method_key=MobilePinStrategy.key,
    )

    return {
        "student_id": student.id,
        "status": "reset" if reset else "issued",
        "credential": "pin",
        # The one moment this exists outside the operator's screen.
        "pin": pin,
        "sessions_revoked": revoked,
    }


def force_pin_change(student, *, actor_user_id: str = None) -> Dict:
    """Require a new PIN at the next sign-in, without issuing one.

    Set on the PIN's own row, so it says nothing about the password. An
    account whose password must also be changed is a separate fact, recorded
    separately, and neither operation disturbs the other.
    """
    from .provisioning import live_pin_credential
    from .strategies.mobile_pin import MobilePinStrategy

    account = student.user if student.user_id else None
    if account is None:
        return _skipped(student, SKIP_NO_ACCOUNT)

    credential = live_pin_credential(account)
    if credential is None:
        return _skipped(student, SKIP_NO_CREDENTIAL)

    credential.must_change = True
    db.session.flush()

    record_event(
        event_type=EVENT_CREDENTIAL_FORCE_CHANGE,
        tenant_id=account.tenant_id,
        account_id=account.id,
        actor_user_id=actor_user_id,
        method_key=MobilePinStrategy.key,
    )
    return {"student_id": student.id, "status": "force_change_set", "credential": "pin"}


def bulk_issue_pins(
    students: Iterable, *, actor_user_id: str = None, reset: bool = False
) -> Dict:
    """PINs for a set of students the caller has already scoped.

    The same service as the password bulk issuance, in the same shape and with
    the same safety: one child's failure does not lose the rest, and `reset`
    defaults to false so running it twice fills gaps rather than invalidating
    a term's worth of PINs.
    """
    issued: List[Dict] = []
    skipped: List[Dict] = []
    failed: List[Dict] = []
    requested = 0

    for student in students:
        requested += 1
        try:
            with db.session.begin_nested():
                outcome = issue_pin(
                    student, actor_user_id=actor_user_id, reset=reset
                )
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            logger.exception("PIN issuance failed for student %s", student.id)
            failed.append(
                {
                    "student_id": student.id,
                    "admission_number": student.admission_number,
                    "error": str(exc),
                }
            )
            continue

        if outcome.get("status") == "skipped":
            skipped.append(outcome)
        else:
            issued.append(outcome)

    return {
        "requested": requested,
        "processed": len(issued) + len(skipped) + len(failed),
        "issued": len(issued),
        "skipped": len(skipped),
        "failed": len(failed),
        "pins": issued,
        "skipped_students": skipped,
        "failed_students": failed,
        "counts_by_skip_reason": _tally(skipped),
    }


def force_password_change(student, *, actor_user_id: str = None) -> Dict:
    """Require this student to choose a new password, without giving them one.

    Deliberately not a reset. A school that suspects a password has been
    shared around a classroom wants the child to change it at the next
    sign-in; it does not want to hand out a new slip, and it does not want the
    child locked out in the meantime. Their current password keeps working
    exactly once more.
    """
    account = student.user if student.user_id else None
    if account is None:
        return _skipped(student, SKIP_NO_ACCOUNT)

    account.force_password_reset = True
    # `person_link` carries this to the credential row, so the two flags
    # cannot drift apart.
    db.session.flush()

    record_event(
        event_type=EVENT_CREDENTIAL_FORCE_CHANGE,
        tenant_id=account.tenant_id,
        account_id=account.id,
        actor_user_id=actor_user_id,
    )

    return {
        "student_id": student.id,
        "status": "force_change_set",
        "must_change": True,
    }


def _ensure_admission_identifier(account, student, actor_user_id):
    """Give the account its admission identifier if the school permits it."""
    from .models import AccountIdentifier

    before = (
        AccountIdentifier.query.filter_by(
            account_id=account.id, identifier_type=IDENTIFIER_TYPE_ADMISSION_ID
        )
        .filter(AccountIdentifier.deleted_at.is_(None))
        .first()
    )
    if before is not None:
        return None

    identifier = issue_admission_identifier(
        account, student.admission_number, issued_by_user_id=actor_user_id
    )
    if identifier is not None:
        record_event(
            event_type=EVENT_IDENTIFIER_ISSUED,
            tenant_id=account.tenant_id,
            account_id=account.id,
            actor_user_id=actor_user_id,
            identifier_type=IDENTIFIER_TYPE_ADMISSION_ID,
            identifier_value=student.admission_number,
        )
    return identifier


def _live_credential(account):
    from .models import AccountCredential

    return (
        AccountCredential.query.filter_by(
            account_id=account.id, credential_type="password"
        )
        .filter(AccountCredential.deleted_at.is_(None))
        .first()
    )


def _should_force_change(tenant_id: str) -> bool:
    from .policy import student_credential_policy
    from .policy_models import CREDENTIAL_FORCE_CHANGE

    return student_credential_policy(tenant_id) == CREDENTIAL_FORCE_CHANGE


def _skipped(student, reason: str) -> Dict:
    return {
        "student_id": student.id,
        "admission_number": student.admission_number,
        "status": "skipped",
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Doing it to many students at once
# ---------------------------------------------------------------------------

def bulk_issue_credentials(
    students: Iterable, *, actor_user_id: str = None, reset: bool = False
) -> Dict:
    """Issue credentials for a set of students the caller has already scoped.

    **One child's failure does not lose the other four hundred.** Each student
    is committed in a nested transaction of their own, so a constraint
    violation on one row is reported against that row and the rest of the
    class still gets its slips.

    `reset=False` is the default and it is the safe one: a student who already
    has a working password is skipped, so running this twice does not silently
    invalidate a term's worth of credentials.
    """
    issued: List[Dict] = []
    skipped: List[Dict] = []
    failed: List[Dict] = []
    requested = 0

    for student in students:
        requested += 1
        try:
            with db.session.begin_nested():
                outcome = issue_credential(
                    student, actor_user_id=actor_user_id, reset=reset
                )
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            logger.exception(
                "credential issuance failed for student %s", student.id
            )
            failed.append(
                {
                    "student_id": student.id,
                    "admission_number": student.admission_number,
                    "error": str(exc),
                }
            )
            continue

        if outcome.get("status") == "skipped":
            skipped.append(outcome)
        else:
            issued.append(outcome)

    return {
        "requested": requested,
        # Everyone the operation actually reached. `requested` and `processed`
        # differ only if something stops the run part-way, which is exactly
        # when an operator needs to know.
        "processed": len(issued) + len(skipped) + len(failed),
        "issued": len(issued),
        "skipped": len(skipped),
        "failed": len(failed),
        # Every student is attributable. A count with no names is not a report.
        "credentials": issued,
        "skipped_students": skipped,
        "failed_students": failed,
        "counts_by_skip_reason": _tally(skipped),
    }


def backfill_admission_identifiers(
    students: Iterable, *, actor_user_id: str = None
) -> Dict:
    """Let existing students be found by their admission number.

    Phase 1b issued identifiers to students it created. This is the operation
    for everyone who was already there when the school turned the method on.

    **It never touches a password.** A student who is signing in happily today
    keeps doing so; all that changes is that their admission number now also
    finds them. Idempotent, so an operator who runs it twice — or who enables
    the method, backfills, and enables it again — gets the same answer.
    """
    from .models import AccountIdentifier

    issued: List[Dict] = []
    skipped: List[Dict] = []
    failed: List[Dict] = []
    requested = 0

    for student in students:
        requested += 1
        account = student.user if student.user_id else None
        if account is None:
            # No email, no account, nothing to attach an identifier to. Not a
            # failure — creating one would mean inventing an address.
            skipped.append(_skipped(student, SKIP_NO_ACCOUNT))
            continue

        existing = (
            AccountIdentifier.query.filter_by(
                account_id=account.id,
                identifier_type=IDENTIFIER_TYPE_ADMISSION_ID,
            )
            .filter(AccountIdentifier.deleted_at.is_(None))
            .first()
        )
        if existing is not None:
            skipped.append(_skipped(student, SKIP_ALREADY_HAD_IDENTIFIER))
            continue

        try:
            with db.session.begin_nested():
                identifier = issue_admission_identifier(
                    account,
                    student.admission_number,
                    issued_by_user_id=actor_user_id,
                )
                if identifier is None:
                    # The school has not enabled admission sign-in. Reported
                    # rather than silently done anyway.
                    skipped.append(_skipped(student, SKIP_METHOD_NOT_ENABLED))
                    continue
                record_event(
                    event_type=EVENT_IDENTIFIER_BACKFILLED,
                    tenant_id=account.tenant_id,
                    account_id=account.id,
                    actor_user_id=actor_user_id,
                    identifier_type=IDENTIFIER_TYPE_ADMISSION_ID,
                    identifier_value=student.admission_number,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("backfill failed for student %s", student.id)
            failed.append(
                {
                    "student_id": student.id,
                    "admission_number": student.admission_number,
                    "error": str(exc),
                }
            )
            continue

        issued.append(
            {
                "student_id": student.id,
                "admission_number": student.admission_number,
                "status": "issued",
            }
        )

    return {
        "requested": requested,
        "processed": len(issued) + len(skipped) + len(failed),
        "issued": len(issued),
        "skipped": len(skipped),
        "failed": len(failed),
        "issued_students": issued,
        "skipped_students": skipped,
        "failed_students": failed,
        "counts_by_skip_reason": _tally(skipped),
    }


def _tally(skipped: List[Dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for entry in skipped:
        reason = entry.get("reason") or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return counts
