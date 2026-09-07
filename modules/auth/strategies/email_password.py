"""Email address and password — the method the product has always had.

Two things about it are unusual and both are deliberate.

**It is the one method allowed to resolve without a school.** One mobile
application serves every school, so a person who has only typed an address and
a password has not yet said which school they mean. The lookup therefore spans
tenants and, when more than one account matches, the caller is asked to
choose. An email address is globally near-unique, which is what makes that
safe. An admission number is unique only inside one school and a household
mobile number is not unique even there, so **no other strategy may inherit
this**: they declare `requires_tenant = True`, and a registry self-test
asserts that exactly one strategy does not.

**It reads the new tables first and the old columns second.** During this
window `account_identifiers` and `account_credentials` are kept in step with
`users.email` and `users.password_hash` but are not yet the only truth, so a
miss in either falls back rather than failing. That is what makes the phase
reversible: turning the pipeline off returns to a path that was never stopped
being fed.
"""

from __future__ import annotations

from typing import List, Optional

from core.database import db

from ..identifiers import IDENTIFIER_TYPE_EMAIL, normalize_email
from .base import AccountMatch, AuthenticationStrategy


class EmailPasswordStrategy(AuthenticationStrategy):
    key = "email_password"
    identifier_type = IDENTIFIER_TYPE_EMAIL
    credential_type = "password"
    #: See the module docstring. This is the exception, not the pattern.
    requires_tenant = False
    is_paid = False

    def resolve(self, value: str, tenant_id: Optional[str]) -> List[AccountMatch]:
        """Accounts holding this address, in this school or in any of them."""
        from core.models import TENANT_STATUS_ACTIVE, Tenant
        from modules.auth.models import AccountIdentifier, User

        normalized = normalize_email(value)
        if not normalized:
            return []

        accounts = self._by_identifier(normalized, tenant_id)
        if accounts:
            return self._as_matches(accounts, tenant_id, Tenant, TENANT_STATUS_ACTIVE)

        # Dual-read fallback. An account whose identifier row is missing —
        # created before the backfill, or by a path that bypassed the ORM —
        # must still be able to sign in.
        legacy = self._by_legacy_column(normalized, tenant_id, User)
        return self._as_matches(legacy, tenant_id, Tenant, TENANT_STATUS_ACTIVE)

    def _by_identifier(self, normalized: str, tenant_id: Optional[str]):
        """(account, identifier) pairs from `account_identifiers`."""
        from modules.auth.models import AccountIdentifier, User

        query = (
            db.session.query(User, AccountIdentifier)
            .join(AccountIdentifier, AccountIdentifier.account_id == User.id)
            .filter(
                AccountIdentifier.identifier_type == IDENTIFIER_TYPE_EMAIL,
                AccountIdentifier.identifier_value_normalized == normalized,
                AccountIdentifier.deleted_at.is_(None),
                User.deleted_at.is_(None),
            )
        )
        if tenant_id:
            query = query.filter(User.tenant_id == tenant_id)
        return [(account, identifier) for account, identifier in query.all()]

    def _by_legacy_column(self, normalized: str, tenant_id: Optional[str], User):
        """(account, None) pairs from `users.email`.

        Compared case-insensitively against the same normalized value the
        identifier table uses, so the two paths answer alike. The legacy
        constraint is case-sensitive, but the addresses it holds were audited
        before the backfill and no tenant holds two differing only by case.
        """
        query = User.query.filter(
            db.func.lower(db.func.btrim(User.email)) == normalized,
            User.deleted_at.is_(None),
        )
        if tenant_id:
            query = query.filter(User.tenant_id == tenant_id)
        return [(account, None) for account in query.all()]

    def _as_matches(self, pairs, tenant_id, Tenant, active_status) -> List[AccountMatch]:
        """Attach each account's school, keeping only the live ones.

        A suspended school blocks sign-in for everybody, so an account inside
        one is not a candidate — which is also what the legacy cross-tenant
        search did.
        """
        matches: List[AccountMatch] = []
        for account, identifier in pairs:
            tenant = db.session.get(Tenant, account.tenant_id)
            if tenant is None or tenant.status != active_status:
                continue
            matches.append(
                AccountMatch(account=account, tenant=tenant, identifier=identifier)
            )
        return matches

    def verify(self, match: AccountMatch, proof: str, context=None) -> bool:
        """The password, against the credential row or the legacy column."""
        from modules.auth.models import AccountCredential

        if not proof:
            return False

        credential = (
            AccountCredential.query.filter_by(
                account_id=match.account.id,
                credential_type=self.credential_type,
            )
            .filter(AccountCredential.deleted_at.is_(None))
            .first()
        )
        if credential is not None:
            from werkzeug.security import check_password_hash

            return check_password_hash(credential.secret_hash, proof)

        # Dual-read fallback: the account has no credential row yet.
        return match.account.check_password(proof)
