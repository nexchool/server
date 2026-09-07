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

    # Whose name decides "credentials present"? Not the tenant's stored
    # `credential_references` — that used to be the whole answer, and it was
    # the wrong question. `providers/msg91.py` and `providers/meta_whatsapp.py`
    # each call `resolve_secret` against a fixed name baked into the client
    # (`AUTH_KEY_REFERENCE`, `ACCESS_TOKEN_REFERENCE`); neither one ever reads
    # a school's row. So a stored reference that happens to resolve proves
    # nothing about the name a send will actually look up, and a stored
    # reference that is blank or stale proves nothing either, since nothing
    # downstream would have consulted it anyway.
    #
    # There is also no live case left where a stored reference *should* mean
    # something: since Phase 2/9's commercial model, NexSchool owns one
    # vendor account per capability, with its secret set once on the server —
    # not a secret a school brings, and not one a per-tenant reference could
    # name today. Weighing the stored value in here regardless — ANDed, so it
    # could only ever turn a working integration falsely unready, or ORed, so
    # it could only ever turn a broken one falsely ready — has no direction
    # that helps and one that reproduces the exact bug this closes. So it is
    # not consulted for readiness at all. `credential_references` keeps its
    # column, its format validation in `configure_integration`, and its own
    # place in `to_dict()`, where an operator can already see what name a
    # school's row carries and whether *that* resolves, next to this report
    # of whether the provider's own required name does — the seam stays open
    # for a genuine per-tenant secret; it is just not this function's fact.
    #
    # `client.required_credentials` is the one list every provider commits to
    # needing — the same tuple `describe_capabilities` already publishes as
    # "what this provider needs" and `msg91.py` / `meta_whatsapp.py` already
    # resolve from in `send()`. Using it here too is not a second source of
    # truth; it is the existing one, finally consulted by the function whose
    # job is to say whether a send will work.
    has_credentials = credentials_present(
        {name: name for name in client.required_credentials}
    )

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
