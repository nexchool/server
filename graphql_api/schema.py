"""Root GraphQL schema.

Business capabilities are added here as modules migrate: each module owns its
own types and resolvers, and this file composes them into the single schema the
platform exposes.
"""

from __future__ import annotations

import logging
from typing import Any, List, Mapping, Optional

import strawberry
from graphql import GraphQLError

from .errors import is_client_error
from .extensions import build_extensions

logger = logging.getLogger(__name__)


@strawberry.type(description="How the GraphQL transport resolved this request.")
class GraphQLStatus:
    authenticated: bool = strawberry.field(
        description="Whether the request carried a valid identity."
    )
    tenant_subdomain: Optional[str] = strawberry.field(
        description="Subdomain of the resolved tenant, or null if none resolved."
    )


@strawberry.type
class TransportQuery:
    @strawberry.field(
        description=(
            "Reports how this request was resolved — used to verify client wiring "
            "(tenant headers, credentials) against a deployment. Service health "
            "lives at the REST endpoint GET /api/health."
        )
    )
    def graphql_status(self, info: strawberry.Info) -> GraphQLStatus:
        context = info.context
        return GraphQLStatus(
            authenticated=context.is_authenticated,
            tenant_subdomain=getattr(context.tenant, "subdomain", None),
        )


def _build_query_type() -> type:
    """Compose the root Query from the transport's own fields and each module's.

    Imported here rather than at module scope because module resolvers import
    the transport's errors and permissions.
    """
    from modules.auth.resolvers import IdentityQuery
    from modules.people.resolvers import PeopleQuery
    from modules.students.resolvers import StudentQuery

    @strawberry.type(description="Every read the platform exposes.")
    class Query(TransportQuery, IdentityQuery, PeopleQuery, StudentQuery):
        pass

    return Query


def _build_mutation_type() -> type:
    """Compose the root Mutation from each module's writes.

    Add a module's mutation class here, the same way its queries are added
    above. A field that changes something must carry `IsAuthenticated`,
    `RequiresTenant` and the Business Action it performs — with no tenant
    resolved the ORM scope is inert, so an unguarded write reaches every
    school.
    """
    from modules.people.resolvers import PeopleMutation
    from modules.students.resolvers import StudentMutation

    @strawberry.type(description="Every change the platform accepts.")
    class Mutation(PeopleMutation, StudentMutation):
        pass

    return Mutation


class NexchoolSchema(strawberry.Schema):
    """Schema that logs errors with request context before they are masked.

    Client errors — business errors and failed validation — are expected traffic
    and log at WARNING; anything else is our bug and logs at ERROR with the
    traceback.
    """

    def process_errors(
        self,
        errors: List[GraphQLError],
        execution_context: Optional[Any] = None,
    ) -> None:
        context = getattr(execution_context, "context", None)
        operation = getattr(execution_context, "operation_name", None) or "anonymous"
        tenant_id = getattr(context, "tenant_id", None)
        user_id = getattr(getattr(context, "current_user", None), "id", None)

        for error in errors:
            if is_client_error(error):
                logger.warning(
                    "[GraphQL Error] %s | tenant=%s user=%s | %s",
                    operation,
                    tenant_id,
                    user_id,
                    error.message,
                )
            else:
                logger.error(
                    "[GraphQL Error] %s | tenant=%s user=%s | %s",
                    operation,
                    tenant_id,
                    user_id,
                    error.message,
                    exc_info=error.original_error or error,
                )


def build_schema(config: Mapping[str, Any]) -> NexchoolSchema:
    """Build the schema for one application configuration.

    Built per application rather than at import time so the query limits and
    introspection setting come from that app's config.
    """
    return NexchoolSchema(
        query=_build_query_type(),
        mutation=_build_mutation_type(),
        extensions=build_extensions(config),
    )
