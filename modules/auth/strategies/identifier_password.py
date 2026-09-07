"""A school-issued identifier and a password — the student's way in.

Everything that distinguishes this from `email_password` follows from one
fact: **an admission number is unique inside one school and nowhere else.**
Two schools will both have a ``10042``, and neither is wrong.

So `requires_tenant = True`, and the pipeline refuses the attempt before any
lookup happens when no school has been named. That is not a leak being avoided
— a tenant-less lookup would simply return *a* student, possibly a different
child at a different school, which is worse than returning none. The registry
asserts at import time that only the email strategy may resolve without a
tenant, so this cannot quietly acquire the exception.

Everything else is deliberately identical to the email strategy: the pipeline
owns maintenance, policy, lockout, account status, disambiguation, events and
finalization, and this class answers only *which account* and *is this the
password*.
"""

from __future__ import annotations

from typing import List, Optional

from core.database import db

from ..identifiers import IDENTIFIER_TYPE_ADMISSION_ID, normalize_identifier
from .base import AccountMatch, AuthenticationStrategy


class IdentifierPasswordStrategy(AuthenticationStrategy):
    """Resolve an account by a school-issued identifier, prove it by password."""

    key = "admission_id_password"
    identifier_type = IDENTIFIER_TYPE_ADMISSION_ID
    credential_type = "password"
    #: The point of the whole class. See the module docstring.
    requires_tenant = True
    is_paid = False

    def resolve(self, value: str, tenant_id: Optional[str]) -> List[AccountMatch]:
        """The account this school issued that number to.

        Refuses to look at all without a school. The pipeline has already
        enforced `requires_tenant`, so reaching here without one would be a
        bug — and it is answered with no matches rather than a global search,
        so a bug upstream cannot become a cross-tenant lookup down here.
        """
        from core.models import TENANT_STATUS_ACTIVE, Tenant

        from ..models import AccountIdentifier, User

        if not tenant_id:
            return []

        normalized = normalize_identifier(self.identifier_type, value)
        if not normalized:
            return []

        rows = (
            db.session.query(User, AccountIdentifier)
            .join(AccountIdentifier, AccountIdentifier.account_id == User.id)
            .filter(
                # Leading on tenant_id, and never optional. This is the
                # `idx_account_identifiers_lookup` index, in the order it was
                # built for.
                AccountIdentifier.tenant_id == tenant_id,
                AccountIdentifier.identifier_type == self.identifier_type,
                AccountIdentifier.identifier_value_normalized == normalized,
                AccountIdentifier.deleted_at.is_(None),
                User.tenant_id == tenant_id,
                User.deleted_at.is_(None),
            )
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

    def verify(self, match: AccountMatch, proof: str, context=None) -> bool:
        """The password, against the credential row or the legacy column.

        The same dual read the email strategy does, and for the same reason:
        during this window both hold the secret and either may be the one an
        account has.
        """
        from ..models import AccountCredential

        if not proof:
            return False

        credential = (
            AccountCredential.query.filter_by(
                account_id=match.account.id, credential_type=self.credential_type
            )
            .filter(AccountCredential.deleted_at.is_(None))
            .first()
        )
        if credential is not None:
            from werkzeug.security import check_password_hash

            return check_password_hash(credential.secret_hash, proof)

        return match.account.check_password(proof)
