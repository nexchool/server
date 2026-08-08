"""Field-level access checks for the GraphQL transport.

These answer "may this request reach this field at all". What an authenticated
person is allowed to *do* is the Authorization Domain's decision, evaluated in
services.
"""

from __future__ import annotations

from typing import Any, Type

from strawberry.permission import BasePermission

from .errors import AuthenticationError, AuthorizationError, TenantRequiredError


class IsAuthenticated(BasePermission):
    """Require an identified caller.

    Raises rather than returning False so the client receives the transport's
    error code and the reason authentication failed — an expired token and a
    missing one need different handling on the client.
    """

    message = "Authentication required"

    def has_permission(self, source: Any, info: Any, **kwargs: Any) -> bool:
        context = info.context
        if getattr(context, "current_user", None) is None:
            raise AuthenticationError(
                getattr(context, "authentication_error", None) or self.message
            )
        return True


class RequiresTenant(BasePermission):
    """Require a resolved school before the field runs.

    This endpoint deliberately serves tenant-less operations too — signing in
    happens before a tenant is known — so, unlike the REST middleware, it does
    not abort the request when no tenant resolves. The consequence is sharp:
    with no tenant in context the ORM scope in `core/database.py` is inert, so
    a business field that runs anyway reads **every** school's rows.

    Declaring it here rather than checking inside each resolver is the point.
    Every business field must carry this permission; the check is easy to
    forget once, and forgetting it once is a cross-tenant read.
    """

    message = "This operation requires a tenant."

    def has_permission(self, source: Any, info: Any, **kwargs: Any) -> bool:
        context = info.context
        if getattr(context, "tenant_id", None) is None:
            raise TenantRequiredError(
                getattr(context, "tenant_error", None) or self.message
            )
        return True


def requires(permission_key: str) -> Type[BasePermission]:
    """Field-level guard for one Business Action.

    The same decision REST reaches through `require_permission`, asked in the
    one place a GraphQL field can declare it. Both call `has_permission`, so a
    person's authority does not depend on which transport asked — which is the
    point of putting authorization in the Authorization Domain rather than in
    a transport.

    Combine with `IsAuthenticated` and `RequiresTenant`, in that order:
    there is no authority to check before we know who is asking and which
    school they are asking about.
    """

    class RequiresPermission(BasePermission):
        message = "You do not have permission to perform this action."

        def has_permission(self, source: Any, info: Any, **kwargs: Any) -> bool:
            from modules.rbac.services import has_permission as holds

            user = getattr(info.context, "current_user", None)
            if user is None or not holds(user.id, permission_key):
                raise AuthorizationError(self.message)
            return True

    RequiresPermission.__name__ = f"Requires_{permission_key.replace('.', '_')}"
    return RequiresPermission
