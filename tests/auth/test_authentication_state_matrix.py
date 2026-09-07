"""Phase 8 — the state matrix: every way an account can be, and what happens.

The point of a matrix rather than a scatter of cases is that the gaps show.
Each state below is one row of §33, asserted against a live request rather
than reasoned about.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from core.models import TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED
from core.school_time import utc_now
from modules.auth.account_status import describe_access, reactivate_account, suspend_account
from modules.auth.policy import (
    ensure_default_policy,
    end_sessions_opened_with,
    set_method,
)
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


def _account(db_session, tenant, **kwargs):
    account = make_user(db_session, tenant, password=PASSWORD, **kwargs)
    grant_permissions(db_session, tenant, account, ("student.read.self",))
    return account


def _sign_in(client, flask_app, tenant, account, expect=200):
    _fresh(flask_app)
    response = client.post("/api/auth/login", json={
        "email": account.email, "password": PASSWORD, "tenant_id": tenant.id})
    assert response.status_code == expect, response.get_json()
    return response.get_json().get("data") if expect == 200 else None


def _call(client, tenant, tokens):
    return client.get("/api/auth/profile", headers={
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-Tenant-ID": tenant.id})


def _refresh(client, flask_app, tenant, tokens):
    _fresh(flask_app)
    return client.post("/api/auth/refresh",
                       headers={"X-Tenant-ID": tenant.id},
                       json={"refresh_token": tokens["refresh_token"]})


# ---------------------------------------------------------------------------
# §33 — the matrix
# ---------------------------------------------------------------------------

def test_healthy_account_can_do_all_three(client, db_session, flask_app):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    assert _call(client, tenant, tokens).status_code == 200
    assert _refresh(client, flask_app, tenant, tokens).status_code == 200
    _sign_in(client, flask_app, tenant, account)


def test_locked_account_cannot_sign_in_but_a_live_session_continues(
    client, db_session, flask_app
):
    """A lock is a brake on guessing, not a revocation. Someone already inside
    is not thrown out because a stranger typed their address wrong five times
    — otherwise the lock would itself be a denial-of-service."""
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    account.login_locked_until = utc_now() + timedelta(minutes=15)
    db_session.flush()

    _fresh(flask_app)
    assert client.post("/api/auth/login", json={
        "email": account.email, "password": PASSWORD,
        "tenant_id": tenant.id}).status_code == 401
    assert _call(client, tenant, tokens).status_code == 200
    assert _refresh(client, flask_app, tenant, tokens).status_code == 200


def test_suspended_account_can_do_nothing(client, db_session, flask_app):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    suspend_account(account)
    db_session.flush()

    assert _call(client, tenant, tokens).status_code == 401
    assert _refresh(client, flask_app, tenant, tokens).status_code == 401
    _sign_in(client, flask_app, tenant, account, expect=403)


def test_reactivated_account_may_sign_in_and_only_that(
    client, db_session, flask_app
):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)
    suspend_account(account)
    db_session.flush()
    reactivate_account(account)
    db_session.flush()

    assert _call(client, tenant, tokens).status_code == 401
    assert _refresh(client, flask_app, tenant, tokens).status_code == 401
    _sign_in(client, flask_app, tenant, account)


def test_deleted_account_can_do_nothing(client, db_session, flask_app):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    account.deleted_at = utc_now()
    db_session.flush()

    assert _call(client, tenant, tokens).status_code == 401
    assert _refresh(client, flask_app, tenant, tokens).status_code == 401
    _sign_in(client, flask_app, tenant, account, expect=401)


def test_suspended_school_stops_everyone_in_it(client, db_session, flask_app):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    tenant.status = TENANT_STATUS_SUSPENDED
    db_session.flush()

    assert _refresh(client, flask_app, tenant, tokens).status_code == 401
    _fresh(flask_app)
    assert client.post("/api/auth/login", json={
        "email": account.email, "password": PASSWORD,
        "tenant_id": tenant.id}).status_code in (401, 403)


def test_a_revoked_session_is_the_end_of_that_session_only(
    client, db_session, flask_app
):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    first = _sign_in(client, flask_app, tenant, account)
    second = _sign_in(client, flask_app, tenant, account)

    from modules.auth.tokens import session_for_token

    session_for_token(first["refresh_token"]).revoke()
    db_session.flush()

    assert _call(client, tenant, first).status_code == 401
    assert _refresh(client, flask_app, tenant, first).status_code == 401
    assert _call(client, tenant, second).status_code == 200
    _sign_in(client, flask_app, tenant, account)


# ---------------------------------------------------------------------------
# §27 — a method being switched off
# ---------------------------------------------------------------------------

def test_disabling_a_method_signs_out_the_people_who_used_it(
    client, db_session, flask_app
):
    """Otherwise the door is shut on the screen and open for everybody already
    through it — for as long as a session lives."""
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    account = _account(db_session, tenant)
    db_session.flush()
    tokens = _sign_in(client, flask_app, tenant, account)
    assert _call(client, tenant, tokens).status_code == 200

    for kind in ("staff", "student", "parent"):
        set_method(tenant.id, kind, "email_password", enabled=False)
    db_session.flush()

    assert _call(client, tenant, tokens).status_code == 401
    assert _refresh(client, flask_app, tenant, tokens).status_code == 401


def test_disabling_one_method_leaves_the_other_method_signed_in(
    client, db_session, flask_app
):
    """The decision is about a way in, not about a person."""
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    account = _account(db_session, tenant)
    db_session.flush()
    tokens = _sign_in(client, flask_app, tenant, account)

    ended = end_sessions_opened_with(tenant.id, "mobile_pin")

    assert ended == 0
    assert _call(client, tenant, tokens).status_code == 200


def test_disabling_a_method_is_written_down(client, db_session, flask_app):
    from modules.auth.event_models import AuthEvent

    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    account = _account(db_session, tenant)
    operator = _account(db_session, tenant)
    db_session.flush()
    _sign_in(client, flask_app, tenant, account)

    for kind in ("staff", "student", "parent"):
        set_method(tenant.id, kind, "email_password", enabled=False,
                   updated_by_user_id=operator.id)
    db_session.flush()

    event = AuthEvent.query.filter_by(
        account_id=account.id, event_type="session_ended_by_policy"
    ).first()
    assert event is not None
    assert event.reason == "method_disabled"
    assert event.actor_user_id == operator.id


def test_a_school_disabling_a_method_does_not_reach_another_school(
    client, db_session, flask_app
):
    ours = make_tenant(db_session)
    theirs = make_tenant(db_session)
    ensure_default_policy(ours.id)
    ensure_default_policy(theirs.id)
    mine = _account(db_session, ours)
    yours = _account(db_session, theirs)
    db_session.flush()
    _sign_in(client, flask_app, ours, mine)
    their_tokens = _sign_in(client, flask_app, theirs, yours)

    for kind in ("staff", "student", "parent"):
        set_method(ours.id, kind, "email_password", enabled=False)
    db_session.flush()

    assert _call(client, theirs, their_tokens).status_code == 200


def test_re_enabling_does_not_bring_the_old_sessions_back(
    client, db_session, flask_app
):
    """Same reasoning as reactivation: a revocation is not undone by changing
    your mind about the rule that caused it."""
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    account = _account(db_session, tenant)
    db_session.flush()
    tokens = _sign_in(client, flask_app, tenant, account)

    for kind in ("staff", "student", "parent"):
        set_method(tenant.id, kind, "email_password", enabled=False)
    db_session.flush()
    for kind in ("staff", "student", "parent"):
        set_method(tenant.id, kind, "email_password", enabled=True)
    db_session.flush()

    assert _call(client, tenant, tokens).status_code == 401
    _sign_in(client, flask_app, tenant, account)


# ---------------------------------------------------------------------------
# §28 — maintenance, which is not the same as suspension
# ---------------------------------------------------------------------------

def test_maintenance_stops_new_sign_ins_and_lets_the_signed_in_carry_on(
    client, db_session, flask_app, monkeypatch
):
    """Maintenance is an availability control, not a security one. Ending live
    sessions during a deploy would sign out a whole school to protect nothing;
    the refusal that matters — a suspended school — is asserted above."""
    import modules.auth.pipeline as pipeline

    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    monkeypatch.setattr(
        pipeline.AuthenticationService, "_in_maintenance", lambda self: True
    )

    _fresh(flask_app)
    assert client.post("/api/auth/login", json={
        "email": account.email, "password": PASSWORD,
        "tenant_id": tenant.id}).status_code == 503
    assert _call(client, tenant, tokens).status_code == 200
    assert _refresh(client, flask_app, tenant, tokens).status_code == 200


# ---------------------------------------------------------------------------
# What an administrator is shown
# ---------------------------------------------------------------------------

def test_the_access_summary_never_carries_a_secret(client, db_session, flask_app):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    tokens = _sign_in(client, flask_app, tenant, account)

    summary = describe_access(account)
    flat = repr(summary)

    assert summary["active_sessions"] == 1
    assert summary["is_suspended"] is False
    assert PASSWORD not in flat
    assert tokens["refresh_token"] not in flat
    assert tokens["access_token"] not in flat
    assert "password_hash" not in flat
    assert "token_hash" not in flat


def test_the_access_summary_follows_the_account(client, db_session, flask_app):
    tenant = make_tenant(db_session)
    account = _account(db_session, tenant)
    _sign_in(client, flask_app, tenant, account)
    _sign_in(client, flask_app, tenant, account)

    assert describe_access(account)["active_sessions"] == 2

    suspend_account(account)
    db_session.flush()
    summary = describe_access(account)

    assert summary["is_suspended"] is True
    assert summary["active_sessions"] == 0
