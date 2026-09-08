"""Two tabs renewing at once must not sign the person out of both.

A refresh token rotates and may be spent once, which is what makes a stolen one
useful for only moments. But a browser shares that token across every tab of an
origin while the promise that renews it lives in one tab, so when an access
token expires two tabs can start two renewals milliseconds apart. The loser
presents a token the winner has just spent — byte-for-byte what a replay looks
like — and the old answer to that was to end the session and every generation of
its token.

So these tests pin the line between the two readings. Inside the grace window,
with the successor still unspent, it is one client overtaking itself: refused,
nothing revoked. Outside it, or once the successor has been used, it is somebody
holding a copy: the family ends, exactly as before.

The forgiving path must stay narrow, so three of the five tests below are about
what is still punished.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from core.database import db
from core.school_time import utc_now
from modules.auth.event_models import EVENT_REFRESH_RACE, AuthEvent
from modules.auth.models import Session
from modules.auth.refresh_models import RefreshToken, hash_refresh_token
from modules.auth.tokens import ROTATION_GRACE_SECONDS
from tests.auth._characterization import grant_permissions, make_tenant, make_user

PASSWORD = "C0rrectHorse1"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def tenant(db_session):
    return make_tenant(db_session, subdomain_prefix="rce")


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


def _refresh(client, tenant, token):
    return client.post(
        "/api/auth/refresh",
        json={"refresh_token": token},
        headers={"X-Tenant-ID": tenant.id, "X-Client-Surface": "admin-web"},
    )


def _session_of(account):
    return Session.query.filter_by(user_id=account.id).one()


def _row_for(token):
    return RefreshToken.query.filter_by(token_hash=hash_refresh_token(token)).one()


def _age_the_consumption(token, seconds):
    """Move a token's spending back in time, so the grace window has passed."""
    row = _row_for(token)
    row.consumed_at = utc_now() - timedelta(seconds=seconds)
    db.session.commit()


# ---------------------------------------------------------------------------
# The race, forgiven
# ---------------------------------------------------------------------------

def test_a_second_tab_renewing_at_once_is_refused_but_not_signed_out(
    client, tenant, account
):
    first = _sign_in(client, tenant, account)

    winner = _refresh(client, tenant, first["refresh_token"])
    assert winner.status_code == 200

    loser = _refresh(client, tenant, first["refresh_token"])
    assert loser.status_code == 401, "a spent token must never be honoured twice"

    assert not _session_of(account).revoked, (
        "the session was ended because the person had two tabs open"
    )


def test_the_winner_can_still_renew_after_the_race(client, tenant, account):
    """The point of not revoking: the session has to remain usable.

    A refusal that quietly poisoned the family would pass the test above and
    still sign everybody out a minute later.
    """
    first = _sign_in(client, tenant, account)
    winner = _refresh(client, tenant, first["refresh_token"]).get_json()["data"]

    assert _refresh(client, tenant, first["refresh_token"]).status_code == 401

    again = _refresh(client, tenant, winner["refresh_token"])
    assert again.status_code == 200, again.get_json()
    assert again.get_json()["data"]["refresh_token"] != winner["refresh_token"]


def test_the_race_is_recorded_so_it_can_be_counted(client, tenant, account):
    first = _sign_in(client, tenant, account)
    _refresh(client, tenant, first["refresh_token"])
    _refresh(client, tenant, first["refresh_token"])

    races = AuthEvent.query.filter_by(event_type=EVENT_REFRESH_RACE).all()
    assert len(races) == 1
    assert races[0].session_id == _session_of(account).id


# ---------------------------------------------------------------------------
# The replay, still punished
# ---------------------------------------------------------------------------

def test_a_token_presented_after_the_grace_window_still_ends_the_family(
    client, tenant, account
):
    first = _sign_in(client, tenant, account)
    _refresh(client, tenant, first["refresh_token"])

    _age_the_consumption(first["refresh_token"], ROTATION_GRACE_SECONDS + 5)

    assert _refresh(client, tenant, first["refresh_token"]).status_code == 401
    assert _session_of(account).revoked, (
        "a token replayed long after it was spent is a theft, not a race"
    )


def test_a_generation_whose_successor_was_already_used_ends_the_family(
    client, tenant, account
):
    """The condition that separates 'behind' from 'somewhere else entirely'.

    If the successor has been spent, the real client has moved on, and whoever
    still holds this generation is not a tab lagging by milliseconds.
    """
    first = _sign_in(client, tenant, account)
    second = _refresh(client, tenant, first["refresh_token"]).get_json()["data"]
    _refresh(client, tenant, second["refresh_token"])

    assert _refresh(client, tenant, first["refresh_token"]).status_code == 401
    assert _session_of(account).revoked


def test_an_unknown_token_is_still_just_refused(client, tenant, account):
    _sign_in(client, tenant, account)

    assert _refresh(client, tenant, "not-a-token-anyone-issued").status_code == 401
    assert not _session_of(account).revoked, (
        "a stranger's guess must not be able to end somebody else's session"
    )
