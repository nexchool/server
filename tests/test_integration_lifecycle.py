"""An operator must not be able to leave a school half-broken."""

import pytest

from core.database import db
from modules.auth import policy
from modules.integrations.services import (
    IntegrationConfigurationError,
    configure_integration,
    set_integration_status,
)


@pytest.fixture
def enabled_fake_sms(db_session, tenant):
    """A school configured onto the SMS test double, enabled."""
    configure_integration(
        tenant.id,
        capability="sms",
        provider_key="fake_sms",
        configuration={"templates": {"authentication_otp": "test-template-1"}},
    )
    set_integration_status(tenant.id, capability="sms", status="enabled")
    db.session.commit()


@pytest.fixture
def enabled_fake_whatsapp(db_session, tenant):
    """A school configured onto the WhatsApp test double, enabled."""
    configure_integration(
        tenant.id,
        capability="whatsapp",
        provider_key="fake_whatsapp",
        configuration={"templates": {"authentication_otp": "test-whatsapp-template"}},
    )
    set_integration_status(tenant.id, capability="whatsapp", status="enabled")
    db.session.commit()


@pytest.fixture
def otp_enabled_for_students(db_session, tenant):
    """`mobile_otp` switched on for students, on this school's default (SMS) channel."""
    policy.ensure_default_policy(tenant.id)
    policy.set_method(tenant.id, "student", "mobile_otp", enabled=True)
    db.session.commit()


def test_disabling_a_depended_on_integration_is_refused(
    flask_app, tenant, enabled_fake_sms, otp_enabled_for_students
):
    """Otherwise the school keeps showing an OTP button whose codes will
    never arrive, with nothing anywhere saying so."""
    with pytest.raises(IntegrationConfigurationError) as raised:
        set_integration_status(tenant.id, capability="sms", status="disabled")
    assert "mobile_otp" in str(raised.value)


def test_disabling_is_allowed_once_the_method_is_off(
    flask_app, tenant, enabled_fake_sms, otp_enabled_for_students
):
    policy.set_method(tenant.id, "student", "mobile_otp", enabled=False)
    db.session.commit()

    set_integration_status(tenant.id, capability="sms", status="disabled")


def test_a_channel_a_school_does_not_use_is_not_a_dependency(
    flask_app, tenant, enabled_fake_sms, enabled_fake_whatsapp, otp_enabled_for_students
):
    """The school is on SMS. Disabling its unused WhatsApp breaks nothing."""
    set_integration_status(tenant.id, capability="whatsapp", status="disabled")
