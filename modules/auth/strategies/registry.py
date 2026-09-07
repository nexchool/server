"""The one place that knows which authentication methods exist.

A dict populated at import, not a plugin loader: "which methods does this
build have" should be answerable by reading a file. The same shape the
notification strategies already use.

The registry checks itself (invariant A4). The check that matters is the last
one — **exactly one strategy may resolve without a tenant, and it must be the
email one.** An admission number is unique only inside a school and a
household mobile number is not unique even there, so a tenant-less lookup of
either is not a leak but a wrong answer. Asserting it here turns the most
dangerous possible regression in this programme from a code-review question
into an import-time failure.
"""

from __future__ import annotations

from typing import Dict, List

from ..identifiers import IDENTIFIER_TYPES
from .base import AuthenticationStrategy
from .email_password import EmailPasswordStrategy
from .identifier_password import IdentifierPasswordStrategy
from .mobile_otp import MobileOtpStrategy
from .mobile_pin import MobilePinStrategy


class RegistryInvalid(Exception):
    """The authentication registry is malformed. The application must not run."""


class UnknownAuthenticationMethod(Exception):
    """No strategy is registered under that key."""


class AuthenticationStrategyRegistry:
    """Every authentication method this build can execute."""

    def __init__(self, strategies: List[AuthenticationStrategy]):
        self._by_key: Dict[str, AuthenticationStrategy] = {}
        for strategy in strategies:
            if strategy.key in self._by_key:
                raise RegistryInvalid(
                    f"Two strategies registered under {strategy.key!r}."
                )
            self._by_key[strategy.key] = strategy
        self.validate()

    # -- A4 ------------------------------------------------------------------

    def validate(self) -> None:
        """Refuse to run with an incoherent registry."""
        for key, strategy in self._by_key.items():
            if not key or not key.strip():
                raise RegistryInvalid("A strategy has an empty key.")
            if key != strategy.key:
                raise RegistryInvalid(
                    f"Strategy registered as {key!r} calls itself {strategy.key!r}."
                )
            if strategy.identifier_type not in IDENTIFIER_TYPES:
                raise RegistryInvalid(
                    f"Strategy {key!r} presents identifier type "
                    f"{strategy.identifier_type!r}, which is not one of "
                    f"{list(IDENTIFIER_TYPES)}."
                )
            if strategy.credential_type is None and not hasattr(
                strategy, "issue_challenge"
            ):
                raise RegistryInvalid(
                    f"Strategy {key!r} proves nothing: it declares no credential "
                    f"type and offers no challenge."
                )
            for capability in ("resolve", "verify"):
                if not callable(getattr(strategy, capability, None)):
                    raise RegistryInvalid(
                        f"Strategy {key!r} has no {capability}()."
                    )

        tenant_less = [s.key for s in self._by_key.values() if not s.requires_tenant]
        if len(tenant_less) > 1:
            raise RegistryInvalid(
                f"More than one strategy resolves without a tenant: {tenant_less}. "
                f"Only email may, because only an email address is globally "
                f"near-unique."
            )
        for key in tenant_less:
            if self._by_key[key].identifier_type != "email":
                raise RegistryInvalid(
                    f"Strategy {key!r} resolves without a tenant but does not "
                    f"present an email identifier."
                )

    # -- lookup --------------------------------------------------------------

    def get(self, method_key: str) -> AuthenticationStrategy:
        """The strategy for this key.

        Raises rather than falling back. An unknown method must be a clean
        refusal, never a silent downgrade to email and password.
        """
        strategy = self._by_key.get(method_key)
        if strategy is None:
            raise UnknownAuthenticationMethod(method_key)
        return strategy

    def keys(self) -> List[str]:
        return sorted(self._by_key)

    def __contains__(self, method_key: str) -> bool:
        return method_key in self._by_key


#: The default authentication method, and what a request that names none gets.
#: Old clients send no `method`, and must keep working.
DEFAULT_METHOD_KEY = EmailPasswordStrategy.key

#: The registry this build runs with.
#:
#: `email_password` is the only one that may resolve without a school, and the
#: validation above refuses to start if a second ever claims that. Registering
#: a strategy is what makes a method *possible*; a tenant's policy is what
#: makes it *permitted*, and admission sign-in, mobile OTP and mobile PIN are
#: all off until a school turns them on.
registry = AuthenticationStrategyRegistry(
    [
        EmailPasswordStrategy(),
        IdentifierPasswordStrategy(),
        MobileOtpStrategy(),
        MobilePinStrategy(),
    ]
)
