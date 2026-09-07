"""The contract a provider client implements.

Metadata is declared as class attributes, the same way authentication
strategies declare theirs, so the registry can check a provider's shape
without instantiating it and so what a provider promises is auditable by
reading the class rather than by tracing a call.

Two of those attributes are load-bearing rather than descriptive:

`supports_idempotency` is what decides whether a timed-out send may be
retried. A provider that honours an idempotency key can be asked twice and
will send once; a provider that cannot must never be retried after a timeout,
because the first request may well have gone through and the school would pay
for two messages. The retry policy reads this attribute rather than guessing.

`is_billable` is what decides whether a successful call reaches the usage
ledger. It exists so a free metadata call and a paid send can share a client.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .capabilities import CAPABILITY_SMS
from .results import ProviderHealth, SmsSendResult


class ProviderClient(ABC):
    """How NexSchool actually calls one external service.

    Not to be confused with Phase 2's `ServiceProvider`, which is the same
    vendor's *commercial* record — what it sells and what it costs. That model
    holds no endpoint, no key and no retry policy, and this class holds no
    price. They share a vendor identity (`key`) and nothing else.
    """

    #: Matches `service_providers.key` in the billing catalog, so an operator
    #: reading a bill and an operator reading a log see the same name.
    key: str = ""
    #: What this client can do — one of `capabilities.CAPABILITIES`.
    capability: str = ""
    #: Human name for a platform screen.
    name: str = ""
    #: Whether the provider honours an idempotency key on a send. Read by the
    #: retry policy; see this module's docstring.
    supports_idempotency: bool = False
    #: True when using this costs money and a success belongs in the ledger.
    is_billable: bool = True
    #: True only for clients that must never run outside a test.
    is_test_double: bool = False

    #: Environment variable names this provider needs. The values are never
    #: stored, never returned and never logged — only their absence is
    #: reported, by `health()`. See `credentials.py`.
    required_credentials: tuple = ()

    @abstractmethod
    def health(self, configuration: dict) -> ProviderHealth:
        """Whether this looks usable, **without spending anything**.

        A health check must not send a message. Finding out whether an SMS
        integration works by sending an SMS charges the school and bothers
        whoever owns the number; if the provider has a free metadata or
        authentication endpoint, use that, and otherwise report configuration
        readiness and say plainly that delivery was not verified.
        """


class SmsProvider(ProviderClient):
    """A provider that can send a short message to a phone."""

    capability: str = CAPABILITY_SMS

    @abstractmethod
    def send(
        self,
        *,
        destination: str,
        message: str,
        configuration: dict,
        idempotency_key: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> SmsSendResult:
        """Ask the provider to send one message.

        Returns a result rather than raising, including on failure: "the
        message did not send" is an outcome the caller has to handle, not a
        surprise. Only a programming error escapes as an exception.

        `configuration` is the school's non-secret settings — a sender id, a
        route. Credentials are **not** in it; the client fetches those itself
        from the environment, so a configuration blob can be logged or
        returned by an API without anybody having to remember to redact it.
        """
