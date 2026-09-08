"""The refresh token a sign-in hands out has to still exist on the next request.

This is the test the suite was missing, and its absence is the reason a defect
that signed every user out every fifteen minutes went unnoticed through three
phases of work on exactly this code.

`create_session` committed the session row and then minted the refresh token
with `add` + `flush` and nothing after. Every existing test asserts against the
same SQLAlchemy session the request used, where a flushed row is perfectly
visible — so the token looked persisted, and the suite stayed green while the
running application handed clients tokens the database had never heard of.

The discipline these two tests encode: **a persistence guarantee is only proved
across the session boundary.** `db.session.remove()` below is standing in for
the teardown at the end of a real request. Anything merely flushed dies there;
anything committed survives, which is the difference the assertion is about.
"""

from __future__ import annotations

import pytest

from core.database import db
from modules.auth.refresh_models import RefreshToken, hash_refresh_token
from tests.auth._characterization import grant_permissions, make_tenant, make_user

PASSWORD = "C0rrectHorse1"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def tenant(db_session):
    return make_tenant(db_session, subdomain_prefix="rts")


@pytest.fixture
def account(db_session, tenant):
    user = make_user(db_session, tenant, password=PASSWORD)
    grant_permissions(db_session, tenant, user, ("student.read.self",))
    return user


def _sign_in(client, tenant, account):
    response = client.post(
        "/api/auth/login",
        json={"email": account.email, "password": PASSWORD, "tenant_id": tenant.id},
        headers={"X-Client-Surface": "admin-web"},
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def _end_the_request():
    """Discard the session the way the end of a real request does.

    Committed work survives; a pending flush does not. That asymmetry is the
    whole point of these tests.
    """
    db.session.remove()


def test_the_refresh_token_outlives_the_request_that_minted_it(client, tenant, account):
    tokens = _sign_in(client, tenant, account)

    _end_the_request()

    stored = RefreshToken.query.filter_by(
        token_hash=hash_refresh_token(tokens["refresh_token"])
    ).all()

    assert len(stored) == 1, (
        "the client is holding a refresh token with no verifier row — "
        "its session cannot outlive one access token"
    )
    assert stored[0].consumed_at is None
    assert stored[0].generation == 1


def test_a_session_can_actually_be_renewed_on_a_later_request(client, tenant, account):
    """The user-visible consequence, exercised end to end.

    Two separate requests with a teardown between them, which is the smallest
    honest reproduction of "open the app, come back fifteen minutes later".
    """
    tokens = _sign_in(client, tenant, account)

    _end_the_request()

    response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"X-Tenant-ID": tenant.id, "X-Client-Surface": "admin-web"},
    )

    assert response.status_code == 200, response.get_json()
    renewed = response.get_json()["data"]
    assert renewed["access_token"]
    assert renewed["refresh_token"]
    assert renewed["refresh_token"] != tokens["refresh_token"], "the token must rotate"
