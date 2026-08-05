"""GraphQL transport behaviour: context wiring, error exposure and query limits.

Most cases execute a purpose-built schema directly so they assert on transport
rules rather than on whatever business fields happen to exist today.
"""

from __future__ import annotations

import json

import pytest
import strawberry
from flask import Flask

from graphql_api import GRAPHQL_PATH, register_graphql
from graphql_api.context import GraphQLContext
from graphql_api.errors import NotFoundError
from graphql_api.extensions import MASKED_ERROR_MESSAGE, build_extensions
from graphql_api.schema import NexchoolSchema

SECRET_IN_INTERNAL_ERROR = "postgres://admin:hunter2@db"


def _schema(query_type, **overrides) -> NexchoolSchema:
    """Build a schema with the real extensions under a given configuration."""
    config = {
        "GRAPHQL_MAX_DEPTH": 12,
        "GRAPHQL_MAX_TOKENS": 2000,
        "GRAPHQL_MAX_ALIASES": 25,
        "GRAPHQL_INTROSPECTION_ENABLED": True,
    }
    config.update(overrides)
    return NexchoolSchema(query=query_type, extensions=build_extensions(config))


@strawberry.type
class _Node:
    """Self-referencing type, so a query can be nested to any depth."""

    @strawberry.field
    def child(self) -> "_Node":
        return _Node()


@strawberry.type
class _DeepQuery:
    @strawberry.field
    def root(self) -> _Node:
        return _Node()


@strawberry.type
class _Query:
    @strawberry.field
    def known_field(self) -> str:
        return "ok"

    @strawberry.field
    def missing_student(self) -> str:
        raise NotFoundError("Student not found")

    @strawberry.field
    def broken(self) -> str:
        raise ValueError(SECRET_IN_INTERNAL_ERROR)


def _execute(schema, query: str):
    return schema.execute_sync(query, context_value=GraphQLContext())


# ---------------------------------------------------------------------------
# Error exposure
# ---------------------------------------------------------------------------

def test_business_error_reaches_the_client_with_its_code():
    result = _execute(_schema(_Query), "{ missingStudent }")

    assert len(result.errors) == 1
    assert result.errors[0].message == "Student not found"
    assert result.errors[0].extensions["code"] == "NOT_FOUND"


def test_unexpected_failure_is_masked_and_leaks_nothing():
    result = _execute(_schema(_Query), "{ broken }")

    assert len(result.errors) == 1
    assert result.errors[0].message == MASKED_ERROR_MESSAGE
    assert SECRET_IN_INTERNAL_ERROR not in json.dumps(
        [error.formatted for error in result.errors]
    )


def test_unknown_field_tells_the_client_what_is_wrong():
    result = _execute(_schema(_Query), "{ noSuchField }")

    assert len(result.errors) == 1
    assert "Cannot query field" in result.errors[0].message
    assert result.errors[0].message != MASKED_ERROR_MESSAGE


# ---------------------------------------------------------------------------
# Query limits
# ---------------------------------------------------------------------------

def test_query_deeper_than_the_limit_is_rejected():
    nesting = 6
    query = "{ root " + "{ child " * nesting + "{ __typename }" + " }" * nesting + " }"
    result = _execute(_schema(_DeepQuery, GRAPHQL_MAX_DEPTH=4), query)

    assert len(result.errors) == 1
    assert "exceeds maximum operation depth" in result.errors[0].message


def test_query_with_too_many_aliases_is_rejected():
    query = "{ " + " ".join(f"a{i}: knownField" for i in range(6)) + " }"
    result = _execute(_schema(_Query, GRAPHQL_MAX_ALIASES=3), query)

    assert len(result.errors) == 1
    assert "aliases" in result.errors[0].message.lower()


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------

INTROSPECTION_QUERY = "{ __schema { queryType { name } } }"


def test_introspection_is_available_when_enabled():
    result = _execute(_schema(_Query, GRAPHQL_INTROSPECTION_ENABLED=True), INTROSPECTION_QUERY)

    assert not result.errors
    assert result.data["__schema"]["queryType"]["name"] == "Query"


def test_introspection_is_refused_when_disabled():
    result = _execute(_schema(_Query, GRAPHQL_INTROSPECTION_ENABLED=False), INTROSPECTION_QUERY)

    assert result.errors
    assert "introspection" in result.errors[0].message.lower()


# ---------------------------------------------------------------------------
# Endpoint registration
# ---------------------------------------------------------------------------

def _register_on_bare_app(**config) -> Flask:
    app = Flask(__name__)
    app.config.update(GRAPHQL_RATE_LIMIT=None, **config)
    register_graphql(app)
    return app


def _graphql_rule(app: Flask):
    return next(rule for rule in app.url_map.iter_rules() if str(rule) == GRAPHQL_PATH)


def test_endpoint_is_post_only_when_the_ide_is_disabled():
    rule = _graphql_rule(_register_on_bare_app(GRAPHQL_IDE_ENABLED=False))

    assert "POST" in rule.methods
    assert "GET" not in rule.methods


def test_endpoint_serves_get_when_the_ide_is_enabled():
    rule = _graphql_rule(_register_on_bare_app(GRAPHQL_IDE_ENABLED=True))

    assert "GET" in rule.methods


# ---------------------------------------------------------------------------
# Request context (integration, through the real application)
# ---------------------------------------------------------------------------

STATUS_QUERY = "{ graphqlStatus { authenticated tenantSubdomain } }"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def test_status_reports_the_tenant_named_by_the_request_header(client, tenant):
    response = client.post(
        GRAPHQL_PATH,
        json={"query": STATUS_QUERY},
        headers={"X-Tenant-Subdomain": tenant.subdomain},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["graphqlStatus"] == {
        "authenticated": False,
        "tenantSubdomain": tenant.subdomain,
    }


def test_unauthenticated_request_is_served_but_reports_no_identity(client, tenant):
    response = client.post(
        GRAPHQL_PATH,
        json={"query": STATUS_QUERY},
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": "Bearer not-a-real-token",
        },
    )

    body = response.get_json()
    assert response.status_code == 200
    assert body["data"]["graphqlStatus"]["authenticated"] is False


def test_responses_are_never_cached_across_tenants(client, tenant):
    response = client.post(
        GRAPHQL_PATH,
        json={"query": STATUS_QUERY},
        headers={"X-Tenant-Subdomain": tenant.subdomain},
    )

    assert response.headers["Cache-Control"] == "no-store, private, max-age=0"
    assert "X-Tenant-ID" in response.headers["Vary"]
