"""Is this school's integration usable? Asked without spending anything.

The temptation with a "test connection" button is to prove it works by doing
the thing — send a message, see if it arrives. For SMS that charges the school
for every press and rings a real person's phone, so this does not do it.

What it can answer honestly:

    configuration present     is there a row, is it enabled
    provider supported        does this build have a client for that vendor
    credentials present       are the named environment variables actually set
    provider reachable        only when the vendor has a free, non-sending check

The last one is usually absent, and the report says so rather than implying
that delivery was verified.
"""

from __future__ import annotations

from .capabilities import STATUS_DISABLED
from .credentials import credentials_present
from .registry import UnknownProvider, registry
from .resolver import integration_for
from .results import ProviderHealth


def capability_health(*, tenant_id: str, capability: str) -> ProviderHealth:
    """A readiness report for one school and one capability."""
    integration = integration_for(tenant_id, capability)

    if integration is None:
        return ProviderHealth(
            configured=False,
            credentials_present=False,
            provider_supported=False,
            detail=f"No {capability} provider is configured for this school.",
            checks={"integration_row": False},
        )

    try:
        client = registry.get(integration.provider_key)
    except UnknownProvider:
        return ProviderHealth(
            configured=True,
            credentials_present=False,
            provider_supported=False,
            detail=(
                f"This school is configured to use '{integration.provider_key}', "
                "which this build has no client for."
            ),
            checks={"integration_row": True, "provider_supported": False},
        )

    has_credentials = credentials_present(integration.credential_references or {})

    # The provider's own check, which by contract never sends anything.
    report = client.health(integration.configuration or {})
    report.configured = integration.status != STATUS_DISABLED
    report.credentials_present = has_credentials and report.credentials_present
    report.provider_supported = True
    report.checks = {
        "integration_row": True,
        "enabled": integration.status != STATUS_DISABLED,
        "provider_supported": True,
        "credentials_present": has_credentials,
    }

    if report.provider_reachable is None:
        report.detail = (
            (report.detail + " ") if report.detail else ""
        ) + "Delivery was not verified — checking that would cost a message."

    return report
