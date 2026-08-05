"""GraphQL transport.

Mounted at ``/api/graphql``. It shares tenancy, authentication, the database
session and the error taxonomy with the REST transport — a business operation is
implemented once in a service and exposed by exactly one transport.
"""

from __future__ import annotations

from flask import Flask
from strawberry.flask.views import GraphQLView

from .context import GraphQLContext, build_context
from .schema import build_schema

GRAPHQL_PATH = "/api/graphql"


class NexchoolGraphQLView(GraphQLView):
    """Flask view that hands every operation the request's resolved context."""

    def get_context(self, request, response) -> GraphQLContext:
        context = build_context()
        if context.new_access_token:
            # Same contract as REST: a refreshed access token comes back on the
            # response so the client can replace the expired one.
            response.headers["X-New-Access-Token"] = context.new_access_token
        return context


def register_graphql(app: Flask) -> None:
    """Mount the GraphQL endpoint on the application."""
    graphql_ide = "graphiql" if app.config.get("GRAPHQL_IDE_ENABLED", False) else None

    view = NexchoolGraphQLView.as_view(
        "graphql",
        schema=build_schema(app.config),
        graphql_ide=graphql_ide,
        # GET exists only to serve the IDE; without it the endpoint is POST-only,
        # which keeps queries out of URLs, logs and browser history.
        allow_queries_via_get=bool(graphql_ide),
    )

    rate_limit = app.config.get("GRAPHQL_RATE_LIMIT")
    if rate_limit:
        from core.extensions import limiter

        view = limiter.limit(rate_limit)(view)

    app.add_url_rule(
        GRAPHQL_PATH,
        view_func=view,
        methods=["GET", "POST"] if graphql_ide else ["POST"],
    )
