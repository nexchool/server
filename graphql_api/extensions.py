"""Schema extensions: query limits, error masking and operation logging.

A single GraphQL endpoint accepts arbitrary client-composed queries, so the
limits below are the transport's equivalent of pagination on a REST list: they
bound how much work one request can ask for.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterator, Mapping

from graphql.validation import NoSchemaIntrospectionCustomRule
from strawberry.extensions import (
    AddValidationRules,
    MaskErrors,
    MaxAliasesLimiter,
    MaxTokensLimiter,
    QueryDepthLimiter,
    SchemaExtension,
)

from .errors import AuthorizationError, is_client_error

logger = logging.getLogger(__name__)

MASKED_ERROR_MESSAGE = "An unexpected error occurred"


class TranslateDomainRefusals(SchemaExtension):
    """Give refusals raised inside services the transport's vocabulary.

    A service says no by raising its own exception, and is right to — it must
    not know which transport asked. REST turns those into status codes with a
    Flask error handler, which never runs here: graphql-core catches whatever
    a resolver raises, so an untranslated refusal reaches the client as
    "An unexpected error occurred" and is logged as our bug.

    Translating in one place rather than per resolver is the point. A module
    that migrates to GraphQL should not have to remember this, and a refusal
    that surfaces as a 500 is the kind of thing nobody notices until someone
    branch-restricted files a support ticket.
    """

    def resolve(self, _next, root, info, *args, **kwargs):
        from core.branch_scope import BranchForbidden

        try:
            return _next(root, info, *args, **kwargs)
        except BranchForbidden as refusal:
            raise AuthorizationError(str(refusal)) from refusal


class OperationLogger(SchemaExtension):
    """Log each operation with its duration, caller and error count."""

    def on_operation(self) -> Iterator[None]:
        started_at = time.perf_counter()
        yield
        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)

        execution_context = self.execution_context
        context = getattr(execution_context, "context", None)
        result = getattr(execution_context, "result", None)
        errors = getattr(result, "errors", None) or []

        logger.info(
            "[GraphQL] %s | %sms | tenant=%s user=%s errors=%s",
            execution_context.operation_name or "anonymous",
            duration_ms,
            getattr(context, "tenant_id", None),
            getattr(getattr(context, "current_user", None), "id", None),
            len(errors),
        )


def _should_mask(error) -> bool:
    """Mask anything the client did not cause — i.e. our own unhandled failures."""
    return not is_client_error(error)


def build_extensions(config: Mapping[str, Any]) -> list:
    """Assemble the extension list for one application configuration."""
    extensions: list = [
        QueryDepthLimiter(max_depth=config.get("GRAPHQL_MAX_DEPTH", 12)),
        MaxTokensLimiter(max_token_count=config.get("GRAPHQL_MAX_TOKENS", 2000)),
        MaxAliasesLimiter(max_alias_count=config.get("GRAPHQL_MAX_ALIASES", 25)),
        # Before masking: a refusal must become a business error while it can
        # still be recognised as one.
        TranslateDomainRefusals,
        MaskErrors(should_mask_error=_should_mask, error_message=MASKED_ERROR_MESSAGE),
        OperationLogger,
    ]

    # Introspection stays on in development (it powers the IDE and codegen) and
    # off in production, where the schema is not public API documentation.
    if not config.get("GRAPHQL_INTROSPECTION_ENABLED", True):
        extensions.append(AddValidationRules([NoSchemaIntrospectionCustomRule]))

    return extensions
