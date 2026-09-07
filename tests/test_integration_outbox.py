"""What a test double sent, readable only where test doubles may run."""

from __future__ import annotations

import uuid

import pytest

from modules.auth.services import generate_access_token
from modules.integrations import outbox
from tests.auth._characterization import grant_permissions, make_tenant, make_user


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


def _school_user(db_session, tenant, *, permissions=("subscription.read",)):
    user = make_user(db_session, tenant, password="Member12345")
    grant_permissions(db_session, tenant, user, permissions)
    return {
        "Authorization": f"Bearer {generate_access_token(user)}",
        "X-Tenant-ID": tenant.id,
    }


@pytest.fixture
def enabled_fake_sms(db_session, tenant):
    """A school configured onto the SMS test double, with a template."""
    from core.database import db
    from modules.integrations.services import configure_integration, set_integration_status

    configure_integration(
        tenant.id,
        capability="sms",
        provider_key="fake_sms",
        # Named — Task 8b — so the two-value OTP send below (code, minutes)
        # matches the template's declared slots instead of being refused.
        configuration={
            "templates": {
                "authentication_otp": {"id": "test-template-1", "variables": ["OTP", "MINUTES"]},
            }
        },
    )
    set_integration_status(tenant.id, capability="sms", status="enabled")
    db.session.commit()


def test_the_buffer_is_bounded(flask_app):
    """An unbounded in-memory collection is a memory leak with a schedule."""
    outbox.clear()
    for index in range(outbox.CAPACITY + 10):
        outbox.record(
            tenant_id="t", channel="sms", destination="+91987654321",
            body=f"message {index}", purpose="authentication_otp",
        )
    assert len(outbox.recent(limit=1000)) == outbox.CAPACITY


def test_the_newest_message_is_first(flask_app):
    outbox.clear()
    outbox.record(tenant_id="t", channel="sms", destination="+9198", body="first", purpose="authentication_otp")
    outbox.record(tenant_id="t", channel="sms", destination="+9198", body="second", purpose="authentication_otp")
    assert outbox.recent()[0]["body"] == "second"


def test_a_fake_send_reaches_the_outbox(flask_app, tenant, enabled_fake_sms):
    from modules.integrations.sms import send_sms

    outbox.clear()
    send_sms(
        tenant_id=tenant.id, destination="+919876543210",
        body="418302 is your NexSchool sign-in code.",
        purpose="authentication_otp", variables=["418302", "5"],
    )
    assert "418302" in outbox.recent()[0]["body"]


def test_the_endpoint_is_absent_where_test_doubles_may_not_run(
    flask_app, db_session, client
):
    """One predicate decides whether fakes run and whether their outbox can
    be read. Two that could disagree is how a fake reaches production."""
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)
    flask_app.config["TESTING"] = False
    flask_app.config["DEBUG"] = False
    try:
        response = client.get("/api/platform/integrations/outbox", headers=headers)
        assert response.status_code == 404
    finally:
        flask_app.config["TESTING"] = True


def test_the_endpoint_needs_a_platform_admin(flask_app, db_session, client):
    tenant = make_tenant(db_session)
    headers = _school_user(db_session, tenant)
    response = client.get("/api/platform/integrations/outbox", headers=headers)
    assert response.status_code in (401, 403)
