"""How long a session lives, and why it is not one number for everybody.

Two limits, and the tests are mostly about the difference between them. The
**idle limit** slides on every renewal, so a session in use stays alive — that
is the half that fixes signing a student out mid-week for no reason they could
see. The **absolute cap** never slides, so every session ends eventually no
matter how busy — that is the half that means a stolen phone stops working
without anybody having to report it.

The panel is the surface these tests watch hardest. An operator there can enter
any school on the system, so its numbers are deliberately close to what a bank
gives its own staff, and the test that matters most is the one asserting it did
not quietly inherit anybody else's.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from core.database import db
from core.school_time import utc_now
from modules.auth.models import Session
from modules.auth.refresh_models import RefreshToken, hash_refresh_token
from modules.auth.session_policy import SESSION_POLICY, lifetime_for, slid_expiry
from modules.auth.tokens import RefreshOutcome, rotate
from tests.auth._characterization import grant_permissions, make_tenant, make_user

PASSWORD = "C0rrectHorse1"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def tenant(db_session):
    return make_tenant(db_session, subdomain_prefix="slt")


@pytest.fixture
def account(db_session, tenant):
    user = make_user(db_session, tenant, password=PASSWORD)
    grant_permissions(db_session, tenant, user, ("student.read.self",))
    return user


def _sign_in(client, tenant, account, surface):
    response = client.post(
        "/api/auth/login",
        json={"email": account.email, "password": PASSWORD, "tenant_id": tenant.id},
        headers={"X-Client-Surface": surface},
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def _refresh(client, tenant, token, surface):
    return client.post(
        "/api/auth/refresh",
        json={"refresh_token": token},
        headers={"X-Tenant-ID": tenant.id, "X-Client-Surface": surface},
    )


def _session_of(account):
    return Session.query.filter_by(user_id=account.id).one()


# ---------------------------------------------------------------------------
# Each surface gets its own numbers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "surface,expected_days",
    [("student-mobile", 30), ("admin-web", 7), ("unknown", 7)],
)
def test_a_new_session_expires_by_its_own_surfaces_clock(
    client, tenant, account, surface, expected_days
):
    _sign_in(client, tenant, account, surface)
    session = _session_of(account)

    assert session.client_surface == surface
    expected = session.created_at + timedelta(days=expected_days)
    assert abs((session.refresh_token_expires_at - expected).total_seconds()) < 60


def test_the_panel_gets_half_an_hour_not_a_week(client, tenant, account):
    """The surface with cross-tenant authority is the strictest, not the same.

    Before this existed the panel silently inherited the same seven days as a
    student's phone. An operator console left open over lunch is now dead.
    """
    _sign_in(client, tenant, account, "panel")
    session = _session_of(account)

    lifetime = session.refresh_token_expires_at - session.created_at
    assert lifetime <= timedelta(minutes=31)
    assert lifetime_for("panel").absolute == timedelta(hours=12)


def test_an_unrecognised_surface_gets_the_careful_default(client, tenant, account):
    """A client that says something unexpected must not be rewarded for it."""
    _sign_in(client, tenant, account, "not-a-real-surface")

    assert lifetime_for("not-a-real-surface") == SESSION_POLICY["unknown"]
    assert lifetime_for("not-a-real-surface").idle < SESSION_POLICY[
        "student-mobile"
    ].idle


# ---------------------------------------------------------------------------
# The idle limit slides
# ---------------------------------------------------------------------------

def test_using_a_session_keeps_it_alive(client, tenant, account):
    tokens = _sign_in(client, tenant, account, "student-mobile")
    session = _session_of(account)

    # A week has passed and the app has been opened every day since.
    original_expiry = session.refresh_token_expires_at
    session.refresh_token_expires_at = utc_now() + timedelta(days=23)
    db.session.commit()

    assert _refresh(client, tenant, tokens["refresh_token"], "student-mobile").status_code == 200

    renewed = _session_of(account)
    assert renewed.refresh_token_expires_at > original_expiry - timedelta(days=1)
    assert renewed.refresh_token_expires_at > utc_now() + timedelta(days=29)


def test_the_absolute_cap_does_not_move(client, tenant, account):
    """The limit that makes a lost phone stop working on its own.

    A session renewed on its eighty-ninth day gets whatever is left of the
    ninetieth, and not a day more.
    """
    tokens = _sign_in(client, tenant, account, "student-mobile")
    session = _session_of(account)

    session.created_at = utc_now() - timedelta(days=89)
    db.session.commit()

    assert _refresh(client, tenant, tokens["refresh_token"], "student-mobile").status_code == 200

    renewed = _session_of(account)
    ceiling = renewed.created_at + timedelta(days=90)
    assert renewed.refresh_token_expires_at <= ceiling
    assert renewed.refresh_token_expires_at < utc_now() + timedelta(days=2)


def test_a_session_past_its_cap_cannot_renew_its_way_back(client, tenant, account):
    tokens = _sign_in(client, tenant, account, "student-mobile")
    session = _session_of(account)

    session.created_at = utc_now() - timedelta(days=91)
    session.refresh_token_expires_at = slid_expiry(session)
    RefreshToken.query.filter_by(session_id=session.id).update(
        {"expires_at": session.refresh_token_expires_at}
    )
    db.session.commit()

    assert _refresh(client, tenant, tokens["refresh_token"], "student-mobile").status_code == 401


# ---------------------------------------------------------------------------
# Invariants that must survive the change
# ---------------------------------------------------------------------------

def test_a_token_never_outlives_the_session_it_belongs_to(client, tenant, account):
    tokens = _sign_in(client, tenant, account, "panel")
    session = _session_of(account)

    row = RefreshToken.query.filter_by(
        token_hash=hash_refresh_token(tokens["refresh_token"])
    ).one()
    assert row.expires_at <= session.refresh_token_expires_at


def test_a_revoked_session_does_not_slide(client, tenant, account, flask_app):
    tokens = _sign_in(client, tenant, account, "admin-web")
    session = _session_of(account)
    before = session.refresh_token_expires_at

    session.revoked = True
    session.revoked_at = utc_now()
    db.session.commit()

    with flask_app.test_request_context():
        outcome, _, replacement = rotate(tokens["refresh_token"])

    assert outcome == RefreshOutcome.SESSION_REVOKED
    assert replacement is None
    assert _session_of(account).refresh_token_expires_at == before
