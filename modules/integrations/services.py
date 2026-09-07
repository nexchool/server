"""Configuring which provider carries a school's work.

Platform-administrator operations. A school does not choose its own vendor for
the same reason it does not set its own price: which company NexSchool buys
from, and on what terms, is NexSchool's commercial decision.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from core.database import db
from core.school_time import utc_now

from .capabilities import (
    CAPABILITIES,
    CAPABILITY_LABELS,
    STATUS_DISABLED,
    STATUS_ENABLED,
    STATUSES,
)
from .credentials import is_valid_reference
from .health import capability_health
from .models import TenantIntegration
from .registry import registry


class IntegrationConfigurationError(Exception):
    """The integration was asked for something that does not make sense."""


def describe_capabilities() -> List[Dict]:
    """What this build can do, and who could do it.

    Reads the registry rather than the database: this is a property of the
    deployed code, not of anybody's configuration.
    """
    return [
        {
            "capability": capability,
            "label": CAPABILITY_LABELS.get(capability, capability),
            "providers": [
                {
                    "key": provider.key,
                    "name": provider.name or provider.key,
                    "supports_idempotency": provider.supports_idempotency,
                    "is_billable": provider.is_billable,
                    "is_test_double": provider.is_test_double,
                    # The *names* of what it needs. Never a value; see
                    # `credentials.py`.
                    "required_credentials": list(provider.required_credentials),
                }
                for provider in registry.for_capability(capability)
            ],
        }
        for capability in CAPABILITIES
    ]


def describe_tenant_integrations(tenant_id: str) -> List[Dict]:
    """Every integration this school has, whatever its status, with health."""
    integrations = (
        TenantIntegration.query.filter_by(tenant_id=tenant_id)
        .order_by(TenantIntegration.capability)
        .all()
    )

    described = []
    for integration in integrations:
        report = capability_health(
            tenant_id=tenant_id, capability=integration.capability
        )
        described.append(
            {
                **integration.to_dict(),
                "health": {
                    "ready": report.ready,
                    "configured": report.configured,
                    "credentials_present": report.credentials_present,
                    "provider_supported": report.provider_supported,
                    "provider_reachable": report.provider_reachable,
                    "detail": report.detail,
                    "checks": report.checks,
                },
            }
        )
    return described


def configure_integration(
    tenant_id: str,
    *,
    capability: str,
    provider_key: str,
    configuration: Optional[dict] = None,
    credential_references: Optional[dict] = None,
    actor_user_id: Optional[str] = None,
) -> TenantIntegration:
    """Point a school's capability at a provider.

    **Never enables it.** A newly configured integration starts disabled, so
    adding a row cannot start carrying traffic — somebody enables it
    deliberately, after looking at its health. Re-configuring an already
    enabled integration leaves it enabled; changing a vendor is not a reason
    to take a school's SMS offline.
    """
    if capability not in CAPABILITIES:
        raise IntegrationConfigurationError(
            f"'{capability}' is not a capability this build has. Expected one of: "
            + ", ".join(CAPABILITIES)
        )
    if provider_key not in registry:
        raise IntegrationConfigurationError(
            f"No provider is registered under '{provider_key}'."
        )

    client = registry.get(provider_key)
    if client.capability != capability:
        raise IntegrationConfigurationError(
            f"'{provider_key}' provides {client.capability}, not {capability}."
        )

    references = credential_references or {}
    for purpose, reference in references.items():
        # A reference is the *name* of an environment variable. Refusing
        # anything else is what stops somebody pasting an API key into the
        # field that was built so keys would never be stored.
        if not is_valid_reference(reference):
            raise IntegrationConfigurationError(
                f"'{purpose}' must name an environment variable "
                "(uppercase letters, digits and underscores) — not a value."
            )

    integration = TenantIntegration.query.filter_by(
        tenant_id=tenant_id, capability=capability
    ).first()
    if integration is None:
        integration = TenantIntegration(
            tenant_id=tenant_id, capability=capability, status=STATUS_DISABLED
        )
        db.session.add(integration)

    integration.provider_key = provider_key
    integration.configuration = configuration or {}
    integration.credential_references = references
    integration.status_detail = None
    db.session.flush()
    return integration


def set_integration_status(
    tenant_id: str,
    *,
    capability: str,
    status: str,
    actor_user_id: Optional[str] = None,
) -> TenantIntegration:
    """Turn a school's integration on or off.

    Disabling is not deleting. The configuration stays, the usage history
    stays, and the billing records stay valid — a school that pauses SMS over
    the summer has not lost its settings, and last term's messages still have
    to be explicable.
    """
    if status not in STATUSES:
        raise IntegrationConfigurationError(
            f"'{status}' is not a status. Expected one of: " + ", ".join(STATUSES)
        )

    integration = TenantIntegration.query.filter_by(
        tenant_id=tenant_id, capability=capability
    ).first()
    if integration is None:
        raise IntegrationConfigurationError(
            f"This school has no {capability} integration to enable."
        )

    if status == STATUS_ENABLED:
        report = capability_health(tenant_id=tenant_id, capability=capability)
        if not report.provider_supported:
            raise IntegrationConfigurationError(
                "This build has no client for that provider."
            )
        if not report.credentials_present:
            # Enabling something that cannot possibly work produces a school
            # whose messages fail silently. Refused, with the reason.
            raise IntegrationConfigurationError(
                "The credentials this provider needs are not set on this server."
            )
        integration.enabled_by_user_id = actor_user_id
        integration.enabled_at = utc_now()

    integration.status = status
    integration.last_checked_at = utc_now()
    db.session.flush()
    return integration
