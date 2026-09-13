"""A suspended school can still sign in and look at its subscription.

Suspension used to be a full lock-out: the tenant did not even resolve, so a
school suspended for non-payment was told its school does not exist. Now that
the platform suspends schools by itself when a payment grace period runs out
(ADR-023), that is the worst possible thing to show them — they need to see
what is owed and what has been paid, which is exactly the page they were
locked out of.

So a suspended school resolves, signs in, and reaches auth and
/api/subscription. Everything else is refused, and every write stays refused
by the subscription gate regardless. A deleted tenant is still gone.
"""

from __future__ import annotations

import pytest

from modules.auth.services import generate_access_token
from tests.auth._characterization import grant_permissions, make_tenant, make_user


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _member(db_session, tenant, *, permissions=("subscription.read",)):
    user = make_user(db_session, tenant, password="Member12345")
    grant_permissions(db_session, tenant, user, permissions)
    return {"Authorization": f"Bearer {generate_access_token(user)}",
            "X-Tenant-ID": tenant.id}


def test_a_suspended_school_can_read_its_subscription_state(client, db_session):
    tenant = make_tenant(db_session)
    headers = _member(db_session, tenant)
    tenant.status = "suspended"
    db_session.flush()

    response = client.get("/api/subscription/state", headers=headers)

    assert response.status_code == 200
    assert response.get_json()["data"]["subscription"]["reason"] == "SubscriptionSuspended"


def test_a_suspended_school_can_read_its_payments(client, db_session):
    tenant = make_tenant(db_session)
    headers = _member(db_session, tenant)
    tenant.status = "suspended"
    db_session.flush()

    assert client.get("/api/subscription/payments", headers=headers).status_code == 200


def test_a_suspended_school_still_cannot_reach_the_rest_of_the_app(client, db_session):
    tenant = make_tenant(db_session)
    headers = _member(db_session, tenant, permissions=("student.read.all",))
    tenant.status = "suspended"
    db_session.flush()

    response = client.get("/api/students", headers=headers)

    assert response.status_code == 403
    assert response.get_json()["error"] == "TenantSuspended"


def test_a_deleted_school_reaches_nothing_at_all(client, db_session):
    tenant = make_tenant(db_session)
    headers = _member(db_session, tenant)
    tenant.status = "deleted"
    db_session.flush()

    assert client.get("/api/subscription/state", headers=headers).status_code == 403


def test_a_suspended_school_is_found_by_its_own_subdomain(flask_app, db_session):
    """The lookup used to hide it, so its login answered "tenant not found"."""
    from core.tenant import find_tenant

    tenant = make_tenant(db_session)
    tenant.status = "suspended"
    db_session.flush()

    with flask_app.test_request_context(
        "/api/auth/login", headers={"X-Tenant-Subdomain": tenant.subdomain}
    ):
        assert find_tenant() is not None
        assert find_tenant().id == tenant.id


def test_the_auth_resolver_lets_a_suspended_school_through_to_sign_in(flask_app, db_session):
    from flask import g

    from core.tenant import resolve_tenant_for_auth

    tenant = make_tenant(db_session)
    tenant.status = "suspended"
    db_session.flush()

    with flask_app.test_request_context(
        "/api/auth/login", headers={"X-Tenant-Subdomain": tenant.subdomain}
    ):
        assert resolve_tenant_for_auth() is None  # no refusal
        assert g.tenant_id == tenant.id


def test_a_deleted_school_is_refused_even_at_sign_in(flask_app, db_session):
    from core.tenant import resolve_tenant_for_auth

    tenant = make_tenant(db_session)
    tenant.status = "deleted"
    db_session.flush()

    with flask_app.test_request_context(
        "/api/auth/login", headers={"X-Tenant-Subdomain": tenant.subdomain}
    ):
        failure = resolve_tenant_for_auth(use_default=False)
        assert failure is not None and failure[0] == 403
