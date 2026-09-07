"""Phase 1c — seeing and ending the sessions an account has open.

Before this, a session could be created and could expire, and everything in
between was invisible: nobody could ask what an account had open, and the only
way to end one was a side effect of changing a password. (`logout`'s
unauthenticated cookie branch used to end *every* session for whoever the
token named; Phase 8 narrowed it to one, so signing out everywhere is now
only reachable here, authenticated.)

Two audiences share one model here, and the tests are grouped that way: a
person managing their own sessions needs nothing but a valid token, while an
operator managing somebody else's needs `user.manage` and can only reach
accounts inside their own school.

The assertions worth reading first:

  * `test_a_listing_never_carries_the_token_that_opened_the_session` — a
    refresh token *is* the session; listing one would hand over all of them.
  * `test_a_session_id_from_another_account_is_simply_not_found` — revocation
    is matched by id **and** account.
  * `test_another_school_cannot_end_this_school_s_sessions`.
"""

from __future__ import annotations

import pytest

from core.database import db
from modules.auth.event_models import AuthEvent
from modules.auth.models import Session, User
from modules.auth.services import generate_access_token
from modules.auth.session_admin import list_sessions, revoke_all_sessions
from tests.auth._characterization import grant_permissions, make_tenant, make_user, new_id


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _headers_for(user, tenant):
    return {
        "Authorization": f"Bearer {generate_access_token(user)}",
        "X-Tenant-ID": tenant.id,
    }


def _member(db_session, tenant, *, permissions=("student.read.all",)):
    user = make_user(db_session, tenant, password="Member12345")
    grant_permissions(db_session, tenant, user, permissions)
    return user, _headers_for(user, tenant)


def _open_session(db_session, tenant, account, **overrides):
    fields = dict(
        id=new_id("sess-"),
        tenant_id=tenant.id,
        user_id=account.id,
        refresh_token=new_id("rt-"),
        login_method="email_password",
        client_surface="admin_web",
        ip_address="203.0.113.7",
        user_agent="Chrome on a school laptop",
    )
    fields.update(overrides)
    session = Session(**fields)
    db_session.add(session)
    db_session.flush()
    return session


# ---------------------------------------------------------------------------
# My own sessions
# ---------------------------------------------------------------------------

def test_i_can_see_where_i_am_signed_in(client, db_session):
    tenant = make_tenant(db_session)
    user, headers = _member(db_session, tenant)
    _open_session(db_session, tenant, user)
    _open_session(db_session, tenant, user, client_surface="mobile")

    response = client.get("/api/auth/sessions", headers=headers)

    assert response.status_code == 200
    surfaces = {row["client_surface"] for row in response.get_json()["data"]["sessions"]}
    assert surfaces == {"admin_web", "mobile"}


def test_a_listing_never_carries_the_token_that_opened_the_session(client, db_session):
    tenant = make_tenant(db_session)
    user, headers = _member(db_session, tenant)
    session = _open_session(db_session, tenant, user)

    body = client.get("/api/auth/sessions", headers=headers).get_json()

    assert session.refresh_token not in repr(body)
    assert "refresh_token" not in repr(body)


def test_a_revoked_session_is_out_of_the_listing_by_default(client, db_session):
    tenant = make_tenant(db_session)
    user, headers = _member(db_session, tenant)
    live = _open_session(db_session, tenant, user)
    gone = _open_session(db_session, tenant, user)
    gone.revoke()
    db_session.flush()

    listed = client.get("/api/auth/sessions", headers=headers).get_json()["data"]["sessions"]

    assert [row["id"] for row in listed] == [live.id]
    assert gone.id in {row["id"] for row in list_sessions(user, include_revoked=True)}


def test_i_can_sign_myself_out_of_one_place(client, db_session):
    tenant = make_tenant(db_session)
    user, headers = _member(db_session, tenant)
    keep = _open_session(db_session, tenant, user)
    drop = _open_session(db_session, tenant, user)

    response = client.delete(f"/api/auth/sessions/{drop.id}", headers=headers)

    assert response.status_code == 200
    assert Session.query.filter_by(id=drop.id).first().revoked is True
    assert Session.query.filter_by(id=keep.id).first().revoked is False


def test_a_session_id_from_another_account_is_simply_not_found(client, db_session):
    """Revocation is matched by id *and* account, so this cannot reach across."""
    tenant = make_tenant(db_session)
    mine, headers = _member(db_session, tenant)
    theirs, _ = _member(db_session, tenant)
    their_session = _open_session(db_session, tenant, theirs)

    response = client.delete(f"/api/auth/sessions/{their_session.id}", headers=headers)

    assert response.status_code == 404
    assert Session.query.filter_by(id=their_session.id).first().revoked is False


def test_revoking_a_session_twice_is_not_an_error_the_second_time_around(client, db_session):
    """A revoked session and one that never existed look the same from outside."""
    tenant = make_tenant(db_session)
    user, headers = _member(db_session, tenant)
    session = _open_session(db_session, tenant, user)

    first = client.delete(f"/api/auth/sessions/{session.id}", headers=headers)
    second = client.delete(f"/api/auth/sessions/{session.id}", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 404


def test_signing_out_everywhere_ends_every_session(client, db_session):
    tenant = make_tenant(db_session)
    user, headers = _member(db_session, tenant)
    for _ in range(3):
        _open_session(db_session, tenant, user)

    response = client.delete("/api/auth/sessions", headers=headers)

    assert response.get_json()["data"]["revoked"] == 3
    assert Session.query.filter_by(user_id=user.id, revoked=False).count() == 0


def test_signing_out_everywhere_can_spare_the_one_i_am_speaking_from(client, db_session):
    """Which session is mine comes from the access token, not from a header.

    It used to be found by looking up the caller's refresh token, sent along
    on every request. No client sends it any more — a token that may be spent
    once cannot ride on everything — so the access token names its own session
    in a `sid` claim and nothing has to be looked up.
    """
    tenant = make_tenant(db_session)
    user, _ = _member(db_session, tenant)
    here = _open_session(db_session, tenant, user)
    _open_session(db_session, tenant, user)

    headers = {
        "Authorization": f"Bearer {generate_access_token(user, session_id=here.id)}",
        "X-Tenant-ID": tenant.id,
    }

    response = client.delete("/api/auth/sessions", headers=headers)

    assert response.get_json()["data"]["revoked"] == 1
    assert Session.query.filter_by(id=here.id).first().revoked is False


def test_signing_out_everywhere_spares_nothing_when_the_session_is_unknown(
    client, db_session
):
    """A token from before sessions were named cannot say which one is its
    own, and the honest answer is to end them all rather than to guess."""
    tenant = make_tenant(db_session)
    user, headers = _member(db_session, tenant)
    _open_session(db_session, tenant, user)
    _open_session(db_session, tenant, user)

    response = client.delete("/api/auth/sessions", headers=headers)

    assert response.get_json()["data"]["revoked"] == 2


def test_an_unauthenticated_caller_sees_no_sessions(client, db_session):
    tenant = make_tenant(db_session)
    user, _ = _member(db_session, tenant)
    _open_session(db_session, tenant, user)

    response = client.get("/api/auth/sessions", headers={"X-Tenant-ID": tenant.id})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Somebody else's sessions
# ---------------------------------------------------------------------------

def test_an_operator_can_see_and_end_a_member_s_sessions(client, db_session):
    tenant = make_tenant(db_session)
    _, operator_headers = _member(db_session, tenant, permissions=("user.manage",))
    member, _ = _member(db_session, tenant)
    session = _open_session(db_session, tenant, member)

    listed = client.get(
        f"/api/auth/accounts/{member.id}/sessions", headers=operator_headers
    )
    revoked = client.delete(
        f"/api/auth/accounts/{member.id}/sessions/{session.id}", headers=operator_headers
    )

    assert [row["id"] for row in listed.get_json()["data"]["sessions"]] == [session.id]
    assert revoked.status_code == 200
    assert Session.query.filter_by(id=session.id).first().revoked is True


def test_being_signed_in_is_not_authority_over_somebody_else(client, db_session):
    tenant = make_tenant(db_session)
    _, headers = _member(db_session, tenant)
    member, _ = _member(db_session, tenant)
    session = _open_session(db_session, tenant, member)

    listed = client.get(f"/api/auth/accounts/{member.id}/sessions", headers=headers)
    revoked = client.delete(
        f"/api/auth/accounts/{member.id}/sessions/{session.id}", headers=headers
    )

    assert listed.status_code == 403
    assert revoked.status_code == 403
    assert Session.query.filter_by(id=session.id).first().revoked is False


def test_another_school_cannot_end_this_school_s_sessions(client, db_session):
    ours = make_tenant(db_session)
    theirs = make_tenant(db_session)
    _, our_headers = _member(db_session, ours, permissions=("user.manage",))
    their_member, _ = _member(db_session, theirs)
    their_session = _open_session(db_session, theirs, their_member)

    listed = client.get(
        f"/api/auth/accounts/{their_member.id}/sessions", headers=our_headers
    )
    revoked = client.delete(
        f"/api/auth/accounts/{their_member.id}/sessions", headers=our_headers
    )

    assert listed.status_code == 404
    assert revoked.status_code == 404
    assert Session.query.filter_by(id=their_session.id).first().revoked is False


def test_a_school_cannot_end_a_platform_operator_s_session(client, db_session):
    """A platform admin is not a member of the school they are working in."""
    tenant = make_tenant(db_session)
    _, headers = _member(db_session, tenant, permissions=("user.manage",))
    operator = make_user(
        db_session, tenant, password="Platform12345", is_platform_admin=True
    )
    session = _open_session(db_session, tenant, operator)

    response = client.delete(
        f"/api/auth/accounts/{operator.id}/sessions", headers=headers
    )

    assert response.status_code == 404
    assert Session.query.filter_by(id=session.id).first().revoked is False


# ---------------------------------------------------------------------------
# What gets written down
# ---------------------------------------------------------------------------

def test_ending_a_session_is_written_down_with_who_did_it(client, db_session):
    tenant = make_tenant(db_session)
    operator, operator_headers = _member(db_session, tenant, permissions=("user.manage",))
    member, _ = _member(db_session, tenant)
    session = _open_session(db_session, tenant, member)

    client.delete(
        f"/api/auth/accounts/{member.id}/sessions/{session.id}", headers=operator_headers
    )

    events = AuthEvent.query.filter_by(account_id=member.id).all()
    assert {event.event_type for event in events} == {"session_revoked"}
    assert events[0].actor_user_id == operator.id


def test_nothing_here_writes_down_a_secret(client, db_session):
    tenant = make_tenant(db_session)
    user, headers = _member(db_session, tenant)
    session = _open_session(db_session, tenant, user)

    client.delete(f"/api/auth/sessions/{session.id}", headers=headers)

    for event in AuthEvent.query.filter_by(account_id=user.id).all():
        row = {c.name: getattr(event, c.name) for c in event.__table__.columns}
        assert session.refresh_token not in repr(row)


def test_revoking_everything_is_recorded_even_when_nothing_was_open(db_session):
    """The operator acted; that they found nothing does not unrecord it."""
    tenant = make_tenant(db_session)
    user, _ = _member(db_session, tenant)

    revoked = revoke_all_sessions(user, actor_user_id=user.id)

    assert revoked == 0
    assert AuthEvent.query.filter_by(
        account_id=user.id, event_type="sessions_revoked_all"
    ).count() == 1
