"""Phase −1 — sessions after sign-in: refresh, logout, and revocation.

CHARACTERIZATION. Sessions are the part of authentication that outlives the
login request, and the identity specification promises that no phase of the
refactor will involuntarily revoke one. These tests describe exactly which
operations end which sessions today, so that promise is checkable rather than
asserted.

Deliberately NOT covered: refresh-token hashing and rotation. Neither exists;
both are deferred changes, and a test written for them now would be a test of
the specification rather than of the repository.
"""

from __future__ import annotations

import pytest

from tests.auth._characterization import (
    decode_access_token,
    live_sessions_for,
    login,
    make_account,
    sessions_for,
)

PASSWORD = "C0rrectHorse1"
NEW_PASSWORD = "Ch0senByMe99"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def account(db_session, tenant):
    return make_account(db_session, tenant, password=PASSWORD)


def _sign_in(client, tenant, account):
    return login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]


def _headers(tenant, tokens):
    return {
        "X-Tenant-Subdomain": tenant.subdomain,
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-Refresh-Token": tokens["refresh_token"],
    }


# ---------------------------------------------------------------------------
# Group 15 — refresh
# ---------------------------------------------------------------------------

def test_a_live_access_token_reaches_a_protected_route(client, tenant, account):
    tokens = _sign_in(client, tenant, account)

    response = client.get("/api/auth/profile", headers=_headers(tenant, tokens))

    assert response.status_code == 200


def test_an_expired_access_token_is_refreshed_from_the_refresh_token(
    client, db_session, tenant, account
):
    """The silent-refresh contract every client depends on: the request still
    succeeds and the replacement token comes back in a response header."""
    from modules.auth.services import generate_access_token

    tokens = _sign_in(client, tenant, account)
    expired = generate_access_token(account, access_minutes=-1)

    response = client.get(
        "/api/auth/profile",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {expired}",
            "X-Refresh-Token": tokens["refresh_token"],
        },
    )

    assert response.status_code == 200
    minted = response.headers.get("X-New-Access-Token")
    assert minted
    assert decode_access_token(minted)["sub"] == account.id


def test_a_refresh_stamps_last_accessed_at_on_the_session(
    client, db_session, tenant, account
):
    from modules.auth.services import generate_access_token

    tokens = _sign_in(client, tenant, account)
    assert sessions_for(account.id)[0].last_accessed_at is None

    client.get(
        "/api/auth/profile",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {generate_access_token(account, access_minutes=-1)}",
            "X-Refresh-Token": tokens["refresh_token"],
        },
    )

    assert sessions_for(account.id)[0].last_accessed_at is not None


def test_refreshing_rotates_the_refresh_token(client, db_session, tenant, account):
    """It used not to. The same long-lived string kept working for its whole
    window, so a stolen refresh token was good for seven days.

    Now every refresh spends the token and returns its successor, in the
    `X-New-Refresh-Token` header. A client that keeps the old one is replaying
    a consumed token on its next attempt — see the reuse test below.
    """
    from modules.auth.services import generate_access_token

    tokens = _sign_in(client, tenant, account)

    response = client.get(
        "/api/auth/profile",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {generate_access_token(account, access_minutes=-1)}",
            "X-Refresh-Token": tokens["refresh_token"],
        },
    )

    assert response.status_code == 200
    replacement = response.headers.get("X-New-Refresh-Token")
    assert replacement and replacement != tokens["refresh_token"]


def test_a_revoked_session_cannot_refresh(client, db_session, tenant, account):
    from modules.auth.services import generate_access_token

    tokens = _sign_in(client, tenant, account)
    sessions_for(account.id)[0].revoke()

    response = client.get(
        "/api/auth/profile",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {generate_access_token(account, access_minutes=-1)}",
            "X-Refresh-Token": tokens["refresh_token"],
        },
    )

    assert response.status_code == 401


def test_an_expired_access_token_with_no_refresh_token_is_401(
    client, tenant, account
):
    from modules.auth.services import generate_access_token

    _sign_in(client, tenant, account)

    response = client.get(
        "/api/auth/profile",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {generate_access_token(account, access_minutes=-1)}",
        },
    )

    assert response.status_code == 401


def test_a_garbage_refresh_token_is_refused(client, tenant, account):
    from modules.auth.services import generate_access_token

    _sign_in(client, tenant, account)

    response = client.get(
        "/api/auth/profile",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {generate_access_token(account, access_minutes=-1)}",
            "X-Refresh-Token": "not-a-jwt",
        },
    )

    assert response.status_code == 401


def test_revoking_a_session_invalidates_its_access_token_at_once(
    client, db_session, tenant, account
):
    """It used not to. Revoking a session stopped future refreshes and left the
    access token already in somebody's hands working until it expired — up to
    fifteen minutes by default, and up to seven days for a school that had
    raised its session timeout. For an account being suspended mid-incident
    that is not a window anybody should have to explain.

    The token now names its session and validation checks that session is
    live, so revocation is felt on the very next request.
    """
    tokens = _sign_in(client, tenant, account)
    sessions_for(account.id)[0].revoke()

    response = client.get("/api/auth/profile", headers=_headers(tenant, tokens))

    assert response.status_code == 401


def test_suspending_the_account_takes_effect_on_the_next_request(
    client, db_session, tenant, account
):
    """The counterpart: account status IS re-checked per request, so revocation
    of the human is immediate even on a live token."""
    tokens = _sign_in(client, tenant, account)
    account.is_suspended = True
    db_session.flush()

    response = client.get("/api/auth/profile", headers=_headers(tenant, tokens))

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Group 14 — logout and revocation
# ---------------------------------------------------------------------------

def test_refresh_tokens_minted_in_the_same_second_are_identical(account):
    """EXISTING DEFECT, characterized and deliberately NOT fixed.

    `generate_refresh_token` signs `{sub, type, iat, exp}` and nothing else.
    `iat`/`exp` are whole seconds, so two tokens minted for one account inside
    one second are BYTE-IDENTICAL — and `sessions.refresh_token` is indexed but
    not unique, so two live rows can then carry the same string.

    Asserted at the mint rather than by racing two HTTP logins: the defect is a
    property of the payload, and driving it through the login route makes the
    test depend on both requests landing in the same wall-clock second.
    """
    from modules.auth.services import generate_refresh_token

    assert generate_refresh_token(account) == generate_refresh_token(account)


def test_two_sessions_can_therefore_hold_one_token_string(
    client, db_session, tenant, account
):
    """The consequence of the above, constructed rather than raced: two live
    session rows carrying the same refresh token."""
    first = _sign_in(client, tenant, account)
    _sign_in(client, tenant, account)
    rows = live_sessions_for(account.id)
    assert len(rows) == 2

    # What the mint produces inside one second, made deterministic.
    for row in rows:
        row.refresh_token = first["refresh_token"]
    db_session.flush()

    assert len({row.refresh_token for row in live_sessions_for(account.id)}) == 1


def test_logout_revokes_exactly_one_session_row(
    client, db_session, tenant, account
):
    """EXISTING BEHAVIOUR. `logout_user` resolves the session with `.first()`,
    so exactly one row is revoked — but when two rows share a token string
    (see above) which one is anybody's guess, and the survivor still answers
    to the token the caller just logged out with."""
    first = _sign_in(client, tenant, account)
    _sign_in(client, tenant, account)
    assert len(live_sessions_for(account.id)) == 2

    response = client.post(
        "/api/auth/logout",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "X-Refresh-Token": first["refresh_token"],
        },
    )

    assert response.status_code == 200
    assert len(live_sessions_for(account.id)) == 1


def test_two_sessions_can_no_longer_share_a_refresh_token(
    client, db_session, tenant, account
):
    """The defect this file used to characterize, now impossible to construct.

    A refresh token was a JWT of `{sub, type, iat, exp}`; timestamps are whole
    seconds, so two sign-ins by one account inside one second were byte
    identical. Two live sessions could hold the same string, `logout` resolved
    it with `.first()` and revoked an arbitrary one, and the token kept
    working — so logging out did not reliably end access.

    A token is now 48 random bytes and its digest carries a unique index, so
    the collision cannot happen and the ambiguity it created cannot either.
    """
    from sqlalchemy.exc import IntegrityError

    from modules.auth.refresh_models import RefreshToken, hash_refresh_token

    first = _sign_in(client, tenant, account)
    second = _sign_in(client, tenant, account)

    assert first["refresh_token"] != second["refresh_token"]

    # And the database refuses to be told otherwise.
    rows = RefreshToken.query.filter_by(user_id=account.id).all()
    assert len({row.token_hash for row in rows}) == len(rows)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            rows[1].token_hash = hash_refresh_token(first["refresh_token"])
            db_session.flush()

def test_logout_of_a_single_session_ends_it_when_there_is_only_one(
    client, db_session, tenant, account
):
    """The unambiguous case: one session, one token, logout ends it."""
    tokens = _sign_in(client, tenant, account)

    client.post(
        "/api/auth/logout",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "X-Refresh-Token": tokens["refresh_token"],
        },
    )

    assert live_sessions_for(account.id) == []


def test_a_revoked_session_records_when_it_was_revoked(
    client, db_session, tenant, account
):
    tokens = _sign_in(client, tenant, account)

    client.post(
        "/api/auth/logout",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "X-Refresh-Token": tokens["refresh_token"],
        },
    )

    session = sessions_for(account.id)[0]
    assert session.revoked is True
    assert session.revoked_at is not None
    # The row is kept, not deleted — revocation is a flag. What is *not* kept
    # is the token: it never sat on this row, and its generations are retired
    # with the session so that revoking one also ends the ability to refresh
    # it.
    assert session.refresh_token is None


def test_logout_needs_no_authentication(client, db_session, tenant, account):
    """EXISTING BEHAVIOUR, asserted rather than endorsed: possession of the
    refresh token is the whole credential. No Authorization header is sent."""
    tokens = _sign_in(client, tenant, account)

    response = client.post(
        "/api/auth/logout",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "X-Refresh-Token": tokens["refresh_token"],
        },
    )

    assert response.status_code == 200


def test_logout_with_neither_a_token_nor_a_cookie_is_a_400(client, tenant):
    response = client.post(
        "/api/auth/logout", headers={"X-Tenant-Subdomain": tenant.subdomain}
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "ValidationError"


def test_resetting_the_password_revokes_every_session(
    client, db_session, tenant, account
):
    _sign_in(client, tenant, account)
    _sign_in(client, tenant, account)
    token = account.generate_reset_password_token()
    db_session.flush()

    response = client.post(
        "/api/auth/password/reset",
        json={
            "email": account.email,
            "token": token,
            "new_password": NEW_PASSWORD,
            "tenant_id": tenant.id,
        },
    )

    assert response.status_code == 200, response.get_json()
    assert live_sessions_for(account.id) == []


def test_a_forced_reset_keeps_the_callers_session_and_ends_the_others(
    client, db_session, tenant
):
    account = make_account(
        db_session, tenant, password=PASSWORD, force_password_reset=True
    )
    keeper = _sign_in(client, tenant, account)
    _sign_in(client, tenant, account)
    assert len(live_sessions_for(account.id)) == 2

    response = client.post(
        "/api/auth/password/force-reset",
        json={"new_password": NEW_PASSWORD},
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {keeper['access_token']}",
            "X-Refresh-Token": keeper["refresh_token"],
        },
    )

    assert response.status_code == 200, response.get_json()
    live = live_sessions_for(account.id)
    assert len(live) == 1
    # Identified by session id, not by token string: two same-second logins
    # can share a token (see the collision tests above).
    # Identified through the token table: the session no longer carries the
    # token on a column of its own.
    from modules.auth.tokens import session_for_token

    assert live[0].id == session_for_token(keeper["refresh_token"]).id


def test_changing_the_password_keeps_sessions_unless_asked(
    client, db_session, tenant, account
):
    tokens = _sign_in(client, tenant, account)
    _sign_in(client, tenant, account)

    response = client.post(
        "/api/auth/password/change",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {tokens['access_token']}",
            "X-Refresh-Token": tokens["refresh_token"],
        },
    )

    assert response.status_code == 200, response.get_json()
    assert len(live_sessions_for(account.id)) == 2
