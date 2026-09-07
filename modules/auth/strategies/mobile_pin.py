"""A mobile number and a PIN — the student's way in from a phone.

Sits between the two methods that came before it. Like `mobile_otp` it is
found by a mobile number; like `admission_id_password` it is proved by a
stored secret. What is new is that the secret is *short*, and that changes
where the security lives.

**The PIN is not what protects the account. The attempt limit is.** Six digits
is a million values — a number an offline attacker exhausts in seconds and an
online one never reaches, provided the online path counts every guess. So this
strategy consults `pin_throttle` before it compares anything, and records
every failure, and both of those happen here rather than in the pipeline for a
reason worth stating: the pipeline's failure counter is keyed on an account,
and an enumeration-resistant login has to count guesses made against numbers
that resolve to no account at all. Otherwise guessing at a number nobody holds
is free, and free-versus-throttled is itself the answer to "is this number a
customer here".

**Students only.** The product asked for a PIN for children signing in on a
phone, not a second password for staff. Two independent things enforce that:
a school's policy, which grants methods per subject kind, and this strategy,
which will not resolve an account whose person is not a student of the school.
Either alone would do; both, because one of them being wrong should not be
enough.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from core.database import db

from ..identifiers import IDENTIFIER_TYPE_MOBILE, normalize_mobile
from .base import AccountMatch, AuthenticationStrategy, ThrottledOut

logger = logging.getLogger(__name__)


class MobilePinStrategy(AuthenticationStrategy):
    """Resolve an account by mobile number, prove it by the PIN it holds."""

    key = "mobile_pin"
    identifier_type = IDENTIFIER_TYPE_MOBILE
    #: A real stored credential, unlike the OTP's challenge. Its own type, so
    #: an account may hold a password and a PIN at once and neither is the
    #: other.
    credential_type = "pin"
    #: A number is unique inside one school at best. Resolving one without a
    #: school would not be a leak so much as a wrong answer.
    requires_tenant = True
    #: A mobile number is not a secret — it is on the admission form and known
    #: to every classmate — so wrong PINs must not be able to spend the
    #: account's shared lockout budget and shut the owner out of the password
    #: they actually use. `pin_throttle` holds the line for this method, and
    #: holds it on the number rather than on the account.
    counts_toward_account_lockout = False
    #: Nothing is sent. A PIN sign-in costs nothing and touches no provider.
    is_paid = False

    def resolve(self, value: str, tenant_id: Optional[str]) -> List[AccountMatch]:
        """The student account this school issued that number to.

        The same tenant-scoped mobile lookup `mobile_otp` does, narrowed to
        students. Narrowing here rather than after verification is deliberate:
        for a student-only method, a staff account is not a match that fails
        the gates — it is not a match.
        """
        from core.models import TENANT_STATUS_ACTIVE, Tenant

        from ..models import AccountIdentifier, User
        from ..policy_models import SUBJECT_STUDENT

        if not tenant_id:
            return []

        normalized = normalize_mobile(value)
        if not normalized:
            return []

        rows = (
            db.session.query(User, AccountIdentifier)
            .join(AccountIdentifier, AccountIdentifier.account_id == User.id)
            .filter(
                # Leading on tenant_id, and never optional — the
                # `idx_account_identifiers_lookup` index in its built order.
                AccountIdentifier.tenant_id == tenant_id,
                AccountIdentifier.identifier_type == self.identifier_type,
                AccountIdentifier.identifier_value_normalized == normalized,
                AccountIdentifier.deleted_at.is_(None),
                User.tenant_id == tenant_id,
                User.deleted_at.is_(None),
            )
            # Deterministic, so the plural case is at least stable while
            # somebody looks at it. It is refused, never chosen from.
            .order_by(User.id)
            .all()
        )

        from ..policy import subject_kinds

        matches: List[AccountMatch] = []
        for account, identifier in rows:
            tenant = db.session.get(Tenant, account.tenant_id)
            if tenant is None or tenant.status != TENANT_STATUS_ACTIVE:
                continue
            # Asked of the identity layer rather than recomputed here: "what is
            # this person to us" already has an owner, and a person may be both
            # a student and staff, so this tests membership rather than
            # equality.
            if SUBJECT_STUDENT not in subject_kinds(account):
                continue
            matches.append(
                AccountMatch(account=account, tenant=tenant, identifier=identifier)
            )
        return matches

    def verify(self, match: AccountMatch, proof: str, context: Optional[dict] = None) -> bool:
        """The PIN, against the credential — after asking whether we may try.

        The throttle is consulted before the comparison and a failure is
        recorded after it, so a blocked attacker learns nothing from timing
        and a correct PIN clears the count against that number.
        """
        from werkzeug.security import check_password_hash

        from ..otp_throttle import hash_value
        from ..pin_throttle import check_attempt_allowed, clear_failures, record_failure
        from ..provisioning import live_pin_credential

        if not proof:
            return False

        identifier = match.identifier
        mobile = identifier.identifier_value_normalized if identifier else None
        if not mobile:
            return False

        tenant_id = match.account.tenant_id
        mobile_hash = hash_value(mobile)
        ip_address = _caller_ip()

        decision = check_attempt_allowed(
            tenant_id=tenant_id, mobile_hash=mobile_hash, ip_address=ip_address
        )
        if not decision.allowed:
            # Refused before the PIN is compared. Raised rather than returned
            # false so the pipeline can tell "we declined to look" from "the
            # PIN was wrong" — the caller still sees one coarse answer, but
            # only the second counts against the account's own lockout.
            logger.warning(
                "PIN attempt refused by the limiter (tenant=%s reason=%s)",
                tenant_id,
                decision.reason,
            )
            raise ThrottledOut(decision.reason or "throttled")

        credential = live_pin_credential(match.account)
        if credential is None:
            # No PIN issued. Counted, because otherwise an attacker learns
            # which numbers have one from how many guesses they are allowed.
            record_failure(
                tenant_id=tenant_id, mobile_hash=mobile_hash, ip_address=ip_address
            )
            return False

        if not check_password_hash(credential.secret_hash, proof):
            record_failure(
                tenant_id=tenant_id, mobile_hash=mobile_hash, ip_address=ip_address
            )
            return False

        clear_failures(tenant_id=tenant_id, mobile_hash=mobile_hash)
        return True


def _caller_ip() -> Optional[str]:
    """The address this attempt came from, when there is a request to ask.

    None outside a request — a script or a test driving the pipeline directly
    — in which case the per-address limit simply does not apply and the
    per-number and per-school ones still do.
    """
    try:
        from flask import request

        return request.remote_addr
    except Exception:  # noqa: BLE001
        return None
