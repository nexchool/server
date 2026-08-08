"""Error contract for the GraphQL transport.

Mirrors the error hierarchy in `.claude/rules/error-handling.md`: services raise
a business error, the transport turns it into a GraphQL error carrying a stable
machine-readable ``extensions.code`` that clients can branch on.

Anything that is *not* a BusinessError is a bug on our side. Those are logged
with full context server-side and masked before they reach the client, so an
internal message or stack trace can never leak (see ``extensions.build_extensions``).
"""

from __future__ import annotations

from typing import Any, Optional

from graphql import GraphQLError


class BusinessError(GraphQLError):
    """A failure the client is allowed to see and act on.

    Subclasses set ``code``; it is exposed to clients as ``extensions.code``.
    """

    code = "INTERNAL_ERROR"

    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        extensions: dict[str, Any] = {"code": self.code}
        if details is not None:
            extensions["details"] = details
        super().__init__(message, extensions=extensions)


class ValidationError(BusinessError):
    """Input failed validation — the client sent something malformed."""

    code = "VALIDATION_ERROR"


class AuthenticationError(BusinessError):
    """No valid identity on the request (missing, expired or rejected token)."""

    code = "UNAUTHENTICATED"


class AuthorizationError(BusinessError):
    """Authenticated, but lacking the business authority for this action."""

    code = "FORBIDDEN"


class NotFoundError(BusinessError):
    """The requested resource does not exist (or is not visible to this caller)."""

    code = "NOT_FOUND"


class ConflictError(BusinessError):
    """The operation conflicts with current state (duplicate, closed period…)."""

    code = "CONFLICT"


class TenantRequiredError(BusinessError):
    """The operation is tenant-scoped but no tenant could be resolved."""

    code = "TENANT_REQUIRED"


class FeatureDisabledError(BusinessError):
    """The school has this module switched off."""

    code = "FEATURE_DISABLED"


class SetupIncompleteError(BusinessError):
    """The school is still being set up, so it cannot be written to yet."""

    code = "SETUP_INCOMPLETE"


def is_business_error(error: GraphQLError) -> bool:
    """True when the error was raised deliberately and is safe to expose.

    graphql-core re-wraps resolver exceptions, keeping the original on
    ``original_error``, so both the wrapper and the original are checked.
    """
    return isinstance(error, BusinessError) or isinstance(
        getattr(error, "original_error", None), BusinessError
    )


def is_client_error(error: GraphQLError) -> bool:
    """True for errors the client caused, which it is therefore allowed to read.

    Two kinds qualify: business errors we raised on purpose, and GraphQL syntax
    or validation errors ("unknown field", "exceeds maximum depth"). The latter
    are raised before execution begins and so carry no ``original_error`` —
    that absence is what distinguishes them from a resolver blowing up.

    Validation messages do describe parts of the schema, which is a deliberate
    trade: without them no client developer can tell a typo from an outage.
    """
    return is_business_error(error) or getattr(error, "original_error", None) is None
