"""Per-request GraphQL context.

GraphQL is a single endpoint serving both public operations (login) and
protected ones, so the transport resolves tenant and identity *permissively*:
it records what it found and never rejects the request itself. Fields decide
what they require — a public mutation tolerates an anonymous caller, a
tenant-scoped field does not.

Tenant is resolved before authentication because identity checks compare the
user's tenant against the request's (see ``core.authentication``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

from flask import g

from core.authentication import authenticate_request
from core.tenant import find_tenant


@dataclass
class GraphQLContext:
    """What every resolver knows about the caller.

    ``tenant_error`` / ``authentication_error`` explain *why* something is
    missing, so a field requiring it can raise a precise error instead of a
    generic "unauthorized".
    """

    tenant: Optional[Any] = None
    tenant_id: Optional[str] = None
    tenant_error: Optional[str] = None
    current_user: Optional[Any] = None
    authentication_error: Optional[str] = None
    new_access_token: Optional[str] = None
    # Batched reads for this request only. A loader caches what it has
    # already fetched, so sharing one across requests would serve one
    # tenant's rows to another.
    loaders: Optional[Any] = None

    @property
    def is_authenticated(self) -> bool:
        return self.current_user is not None


def _resolve_tenant() -> Tuple[Optional[Any], Optional[str]]:
    """Resolve the request's tenant and publish it on ``g``.

    Setting ``g.tenant_id`` is what arms the ORM's tenant scoping, so it must
    happen before any query runs. Suspended tenants resolve to no tenant.
    """
    from core.models import TENANT_STATUS_ACTIVE

    tenant = find_tenant()
    if tenant is None:
        return None, (
            "Tenant could not be resolved. Send X-Tenant-ID or X-Tenant-Subdomain, "
            "or call the API on a tenant subdomain."
        )

    if tenant.status != TENANT_STATUS_ACTIVE:
        return None, (
            "Tenant is suspended"
            if tenant.status == "suspended"
            else "Tenant is not available"
        )

    g.tenant_id = tenant.id
    g.tenant = tenant
    return tenant, None


def build_context() -> GraphQLContext:
    """Build the context for one GraphQL request."""
    from modules.students.graphql.loaders import build_loaders

    tenant, tenant_error = _resolve_tenant()
    authentication = authenticate_request()

    return GraphQLContext(
        tenant=tenant,
        tenant_id=tenant.id if tenant is not None else None,
        tenant_error=tenant_error,
        current_user=authentication.user,
        authentication_error=authentication.error,
        new_access_token=authentication.new_access_token,
        loaders=build_loaders(),
    )
