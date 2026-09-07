"""Which wire a school's sign-in codes go down."""

import re
import uuid

import pytest
from sqlalchemy import CheckConstraint
from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.auth import policy
from modules.auth.policy_models import (
    CREDENTIAL_FORCE_CHANGE,
    CREDENTIAL_NO_FORCED_CHANGE,
    TenantAuthPolicy,
)
from modules.auth.services import generate_access_token
from modules.integrations.capabilities import MESSAGING_CAPABILITIES
from tests.auth._characterization import make_user
from tests.auth.test_mobile_otp import _member, _school

_CONSTRAINT_NAME = "ck_tenant_auth_policies_otp_delivery_channel"


# ---------------------------------------------------------------------------
# Fixtures and helpers
#
# Module-local, the same shape `test_mobile_otp.py` and
# `tests/test_integrations_routes.py` use — there is no shared `app` fixture,
# no `platform_admin_client`, and (until Task 7 adds the outbox and a
# WhatsApp test double) no registered WhatsApp provider to configure a school
# onto the way `configure_integration` does for SMS. Where a test below needs
# a "the school's WhatsApp works" fact, it patches `messaging_health` — the
# one seam both the delivery path and the readiness gates actually read.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reachable_redis(flask_app):
    """`request_otp` counts against the throttle before it sends anything, and
    the throttle fails closed — see `test_mobile_otp.py` for why skipping
    beats passing for the wrong reason when there is no Redis to count in."""
    import core.cache as cache

    from modules.auth.otp_throttle import clear_for_tests

    previous_url = flask_app.config.get("REDIS_URL")
    previous_pool = cache._pool
    flask_app.config["REDIS_URL"] = "redis://localhost:6379/0"
    cache._pool = None

    with flask_app.app_context():
        client = cache.redis_client()
        try:
            assert client is not None and client.ping()
        except Exception:  # noqa: BLE001
            flask_app.config["REDIS_URL"] = previous_url
            cache._pool = previous_pool
            pytest.skip("this suite needs a reachable Redis for the OTP limiter")
        clear_for_tests(tenant_id="", ip_address="127.0.0.1")

    yield
    flask_app.config["REDIS_URL"] = previous_url
    cache._pool = previous_pool


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _platform_admin(db_session, tenant):
    operator = make_user(
        db_session,
        tenant,
        password="Platform12345",
        email=f"ops-{uuid.uuid4().hex[:8]}@nexchool.test",
        is_platform_admin=True,
    )
    return {"Authorization": f"Bearer {generate_access_token(operator)}"}


def test_a_school_that_has_chosen_nothing_is_on_sms(db_session, tenant):
    """The default is what every school does today. A migration that changed
    behaviour for anybody would be the wrong kind of surprise."""
    assert policy.otp_delivery_channel(tenant.id) == "sms"


def test_an_operator_can_move_a_school_to_whatsapp(db_session, tenant):
    policy.set_otp_delivery_channel(tenant.id, "whatsapp")
    db.session.commit()
    assert policy.otp_delivery_channel(tenant.id) == "whatsapp"


def test_a_channel_this_build_cannot_deliver_is_refused(db_session, tenant):
    with pytest.raises(ValueError):
        policy.set_otp_delivery_channel(tenant.id, "carrier_pigeon")


def test_the_channel_is_in_what_the_panel_reads(db_session, tenant):
    described = policy.describe(tenant.id)
    assert described["otp_delivery_channel"] == "sms"


def test_the_database_refuses_a_channel_the_application_would_have_caught(
    db_session, tenant
):
    """The setter validates, but a script or a shell does not go through it.

    `ck_tenant_auth_policies_otp_delivery_channel` is the backstop for
    whatever bypasses `set_otp_delivery_channel` — set directly on the model
    the way a one-off script or a future code path might, skipping the
    `ValueError` the setter already covers above.
    """
    policy_row = policy.ensure_default_policy(tenant.id)
    policy_row.otp_delivery_channel = "carrier_pigeon"
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_the_constraint_matches_messaging_capabilities():
    """The database's list and the application's list must never drift.

    `ck_tenant_auth_policies_otp_delivery_channel` is a SQL literal — it
    cannot read `MESSAGING_CAPABILITIES` at runtime — so nothing but a test
    keeps them in step. Without this, adding a third messaging capability
    would silently leave the database still refusing it, and the first
    school to be moved onto it would find out from a failed OTP rather than
    from a review comment.
    """
    constraints = {
        constraint.name: constraint
        for constraint in TenantAuthPolicy.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    constraint = constraints[_CONSTRAINT_NAME]

    match = re.search(r"IN \(([^)]+)\)", str(constraint.sqltext))
    assert match, f"Could not parse values out of {constraint.sqltext!r}"
    allowed = {value.strip().strip("'") for value in match.group(1).split(",")}

    assert allowed == set(MESSAGING_CAPABILITIES)


# ---------------------------------------------------------------------------
# The channel is where a code actually goes, not just what is recorded
# ---------------------------------------------------------------------------


def test_a_code_goes_down_the_channel_the_school_chose(db_session, monkeypatch):
    """`_deliver` reads the school's chosen channel from policy — it must not
    keep sending down SMS regardless of what a school picked."""
    from modules.auth import otp
    from modules.integrations.results import STATUS_ACCEPTED, MessageSendResult

    tenant = _school(db_session, sms_working=False)
    policy.set_otp_delivery_channel(tenant.id, "whatsapp")
    db.session.commit()

    account, number = _member(db_session, tenant)

    import modules.integrations.messaging as messaging_module

    sent = []

    def _fake_send_message(
        *, tenant_id, channel, purpose, destination, variables, body=None,
        idempotency_key=None,
    ):
        sent.append(channel)
        return MessageSendResult(
            success=True,
            status=STATUS_ACCEPTED,
            provider_message_id="fake-otp-1",
            billable_units=0,
        )

    monkeypatch.setattr(messaging_module, "send_message", _fake_send_message)

    result = otp.request_otp(tenant_id=tenant.id, mobile=number)

    assert result.accepted
    assert sent == ["whatsapp"]


def test_a_school_on_whatsapp_is_not_blocked_by_a_missing_sms_provider(
    client, db_session, monkeypatch
):
    """The gate used to check SMS unconditionally, which would refuse a
    school that does not use SMS at all."""
    tenant = _school(
        db_session, sms_working=False, whatsapp_working=True, monkeypatch=monkeypatch
    )
    policy.set_otp_delivery_channel(tenant.id, "whatsapp")
    db.session.commit()

    headers = _platform_admin(db_session, tenant)
    response = client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy/methods",
        headers=headers,
        json={"method_key": "mobile_otp", "subject_kind": "student", "enabled": True},
    )

    assert response.status_code == 200


def test_a_school_still_on_sms_with_no_provider_is_still_refused(
    client, db_session, tenant
):
    """The gate did not just move from "always SMS" to "always ready" — a
    school that never touched the channel setting is still SMS by default,
    and still has no provider to send SMS through."""
    headers = _platform_admin(db_session, tenant)

    response = client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy/methods",
        headers=headers,
        json={"method_key": "mobile_otp", "subject_kind": "student", "enabled": True},
    )

    assert response.status_code == 400
    assert "sms" in response.get_json()["details"]["method_key"].lower()


# ---------------------------------------------------------------------------
# Changing the channel while the method is live
# ---------------------------------------------------------------------------


def test_moving_a_live_school_onto_a_channel_with_no_provider_is_refused(
    client, db_session, tenant
):
    policy.set_method(tenant.id, "staff", "mobile_otp", enabled=True)
    db.session.commit()

    headers = _platform_admin(db_session, tenant)
    response = client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy",
        headers=headers,
        json={"otp_delivery_channel": "whatsapp"},
    )

    assert response.status_code == 400


def test_a_refused_channel_change_does_not_partially_apply(
    client, db_session, tenant
):
    """A request naming both a channel and another field is refused, or
    applied, as one unit — not the channel refused while the other field
    quietly went through."""
    policy.set_method(tenant.id, "staff", "mobile_otp", enabled=True)
    db.session.commit()
    original_channel = policy.otp_delivery_channel(tenant.id)
    assert policy.student_credential_policy(tenant.id) == CREDENTIAL_FORCE_CHANGE

    headers = _platform_admin(db_session, tenant)
    response = client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy",
        headers=headers,
        json={
            "otp_delivery_channel": "whatsapp",
            "student_credential_policy": CREDENTIAL_NO_FORCED_CHANGE,
        },
    )

    assert response.status_code == 400
    assert policy.otp_delivery_channel(tenant.id) == original_channel
    # The field sent alongside the refused one did not sneak through — the
    # whole request was one transaction, and `db.session.rollback()` inside
    # the guard undid both, not just the one that failed its own check.
    assert policy.student_credential_policy(tenant.id) == CREDENTIAL_FORCE_CHANGE


def test_a_school_not_using_mobile_otp_may_still_pre_select_a_channel(
    client, db_session, tenant
):
    """Nothing is live yet, so nothing can be stranded — the guard only
    applies once `mobile_otp` is actually switched on somewhere."""
    headers = _platform_admin(db_session, tenant)

    response = client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy",
        headers=headers,
        json={"otp_delivery_channel": "whatsapp"},
    )

    assert response.status_code == 200
    assert policy.otp_delivery_channel(tenant.id) == "whatsapp"
