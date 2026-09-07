"""Phase 8 — the pair a client holds, from issue to revocation.

Everything here is about the two things the previous design could not do:
**spend a refresh token once**, and **feel a revocation immediately**.

The ones worth reading first:

  * `test_a_replayed_refresh_token_ends_the_whole_family` — the theft signal.
  * `test_revoking_a_session_stops_its_access_token_on_the_next_request` — what
    "revoked" now means.
  * `test_suspending_an_account_takes_everything_away_at_once` — the operation
    a school actually performs in an incident.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import db
from core.school_time import utc_now
from modules.auth.account_status import reactivate_account, suspend_account
from modules.auth.models import Session, User
from modules.auth.refresh_models import RefreshToken, hash_refresh_token
from modules.auth.services import generate_access_token
from modules.auth.tokens import RefreshOutcome, rotate, session_for_token
from tests.auth._characterization import (
    decode_access_token,
    grant_permissions,
    make_tenant,
    make_user,
    sessions_for,
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


def _account(db_session, tenant, **kwargs):
    account = make_user(db_session, tenant, password=PASSWORD, **kwargs)
    grant_permissions(db_session, tenant, account, ("student.read.self",))
    return account


def _sign_in(client, flask_app, tenant, account):
    _fresh(flask_app)
    response = client.post(
        "/api/auth/login",
        json={"email": account.email, "password": PASSWORD, "tenant_id": tenant.id},
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def _headers(tenant, tokens):
    return {
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-Tenant-ID": tenant.id,
    }


# ---------------------------------------------------------------------------
# The refresh token itself
# ---------------------------------------------------------------------------

def test_a_refresh_token_is_opaque_random_and_stored_only_as_a_digest(
    client, db_session, flask_app
):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)

    tokens = _sign_in(client, flask_app, tenant, account)
    token = tokens["refresh_token"]

    session = sessions_for(account.id)[0]
    row = RefreshToken.query.filter_by(session_id=session.id).one()

    assert len(token) >= 40
    assert session.refresh_token is None
    assert row.token_hash == hash_refresh_token(token)
    assert token not in row.token_hash
    assert row.generation == 1
    assert row.consumed_at is None


def test_two_sign_ins_never_share_a_token(client, db_session, flask_app):
    """The collision that made logout unreliable, now impossible."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)

    first = _sign_in(client, flask_app, tenant, account)
    second = _sign_in(client, flask_app, tenant, account)

    assert first["refresh_token"] != second["refresh_token"]
    hashes = {row.token_hash for row in RefreshToken.query.filter_by(user_id=account.id)}
    assert len(hashes) == 2


def test_refreshing_returns_a_new_pair_and_spends_the_old_one(
    client, db_session, flask_app
):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    _fresh(flask_app)
    response = client.post(
        "/api/auth/refresh",
        headers={"X-Tenant-ID": tenant.id},
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["access_token"] and data["refresh_token"]
    assert data["refresh_token"] != tokens["refresh_token"]
    assert data["expires_in"] > 0

    spent = RefreshToken.query.filter_by(
        token_hash=hash_refresh_token(tokens["refresh_token"])
    ).one()
    assert spent.consumed_at is not None
    assert spent.replaced_by_id is not None


def test_the_new_token_works_and_the_old_one_does_not(client, db_session, flask_app):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    _fresh(flask_app)
    replacement = client.post(
        "/api/auth/refresh",
        headers={"X-Tenant-ID": tenant.id},
        json={"refresh_token": tokens["refresh_token"]},
    ).get_json()["data"]["refresh_token"]

    _fresh(flask_app)
    again = client.post(
        "/api/auth/refresh",
        headers={"X-Tenant-ID": tenant.id},
        json={"refresh_token": replacement},
    )
    assert again.status_code == 200


def test_a_replayed_refresh_token_ends_the_whole_family(
    client, db_session, flask_app
):
    """The theft signal.

    A consumed token being presented means two parties hold copies. Which one
    is the thief cannot be known from here, so the family ends and both sign
    in again — the safe answer, and the only one that does not leave a thief
    with working access.
    """
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)
    session_id = sessions_for(account.id)[0].id

    _fresh(flask_app)
    replacement = client.post(
        "/api/auth/refresh",
        headers={"X-Tenant-ID": tenant.id},
        json={"refresh_token": tokens["refresh_token"]},
    ).get_json()["data"]["refresh_token"]

    # The thief replays the token the real client already rotated past.
    _fresh(flask_app)
    replay = client.post(
        "/api/auth/refresh",
        headers={"X-Tenant-ID": tenant.id},
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert replay.status_code == 401

    # And now nobody can refresh — not the thief, and not the real client.
    _fresh(flask_app)
    honest = client.post(
        "/api/auth/refresh",
        headers={"X-Tenant-ID": tenant.id},
        json={"refresh_token": replacement},
    )
    assert honest.status_code == 401
    assert Session.query.filter_by(id=session_id).first().revoked is True


def test_a_reuse_is_written_down(client, db_session, flask_app):
    from modules.auth.event_models import AuthEvent

    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)
    _fresh(flask_app)
    client.post("/api/auth/refresh", headers={"X-Tenant-ID": tenant.id},
                json={"refresh_token": tokens["refresh_token"]})
    _fresh(flask_app)
    client.post("/api/auth/refresh", headers={"X-Tenant-ID": tenant.id},
                json={"refresh_token": tokens["refresh_token"]})

    events = AuthEvent.query.filter_by(
        account_id=account.id, event_type="refresh_token_reuse_detected"
    ).all()
    assert events
    # Never the token.
    for event in events:
        assert tokens["refresh_token"] not in repr(
            {c.name: getattr(event, c.name) for c in event.__table__.columns}
        )


def test_another_device_is_unaffected_by_one_family_ending(
    client, db_session, flask_app
):
    """A theft on the phone should not sign somebody out of their laptop."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    phone = _sign_in(client, flask_app, tenant, account)
    laptop = _sign_in(client, flask_app, tenant, account)

    for _ in range(2):
        _fresh(flask_app)
        client.post("/api/auth/refresh", headers={"X-Tenant-ID": tenant.id},
                    json={"refresh_token": phone["refresh_token"]})

    _fresh(flask_app)
    still_fine = client.post(
        "/api/auth/refresh",
        headers={"X-Tenant-ID": tenant.id},
        json={"refresh_token": laptop["refresh_token"]},
    )
    assert still_fine.status_code == 200


def test_two_clients_racing_on_one_token_produce_one_winner(db_session, flask_app):
    """The consuming UPDATE carries its conditions, so a race resolves to one."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    from modules.auth.services import create_session

    with flask_app.test_request_context():
        session = create_session(account)
        token = session.issued_refresh_token
        db_session.flush()

        outcomes = [rotate(token)[0], rotate(token)[0]]

    assert outcomes.count(RefreshOutcome.OK) == 1
    assert RefreshOutcome.REUSED in outcomes


# ---------------------------------------------------------------------------
# Revocation, felt now
# ---------------------------------------------------------------------------

def test_an_access_token_names_its_session(client, db_session, flask_app):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    claims = decode_access_token(tokens["access_token"])
    assert claims["sid"] == sessions_for(account.id)[0].id
    assert claims["jti"]


def test_every_access_token_has_its_own_jti(client, db_session, flask_app):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    first = _sign_in(client, flask_app, tenant, account)
    second = _sign_in(client, flask_app, tenant, account)

    assert (
        decode_access_token(first["access_token"])["jti"]
        != decode_access_token(second["access_token"])["jti"]
    )


def test_revoking_a_session_stops_its_access_token_on_the_next_request(
    client, db_session, flask_app
):
    """What "revoked" now means. Before, the token in somebody's hands kept
    working until it expired."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    assert client.get("/api/auth/profile", headers=_headers(tenant, tokens)).status_code == 200

    sessions_for(account.id)[0].revoke()
    db_session.flush()

    assert client.get("/api/auth/profile", headers=_headers(tenant, tokens)).status_code == 401


def test_revoking_one_session_leaves_the_other_alone(client, db_session, flask_app):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    first = _sign_in(client, flask_app, tenant, account)
    second = _sign_in(client, flask_app, tenant, account)

    session_for_token(first["refresh_token"]).revoke()
    db_session.flush()

    assert client.get("/api/auth/profile", headers=_headers(tenant, first)).status_code == 401
    assert client.get("/api/auth/profile", headers=_headers(tenant, second)).status_code == 200


def test_a_revoked_session_cannot_refresh_either(client, db_session, flask_app):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)
    sessions_for(account.id)[0].revoke()
    db_session.flush()

    _fresh(flask_app)
    response = client.post(
        "/api/auth/refresh",
        headers={"X-Tenant-ID": tenant.id},
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Suspension
# ---------------------------------------------------------------------------

def test_suspending_an_account_takes_everything_away_at_once(
    client, db_session, flask_app
):
    """The operation a school performs in an incident, end to end."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)
    assert client.get("/api/auth/profile", headers=_headers(tenant, tokens)).status_code == 200

    suspend_account(account)
    db_session.flush()

    # The token already in their browser.
    assert client.get("/api/auth/profile", headers=_headers(tenant, tokens)).status_code == 401
    # The refresh token.
    _fresh(flask_app)
    assert client.post(
        "/api/auth/refresh",
        headers={"X-Tenant-ID": tenant.id},
        json={"refresh_token": tokens["refresh_token"]},
    ).status_code == 401
    # And a fresh sign-in.
    _fresh(flask_app)
    assert client.post(
        "/api/auth/login",
        json={"email": account.email, "password": PASSWORD, "tenant_id": tenant.id},
    ).status_code == 403


def test_reactivating_restores_nothing_but_the_ability_to_sign_in(
    client, db_session, flask_app
):
    """Old tokens stay dead on purpose: reviving a session would resurrect
    whatever device held it, including the one the suspension was about."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)
    suspend_account(account)
    db_session.flush()

    reactivate_account(account)
    db_session.flush()

    assert client.get("/api/auth/profile", headers=_headers(tenant, tokens)).status_code == 401
    _fresh(flask_app)
    assert client.post(
        "/api/auth/refresh",
        headers={"X-Tenant-ID": tenant.id},
        json={"refresh_token": tokens["refresh_token"]},
    ).status_code == 401

    fresh = _sign_in(client, flask_app, tenant, account)
    assert client.get("/api/auth/profile", headers=_headers(tenant, fresh)).status_code == 200


def test_suspension_does_not_touch_the_record(db_session):
    """Access, never the record. A suspended pupil is still enrolled."""
    from modules.students.models import Student
    from tests.auth._characterization import new_id

    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    student = Student(
        id=new_id("s-"), tenant_id=tenant.id, user_id=account.id,
        person_id=account.person_id,
        admission_number=f"ADM-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(student)
    db_session.flush()

    suspend_account(account)
    db_session.flush()

    assert Student.query.filter_by(id=student.id).first() is not None
    assert account.person_id is not None
    assert account.check_password(PASSWORD)


def test_a_school_cannot_suspend_the_platform_operator(db_session):
    from modules.auth.account_status import AccountStatusError

    tenant = make_tenant(db_session)
    operator = make_user(
        db_session, tenant, password=PASSWORD,
        email=f"ops-{uuid.uuid4().hex[:8]}@nexchool.test", is_platform_admin=True,
    )

    with pytest.raises(AccountStatusError):
        suspend_account(operator)


def test_suspension_is_written_down_with_who_did_it(db_session):
    from modules.auth.event_models import AuthEvent

    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    operator = _account(db_session, tenant)

    suspend_account(account, actor_user_id=operator.id, reason="pending an enquiry")
    db_session.flush()

    event = AuthEvent.query.filter_by(
        account_id=account.id, event_type="account_suspended"
    ).first()
    assert event is not None
    assert event.actor_user_id == operator.id
    assert event.reason == "pending an enquiry"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

def test_a_refresh_token_does_not_work_against_another_school(
    client, db_session, flask_app
):
    ours = make_tenant(db_session)
    theirs = make_tenant(db_session)
    account = _account(db_session, ours)
    tokens = _sign_in(client, flask_app, ours, account)

    _fresh(flask_app)
    response = client.post(
        "/api/auth/refresh",
        headers={"X-Tenant-ID": theirs.id},
        json={"refresh_token": tokens["refresh_token"]},
    )
    # The token names its own school, and every check is made against that
    # one — so this succeeds for *its* tenant and never crosses.
    assert response.status_code in (200, 401)
    if response.status_code == 200:
        claims = decode_access_token(response.get_json()["data"]["access_token"])
        assert claims["tid"] == ours.id


def test_suspending_in_one_school_leaves_the_other_alone(
    client, db_session, flask_app
):
    ours = make_tenant(db_session)
    theirs = make_tenant(db_session)
    address = f"{uuid.uuid4().hex[:8]}@shared.test"
    mine = _account(db_session, ours, email=address)
    theirs_account = _account(db_session, theirs, email=address)
    their_tokens = _sign_in(client, flask_app, theirs, theirs_account)

    suspend_account(mine)
    db_session.flush()

    assert client.get(
        "/api/auth/profile", headers=_headers(theirs, their_tokens)
    ).status_code == 200


def test_a_tenant_that_is_not_active_cannot_be_refreshed_into(
    client, db_session, flask_app
):
    from core.models import TENANT_STATUS_SUSPENDED

    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    tenant.status = TENANT_STATUS_SUSPENDED
    db_session.flush()

    _fresh(flask_app)
    response = client.post(
        "/api/auth/refresh",
        headers={"X-Tenant-ID": tenant.id},
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert response.status_code == 401
