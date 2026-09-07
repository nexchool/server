"""What an authentication method has to answer, and nothing more.

A strategy answers two questions:

    resolve()  which accounts could this identifier mean?
    verify()   is this proof valid?

It does **not** decide whether the school is in maintenance, whether the
account is locked, whether the tenant's policy permits the method, whether the
account is suspended, or whether the attempt should be audited. Those are the
pipeline's, and they are the pipeline's for a reason this codebase has already
learned once: when two login branches each owned the failed-attempt counter,
one of them stopped counting, and omitting a field from the request body
bought unlimited guesses. `record_failed_login`'s docstring is the record of
that. A gate that lives in one place cannot be forgotten by the second
implementation of anything.

So a new method is a class with two methods and a row in the registry — never
another branch past another copy of the gates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..policy_models import SUBJECT_KINDS


class ThrottledOut(Exception):
    """This attempt was refused before the proof was even compared.

    Raised by a strategy whose own limiter declined, and caught by the
    pipeline, which then refuses *without* counting a credential failure.

    The distinction matters because the two limiters guard different things. A
    strategy's limiter is keyed on the identifier — it exists to protect a
    low-entropy secret from being ground down, and it must count guesses made
    against identifiers that resolve to no account at all. The pipeline's is
    keyed on the account, and it locks that account out of *every* method. If
    a refusal by the first fed the second, anybody who knew a student's mobile
    number could lock them out of their email password too, indefinitely, by
    spending attempts they were never allowed to make.
    """


@dataclass(frozen=True)
class AccountMatch:
    """One account an identifier could mean, and how it was found.

    `identifier` is the row that resolved it, or None when the account was
    found through the legacy `users.email` column during the dual-read window.
    The session records it so support can answer which address was used.
    """

    account: object
    tenant: object = None
    identifier: object = None


class AuthenticationStrategy(ABC):
    """One way of proving an account.

    Subclasses declare their metadata as class attributes so the registry can
    check the shape of a method without instantiating anything, and so
    `requires_tenant` — the property that keeps a tenant-scoped identifier from
    being looked up across schools — is auditable by reading the class rather
    than by tracing a call.
    """

    #: Written to `sessions.login_method` and to the `amr` token claim.
    key: str = ""
    #: Which `account_identifiers.identifier_type` this method presents.
    identifier_type: str = ""
    #: What proves it: a stored credential type, or None for a challenge.
    credential_type: Optional[str] = None
    #: False only for `email`, which is globally near-unique and is the reason
    #: one mobile app can serve every school. Every other identifier is unique
    #: per tenant at best, so resolving one without a school is not a leak but
    #: a wrong answer.
    requires_tenant: bool = True
    #: True when an attempt costs money. Nothing does yet.
    is_paid: bool = False
    #: Whether a wrong proof spends the *account's* shared lockout budget.
    #:
    #: False for any method that brings its own online limiter. The account
    #: lock is one counter shared by every way into an account, so a method
    #: whose identifier is semi-public — a mobile number is printed on forms
    #: and known to every classmate — must not be able to spend it: otherwise
    #: knowing a child's number is enough to lock their parent out of the
    #: password they actually use. Such a method is not left unprotected; it
    #: is protected by a limiter keyed on its own identifier, which also
    #: covers the numbers that resolve to no account at all (see
    #: `pin_throttle`). A lock earned elsewhere still applies here — this
    #: governs only what *earns* one.
    counts_toward_account_lockout: bool = True
    #: Which `SUBJECT_KINDS` this method can ever resolve an account for.
    #:
    #: Defaults to every kind, because most methods have no such limit. A
    #: method that does — `mobile_pin` is the first — has to be able to say
    #: so *here*, declaratively, rather than leave an operator to discover it
    #: from a login that quietly never works. Before this attribute existed
    #: that was exactly what happened: the panel offered every method under
    #: every subject kind because nothing recorded the restriction anywhere
    #: it could be read, so switching Mobile PIN on for Staff produced a
    #: success toast and a method nobody staff could ever use. `set_method`
    #: (`modules/auth/policy.py`) reads this to refuse that pairing before it
    #: is written, the same way it already refuses a paid method with no
    #: working channel — the API is reachable without the panel, so the
    #: refusal has to live here, not only in a UI that happens to check.
    subject_kinds: Tuple[str, ...] = SUBJECT_KINDS

    @abstractmethod
    def resolve(self, value: str, tenant_id: Optional[str]) -> List[AccountMatch]:
        """Every account this identifier could mean. Never raises for a miss."""

    @abstractmethod
    def verify(self, match: AccountMatch, proof: str, context: Optional[dict] = None) -> bool:
        """Whether this proof belongs to that account.

        `context` carries what a method needs from the request beyond the
        proof itself, and exists because a challenge is not a stored secret: a
        password is checked against a column, while a code is checked against
        one particular live challenge that the caller may name. Optional and
        ignored by every credential-based method, so adding it did not change
        what a password strategy does or has to know.
        """
