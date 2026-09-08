"""A deliberate, real send — and the guardrails around pressing the button.

Kept apart from `test_integrations_routes.py`'s configuration tests because
this one costs money and rings a real destination: `health.py` argues at
length for why a readiness check must never send anything, and this route is
the opposite of that — an operator asking, on purpose, for one real message.
"""

from __future__ import annotations

import uuid

import pytest

from modules.auth.services import generate_access_token
from modules.integrations.services import configure_integration, set_integration_status
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
    """A school configured onto the SMS test double, enabled, with **only**
    its sign-in (OTP) template registered.

    This is deliberately the exact shape the product owner hit: a school that
    registered the one template that actually matters — the one a real person
    signs in with — and nothing else. There is no `integration_test` entry
    here on purpose: nobody registers a template for a purpose that only
    exists to be tested, and the fix under test is that the button no longer
    requires one.
    """
    from core.database import db

    configure_integration(
        tenant.id,
        capability="sms",
        provider_key="fake_sms",
        configuration={
            "templates": {
                "authentication_otp": {
                    "id": "test-template-otp",
                    "variables": ["OTP", "MINUTES"],
                },
            }
        },
    )
    set_integration_status(tenant.id, capability="sms", status="enabled")
    db.session.commit()


@pytest.fixture
def enabled_fake_sms_without_otp_template(db_session, tenant):
    """The same school, enabled, with no OTP template registered either.

    The failure that matters — an operator never having wired up the
    template a real sign-in depends on — must still be caught, loudly, by
    this button. Fixing the false failure for the common case must not turn
    this into a silent no-op for the case that is a genuine misconfiguration.
    """
    from core.database import db

    configure_integration(
        tenant.id,
        capability="sms",
        provider_key="fake_sms",
        configuration={"templates": {}},
    )
    set_integration_status(tenant.id, capability="sms", status="enabled")
    db.session.commit()


@pytest.fixture
def sms_service_configured(db_session, tenant):
    """A billing catalog entry for `sms` from `fake_sms`, so usage recorded
    against this tenant lands somewhere instead of being logged and dropped
    (see `usage_recorder.record_provider_usage`)."""
    from decimal import Decimal

    from core.database import db
    from modules.billing.constants import PRICING_METERED
    from modules.billing.services import (
        configure_tenant_service,
        upsert_provider,
        upsert_service,
    )

    upsert_provider(key="fake_sms", name="Fake SMS (tests only)")
    upsert_service(
        provider_key="fake_sms",
        key="sms",
        name="Transactional SMS",
        unit="sms",
        pricing_mode=PRICING_METERED,
        provider_unit_cost=Decimal("0.02"),
    )
    configure_tenant_service(tenant.id, service_key="sms", provider_key="fake_sms")
    db.session.commit()


def test_a_test_send_goes_through_the_otp_template_path(
    flask_app, db_session, tenant, client, enabled_fake_sms
):
    """A test that bypassed templates would prove nothing about the case
    that actually fails.

    This is the case the product owner hit: a school with only its OTP
    template registered must be able to complete a test send, because the
    test now exercises exactly that template — with a placeholder code —
    rather than one nobody would ever register.
    """
    from modules.auth.otp_message import build_otp_message
    from modules.integrations import outbox

    outbox.clear()
    headers = _platform_admin(db_session, tenant)

    response = client.post(
        f"/api/platform/tenants/{tenant.id}/integrations/sms/test-send",
        json={"destination": "+919876543210"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["sent"] is True
    sent = outbox.recent()[0]
    # Billing label stays "integration_test" even though the OTP template's
    # wording is what actually went out — see the usage-record test below.
    assert sent["purpose"] == "integration_test"
    assert sent["body"] == build_otp_message("000000")


def test_a_test_send_without_an_otp_template_is_refused_clearly(
    flask_app, db_session, tenant, client, enabled_fake_sms_without_otp_template
):
    """The failure that matters is still caught: a school that never
    registered a sign-in template gets told exactly that, not a false
    success and not a generic 500."""
    response = client.post(
        f"/api/platform/tenants/{tenant.id}/integrations/sms/test-send",
        json={"destination": "+919876543210"},
        headers=_platform_admin(db_session, tenant),
    )

    assert response.status_code == 200
    body = response.get_json()["data"]
    assert body["sent"] is False
    assert body["error_code"] == "template_not_configured"
    assert "authentication_otp" in body["error_message"]


def test_a_test_send_is_recorded_as_usage(
    flask_app, db_session, tenant, client, enabled_fake_sms, sms_service_configured
):
    from modules.billing.models import ServiceUsageRecord

    headers = _platform_admin(db_session, tenant)

    client.post(
        f"/api/platform/tenants/{tenant.id}/integrations/sms/test-send",
        json={"destination": "+919876543210"},
        headers=headers,
    )

    record = ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).first()
    assert record is not None
    assert record.usage_type == "integration_test"


def test_a_test_send_needs_a_platform_admin(
    flask_app, db_session, tenant, client, enabled_fake_sms
):
    headers = _school_user(db_session, tenant)

    response = client.post(
        f"/api/platform/tenants/{tenant.id}/integrations/sms/test-send",
        json={"destination": "+919876543210"},
        headers=headers,
    )

    assert response.status_code in (401, 403)


def test_a_test_send_is_bounded_per_actor(
    flask_app, db_session, tenant, client, enabled_fake_sms, throttling
):
    """Each press costs real money. Six in an hour is a mistake, not a test."""
    headers = _platform_admin(db_session, tenant)

    codes = [
        client.post(
            f"/api/platform/tenants/{tenant.id}/integrations/sms/test-send",
            json={"destination": "+919876543210"},
            headers=headers,
        ).status_code
        for _ in range(7)
    ]

    assert 429 in codes


def test_a_missing_destination_is_refused(
    flask_app, db_session, tenant, client, enabled_fake_sms
):
    headers = _platform_admin(db_session, tenant)

    response = client.post(
        f"/api/platform/tenants/{tenant.id}/integrations/sms/test-send",
        json={},
        headers=headers,
    )

    assert response.status_code == 400


def test_an_unrecognised_capability_is_a_client_mistake_not_a_server_error(
    flask_app, db_session, tenant, client
):
    """`capability` is a URL segment, not something this build already
    validated — unlike `sms.py`/`whatsapp.py`, which hardcode the channel.
    Before the boundary check, this reached `messaging.send_message`, which
    raises `UnknownCapability` for exactly this case, uncaught by the route —
    a 500 for what is, from the caller's side, a bad request."""
    headers = _platform_admin(db_session, tenant)

    response = client.post(
        f"/api/platform/tenants/{tenant.id}/integrations/not-a-real-capability/test-send",
        json={"destination": "+919876543210"},
        headers=headers,
    )

    assert response.status_code == 400
