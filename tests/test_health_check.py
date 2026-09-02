"""`/api/health` has to be able to say no.

It returned a hardcoded `{'status': 'healthy'}` — no database check, nothing.
It is the container's healthcheck and the only endpoint an uptime monitor
could probe, so it answered 200 through a total database outage and nothing
anywhere would have noticed.

Two dependencies, deliberately weighted differently:

**Postgres is critical.** Without it the API cannot answer a single business
request, so the check fails and says so.

**Redis is not.** `core/cache.py` fails open by design — a Redis outage costs
the permission cache and degrades rate limiting to in-memory, but the product
still serves. Failing the healthcheck on it would take a working API out of a
load balancer over a cache. It is reported, not fatal.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def test_a_healthy_service_reports_its_dependencies(client):
    """Reachable database means 200 — with or without a cache.

    Not pinned to "healthy": Redis is genuinely optional here, and CI often has
    none, so the honest expectation is 200 and a database that answered. Which
    of `healthy`/`degraded` that is depends on the cache, and the Redis case is
    pinned in its own test below.
    """
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] in ("healthy", "degraded"), body
    assert body["checks"]["database"] == "ok", body


def test_a_database_outage_is_not_reported_as_healthy(client, monkeypatch):
    """The whole point: 200 during a DB outage is a lie nobody would catch."""
    import app as app_module

    def dead_database():
        raise RuntimeError("could not connect to server: Connection refused")

    monkeypatch.setattr(app_module, "_database_is_reachable", dead_database)

    response = client.get("/api/health")

    assert response.status_code == 503, response.get_json()
    body = response.get_json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["database"] != "ok"


def test_a_database_outage_does_not_leak_connection_details(client, monkeypatch):
    """`/api/health` is unauthenticated — it must not print the DSN."""
    import app as app_module

    def dead_database():
        raise RuntimeError("FATAL: password authentication failed for user 'nexchool'")

    monkeypatch.setattr(app_module, "_database_is_reachable", dead_database)

    body = client.get("/api/health").get_data(as_text=True)

    assert "password" not in body.lower()
    assert "nexchool" not in body.lower()


def test_redis_being_down_does_not_fail_the_check(client, monkeypatch):
    """The cache fails open, so the service is degraded — not unhealthy."""
    import app as app_module

    def dead_redis():
        raise RuntimeError("Error 111 connecting to redis:6379")

    monkeypatch.setattr(app_module, "_cache_is_reachable", dead_redis)

    response = client.get("/api/health")

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["cache"] != "ok"


def test_health_is_still_reachable_without_a_tenant(client):
    """It is probed by a container with no tenant header and no credentials."""
    assert client.get("/api/health").status_code in (200, 503)
