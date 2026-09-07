"""A mobile number and a code sent to it — the first method with no stored secret.

Everything that distinguishes this from the password strategies follows from
one fact: **there is nothing on the account to check the proof against.** A
password is a credential the account keeps; an OTP is a factor that exists for
five minutes and is destroyed when it is used. So this strategy declares
`credential_type = None` and offers `issue_challenge` instead — a shape the
registry has required since Phase 0d, which refuses to start a strategy that
"proves nothing: it declares no credential type and offers no challenge."

It is also the first method that **costs money to attempt**, which is why
`is_paid` exists on the base class and why the pipeline evaluates policy
before the proof: a method a school has switched off must not be able to spend
that school's money.

Everything else is deliberately identical to the other strategies. The
pipeline owns maintenance, policy, lockout, account status, disambiguation,
events and finalization; this class answers only *which account* and *is this
the code*.
"""

from __future__ import annotations

from typing import List, Optional

from core.database import db

from ..identifiers import IDENTIFIER_TYPE_MOBILE, normalize_mobile
from .base import AccountMatch, AuthenticationStrategy


class MobileOtpStrategy(AuthenticationStrategy):
    """Resolve an account by mobile number, prove it by a code sent to it."""

    key = "mobile_otp"
    identifier_type = IDENTIFIER_TYPE_MOBILE
    #: Nothing is stored to check against. The registry requires a challenge
    #: instead, and `issue_challenge` below is it.
    credential_type = None
    #: A number is unique inside one school at best — and a household number
    #: may not even be unique there. Resolving one without a school would not
    #: be a leak so much as a wrong answer.
    requires_tenant = True
    #: Same reasoning as the PIN's: the identifier is semi-public, so a wrong
    #: code must not lock the account out of every other method. `otp_throttle`
    #: bounds this one, keyed on the number.
    counts_toward_account_lockout = False
    #: The first method where an attempt sends an SMS somebody pays for.
    is_paid = True

    def resolve(self, value: str, tenant_id: Optional[str]) -> List[AccountMatch]:
        """The account this school issued that number to.

        Refuses to look at all without a school, and answers a missing tenant
        with no matches rather than a global search — so a bug upstream cannot
        become a cross-tenant lookup down here.
        """
        from core.models import TENANT_STATUS_ACTIVE, Tenant

        from ..models import AccountIdentifier, User

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
                # `idx_account_identifiers_lookup` index in the order it was
                # built for.
                AccountIdentifier.tenant_id == tenant_id,
                AccountIdentifier.identifier_type == self.identifier_type,
                AccountIdentifier.identifier_value_normalized == normalized,
                AccountIdentifier.deleted_at.is_(None),
                User.tenant_id == tenant_id,
                User.deleted_at.is_(None),
            )
            # Ordered so that the plural case is at least deterministic while
            # somebody looks at it. It is refused, not chosen from.
            .order_by(User.id)
            .all()
        )

        matches: List[AccountMatch] = []
        for account, identifier in rows:
            tenant = db.session.get(Tenant, account.tenant_id)
            if tenant is None or tenant.status != TENANT_STATUS_ACTIVE:
                continue
            matches.append(
                AccountMatch(account=account, tenant=tenant, identifier=identifier)
            )
        return matches

    def verify(self, match: AccountMatch, proof: str, context: Optional[dict] = None) -> bool:
        """The code, against the live challenge for this account and number.

        Spending the code is what verification *is* here — there is no
        idempotent "check" separate from "consume", because a code that could
        be checked twice could be used twice. `verify_code` does both in one
        conditional UPDATE.

        `context` may name a challenge, which is then required to be the one
        that matches. It is optional because the number and the account
        already identify a single live challenge; naming it is a belt on top
        of the braces, and a wrong name is refused rather than ignored.
        """
        from ..otp import verify_code

        if not proof:
            return False

        identifier = match.identifier
        mobile = identifier.identifier_value_normalized if identifier else None
        if not mobile:
            return False

        result = verify_code(
            tenant_id=match.account.tenant_id,
            mobile=mobile,
            code=proof,
            account_id=match.account.id,
            challenge_id=(context or {}).get("challenge_id"),
        )
        return result.verified

    def issue_challenge(
        self,
        *,
        tenant_id: str,
        identifier: str,
        ip_address: Optional[str] = None,
        client_surface: Optional[str] = None,
    ):
        """Send a code to that number.

        The hook the registry has required of a credential-less strategy since
        Phase 0d. It is thin on purpose: the work is `otp.request_otp`, which
        owns throttling, ambiguity and delivery, and the SMS itself is Phase
        3's — no vendor name, no HTTP call and no price appears anywhere in
        this module.
        """
        from ..otp import request_otp

        return request_otp(
            tenant_id=tenant_id,
            mobile=identifier,
            ip_address=ip_address,
            client_surface=client_surface,
        )
