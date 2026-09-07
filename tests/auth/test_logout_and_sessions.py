"""Phase 8 — signing out, and knowing where you are signed in.

Logout used to depend on a refresh token being attached to the request. It no
longer is, because a token that may be spent once cannot ride along on every
call — so these pin the replacement: the access token names its own session.
"""

from __future__ import annotations

import pytest

from modules.auth.models import Session
from modules.auth.refresh_models import RefreshToken
from tests.auth._characterization import (
    grant_permissions, make_tenant, make_user, sessions_for,
)

PASSWORD = "C0rrectHorse1"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _fresh(flask_app):
    from flask import g

    for attribute in ("tenant_id", "tenant", "current_user", "auth_session_id",
                      "auth_login_method"):
        if hasattr(g, attribute):
            delattr(g, attribute)


def _account(db_session, tenant):
    account = make_user(db_session, tenant, password=PASSWORD)
    grant_permissions(db_session, tenant, account, ("student.read.self",))
    return account


def _sign_in(client, flask_app, tenant, account):
    _fresh(flask_app)
    response = client.post("/api/auth/login", json={
        "email": account.email, "password": PASSWORD, "tenant_id": tenant.id})
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def _headers(tenant, tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}",
            "X-Tenant-ID": tenant.id}


def _live(account):
    return {s.id for s in sessions_for(account.id) if not s.revoked}


# ---------------------------------------------------------------------------
# Signing out of one place
# ---------------------------------------------------------------------------

def test_logging_out_with_only_an_access_token_works(
    client, db_session, flask_app
):
    """The case the clients actually produce, now that nothing attaches a
    refresh token to an ordinary request."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    _fresh(flask_app)
    response = client.post("/api/auth/logout", headers=_headers(tenant, tokens))

    assert response.status_code == 200
    assert _live(account) == set()
    assert client.get("/api/auth/profile",
                      headers=_headers(tenant, tokens)).status_code == 401


def test_logging_out_ends_that_session_and_no_other(
    client, db_session, flask_app
):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    phone = _sign_in(client, flask_app, tenant, account)
    laptop = _sign_in(client, flask_app, tenant, account)

    _fresh(flask_app)
    client.post("/api/auth/logout", headers=_headers(tenant, phone))

    assert client.get("/api/auth/profile",
                      headers=_headers(tenant, laptop)).status_code == 200
    assert len(_live(account)) == 1


def test_logging_out_retires_that_session_refresh_token_too(
    client, db_session, flask_app
):
    """Otherwise "signed out" would mean "signed out until the next renewal"."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    _fresh(flask_app)
    client.post("/api/auth/logout", headers=_headers(tenant, tokens))

    _fresh(flask_app)
    assert client.post("/api/auth/refresh",
                       headers={"X-Tenant-ID": tenant.id},
                       json={"refresh_token": tokens["refresh_token"]}
                       ).status_code == 401


def test_logging_out_twice_is_not_an_error(client, db_session, flask_app):
    """A client that retries a logout after a dropped connection should not be
    told something went wrong."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    for _ in range(2):
        _fresh(flask_app)
        assert client.post("/api/auth/logout",
                           headers=_headers(tenant, tokens)).status_code == 200


def test_a_cookie_alone_cannot_sign_somebody_out_of_everything(
    client, db_session, flask_app
):
    """The behaviour this phase was told not to keep: an unauthenticated
    request carrying only a cookie ending every session an account has. The
    production cookie is SameSite=None, so any site could have caused it."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    phone = _sign_in(client, flask_app, tenant, account)
    laptop = _sign_in(client, flask_app, tenant, account)

    _fresh(flask_app)
    client.set_cookie("auth-token", phone["access_token"], domain="localhost")
    response = client.post("/api/auth/logout", headers={"X-Tenant-ID": tenant.id})
    client.delete_cookie("auth-token", domain="localhost")

    assert response.status_code == 200
    assert client.get("/api/auth/profile",
                      headers=_headers(tenant, laptop)).status_code == 200


def test_logging_out_with_nothing_at_all_is_refused(client, db_session, flask_app):
    tenant = make_tenant(db_session)
    _fresh(flask_app)
    assert client.post("/api/auth/logout",
                       headers={"X-Tenant-ID": tenant.id}).status_code == 400


# ---------------------------------------------------------------------------
# Signing out of everywhere else
# ---------------------------------------------------------------------------

def test_signing_out_everywhere_else_keeps_the_session_that_asked(
    client, db_session, flask_app
):
    """Otherwise the button would sign you out of the screen you pressed it
    on, which nobody means by it."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    _sign_in(client, flask_app, tenant, account)
    _sign_in(client, flask_app, tenant, account)
    here = _sign_in(client, flask_app, tenant, account)

    _fresh(flask_app)
    response = client.delete("/api/auth/sessions", headers=_headers(tenant, here))

    assert response.status_code == 200
    assert response.get_json()["data"]["revoked"] == 2
    assert client.get("/api/auth/profile",
                      headers=_headers(tenant, here)).status_code == 200


def test_signing_out_everywhere_can_include_this_one_when_asked(
    client, db_session, flask_app
):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    _sign_in(client, flask_app, tenant, account)
    here = _sign_in(client, flask_app, tenant, account)

    _fresh(flask_app)
    client.delete("/api/auth/sessions?keep_current=false",
                  headers=_headers(tenant, here))

    assert _live(account) == set()


def test_the_session_list_names_places_and_never_tokens(
    client, db_session, flask_app
):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    _fresh(flask_app)
    body = client.get("/api/auth/sessions",
                      headers=_headers(tenant, tokens)).get_json()

    sessions = body["data"]["sessions"]
    assert len(sessions) == 1
    flat = repr(body)
    assert tokens["refresh_token"] not in flat
    assert tokens["access_token"] not in flat
    assert "token_hash" not in flat
    assert "refresh_token" not in flat
    assert sessions[0]["login_method"] == "email_password"


def test_one_person_cannot_end_another_persons_session(
    client, db_session, flask_app
):
    tenant = make_tenant(db_session)
    mine = _account(db_session, tenant)
    theirs = _account(db_session, tenant)
    my_tokens = _sign_in(client, flask_app, tenant, mine)
    their_tokens = _sign_in(client, flask_app, tenant, theirs)
    their_session = [
        s for s in sessions_for(theirs.id) if not s.revoked
    ][0].id

    _fresh(flask_app)
    response = client.delete(f"/api/auth/sessions/{their_session}",
                             headers=_headers(tenant, my_tokens))

    assert response.status_code == 404
    assert client.get("/api/auth/profile",
                      headers=_headers(tenant, their_tokens)).status_code == 200


# ---------------------------------------------------------------------------
# The forced password change
# ---------------------------------------------------------------------------

def test_setting_a_forced_password_keeps_you_here_and_ends_the_rest(
    client, db_session, flask_app
):
    """A password the school issued may have been seen by somebody else, so
    every other session goes — but not the one being used to replace it."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    account.force_password_reset = True
    db_session.flush()

    elsewhere = _sign_in(client, flask_app, tenant, account)
    here = _sign_in(client, flask_app, tenant, account)

    _fresh(flask_app)
    response = client.post("/api/auth/password/force-reset",
                           headers=_headers(tenant, here),
                           json={"new_password": "Ch0senByMe1"})

    assert response.status_code == 200
    assert client.get("/api/auth/profile",
                      headers=_headers(tenant, here)).status_code == 200
    assert client.get("/api/auth/profile",
                      headers=_headers(tenant, elsewhere)).status_code == 401
    _fresh(flask_app)
    assert client.post("/api/auth/refresh",
                       headers={"X-Tenant-ID": tenant.id},
                       json={"refresh_token": elsewhere["refresh_token"]}
                       ).status_code == 401
