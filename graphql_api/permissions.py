"""Field-level access checks for the GraphQL transport.

These answer "may this request reach this field at all". What an authenticated
person is allowed to *do* is the Authorization Domain's decision, evaluated in
services.
"""

from __future__ import annotations

from typing import Any, Type

from strawberry.permission import BasePermission

from .errors import (
    AuthenticationError,
    AuthorizationError,
    SetupIncompleteError,
    TenantRequiredError,
)


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


class SetupComplete(BasePermission):
    """Require the school to have finished setting itself up.

    A school still in the wizard has not decided what its classes are, so a
    write that lands first writes into a structure that is still being made
    up. Reads stay open — an admin has to be able to look at the dashboard
    while working through the wizard — so this belongs on mutations only.

    Platform admins pass regardless, exactly as they do in REST: somebody has
    to be able to unstick a school that is stuck in its own setup.

    The tenant is not re-checked here; `RequiresTenant` comes first and this
    permission is meaningless without it.
    """

    message = "Complete school setup before using this feature."

    def has_permission(self, source: Any, info: Any, **kwargs: Any) -> bool:
        from core.decorators.setup import is_setup_complete

        context = info.context
        user = getattr(context, "current_user", None)
        if user is not None and getattr(user, "is_platform_admin", False):
            return True

        if not is_setup_complete(context.tenant_id):
            raise SetupIncompleteError(self.message)
        return True


def requires_any(*permission_keys: str) -> Type[BasePermission]:
    """Field-level guard satisfied by any one of several Business Actions.

    Some reads are offered to more than one kind of person on different terms
    — a head teacher may read the whole school, a class teacher only their own
    classes. Both reach the same field; what differs is what it returns, which
    is the resolver's job, not this guard's.
    """

    class RequiresAnyPermission(BasePermission):
        message = "You do not have permission to perform this action."

        def has_permission(self, source: Any, info: Any, **kwargs: Any) -> bool:
            from modules.rbac.services import has_permission as holds

            user = getattr(info.context, "current_user", None)
            if user is None or not any(holds(user.id, key) for key in permission_keys):
                raise AuthorizationError(self.message)
            return True

    RequiresAnyPermission.__name__ = "RequiresAny_" + "_".join(
        key.replace(".", "_") for key in permission_keys
    )
    return RequiresAnyPermission


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
