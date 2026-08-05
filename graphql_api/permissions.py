"""Field-level access checks for the GraphQL transport.

These answer "may this request reach this field at all". What an authenticated
person is allowed to *do* is the Authorization Domain's decision, evaluated in
services.
"""

from __future__ import annotations

from typing import Any

from strawberry.permission import BasePermission

from .errors import AuthenticationError


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
