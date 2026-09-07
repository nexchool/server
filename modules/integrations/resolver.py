"""Which provider carries this school's work — asked in exactly one place.

Every caller that needs a provider comes through `resolve_provider`. That is
the whole design: provider selection duplicated across modules is how two
answers to the same question come to exist, and this is a question where two
answers means a school's messages going down a wire nobody expected.

Resolution is always tenant-scoped. There is no way to call this without a
school, because resolving an integration globally would not be a leak so much
as a wrong answer — the point of the module is that two schools may use
different vendors for the same thing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from flask import current_app

from .base import ProviderClient
from .capabilities import CAPABILITIES, SELECTABLE_STATUSES
from .errors import (
    CONFIGURATION_ERROR,
    IntegrationError,
    NoIntegrationConfigured,
    UnknownCapability,
)
from .models import TenantIntegration
from .registry import UnknownProvider, registry

logger = logging.getLogger(__name__)


@dataclass
class ResolvedIntegration:
    """A provider, plus the settings this school uses it with.

    `configuration` is non-secret by construction — credentials are named in
    the integration row and fetched by the client from the environment, so
    this object can be logged without anybody having to remember to redact it.
    """

    client: ProviderClient
    integration: TenantIntegration
    configuration: dict

    @property
    def provider_key(self) -> str:
        return self.client.key


def resolve_provider(*, tenant_id: str, capability: str) -> ResolvedIntegration:
    """The provider this school uses for this capability.

    Raises rather than returning None, and the exceptions carry a normalized
    code — a caller can tell "this school has not set SMS up" from "this build
    has no such capability" without reading a message.
    """
    if capability not in CAPABILITIES:
        raise UnknownCapability(capability)

    if not tenant_id:
        # Not a technicality. A tenant-less resolution would pick somebody's
        # provider, and the one thing worse than no answer is a confident
        # wrong one.
        raise IntegrationError(
            CONFIGURATION_ERROR, "An integration cannot be resolved without a school."
        )

    integration = (
        TenantIntegration.query.filter_by(tenant_id=tenant_id, capability=capability)
        .filter(TenantIntegration.status.in_(SELECTABLE_STATUSES))
        .first()
    )
    if integration is None:
        raise NoIntegrationConfigured(capability)

    try:
        client = registry.get(integration.provider_key)
    except UnknownProvider as exc:
        # Configured onto a vendor this build does not have. A clean refusal,
        # never a silent fallback to whatever else is registered.
        raise IntegrationError(CONFIGURATION_ERROR, str(exc)) from None

    if client.is_test_double and not _test_doubles_allowed():
        raise IntegrationError(
            CONFIGURATION_ERROR,
            f"'{client.key}' is a test provider and cannot be used here.",
        )

    return ResolvedIntegration(
        client=client,
        integration=integration,
        configuration=integration.configuration or {},
    )


def _test_doubles_allowed() -> bool:
    """Whether a fake provider may run.

    Only under testing or debug. An operator who configures a school onto the
    test double by mistake gets a refusal rather than messages that go nowhere
    and are never missed.
    """
    try:
        return bool(current_app.config.get("TESTING") or current_app.config.get("DEBUG"))
    except RuntimeError:
        # No application context — a script or a worker. Assume production.
        return False


def integration_for(tenant_id: str, capability: str) -> Optional[TenantIntegration]:
    """This school's integration row whatever its status, for an operator.

    Separate from `resolve_provider` on purpose: that one answers "what should
    run", this one answers "what is configured", and a disabled integration is
    a real answer to the second question and not to the first.
    """
    return TenantIntegration.query.filter_by(
        tenant_id=tenant_id, capability=capability
    ).first()
