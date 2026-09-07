"""Every provider client this build can execute.

A dict populated at import, not a plugin loader — the same shape the
authentication strategies use, and for the same reason: "which providers does
this build have" should be answerable by reading a file.

`validate()` runs at import and refuses to start on an incoherent registry.
That is deliberate: a provider whose key disagrees with itself, or which
claims a capability nothing defines, is a bug that should stop a deploy rather
than surface as a school's messages quietly not sending.

**Registering a provider is what makes it possible. A school's integration row
is what makes it used.** Nothing here selects anything.
"""

from __future__ import annotations

from typing import Dict, List

from .base import ProviderClient
from .capabilities import CAPABILITIES
from .providers.fake import FakeSmsProvider, FakeWhatsAppProvider
from .providers.msg91 import Msg91Provider


class RegistryInvalid(Exception):
    """The provider registry is malformed. The application must not run."""


class UnknownProvider(Exception):
    """No provider is registered under that key."""


class ProviderRegistry:
    def __init__(self, providers: List[ProviderClient]):
        self._by_key: Dict[str, ProviderClient] = {}
        for provider in providers:
            if provider.key in self._by_key:
                raise RegistryInvalid(
                    f"Two providers registered under {provider.key!r}."
                )
            self._by_key[provider.key] = provider
        self.validate()

    def validate(self) -> None:
        """Refuse to run with a registry that cannot be trusted."""
        for key, provider in self._by_key.items():
            if not key or not key.strip():
                raise RegistryInvalid("A provider has an empty key.")
            if key != provider.key:
                raise RegistryInvalid(
                    f"Provider registered as {key!r} calls itself {provider.key!r}."
                )
            if provider.capability not in CAPABILITIES:
                raise RegistryInvalid(
                    f"Provider {key!r} claims capability "
                    f"{provider.capability!r}, which nothing defines."
                )
            if not callable(getattr(provider, "health", None)):
                raise RegistryInvalid(f"Provider {key!r} cannot report its health.")
            # A provider that charges for a call and cannot be asked twice
            # safely has to say so, because the retry policy reads it.
            if provider.is_billable and provider.supports_idempotency is None:
                raise RegistryInvalid(
                    f"Provider {key!r} bills for calls but will not say whether "
                    "it supports idempotency."
                )

    def get(self, key: str) -> ProviderClient:
        """The client for that key, or a clean refusal.

        Raises rather than falling back. An unknown provider must never be a
        silent downgrade to some default — a school configured onto a vendor
        this build does not have should be told, not quietly rerouted.
        """
        try:
            return self._by_key[key]
        except KeyError:
            raise UnknownProvider(f"No provider is registered under {key!r}.") from None

    def for_capability(self, capability: str) -> List[ProviderClient]:
        """Every provider that can do this, in a stable order."""
        return sorted(
            (p for p in self._by_key.values() if p.capability == capability),
            key=lambda p: p.key,
        )

    def keys(self) -> List[str]:
        return sorted(self._by_key)

    def __contains__(self, key: str) -> bool:
        return key in self._by_key


#: The registry this build runs with.
#:
#: MSG91 is the first real vendor registered, and it is registered without a
#: commercial decision having been taken — no MSG91 account exists and no DLT
#: paperwork has been started. That is safe because registering is not the
#: same as being usable: `Msg91Provider.required_credentials` guarantees
#: `capability_health` reports it unconfigured and `set_integration_status`
#: refuses to enable it until `MSG91_AUTH_KEY` is set on the server. The
#: remaining entries are test doubles, which the resolver refuses to hand out
#: outside a test.
registry = ProviderRegistry(
    [FakeSmsProvider(), FakeWhatsAppProvider(), Msg91Provider()]
)
