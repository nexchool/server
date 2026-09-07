"""The capability layer, once there is more than one channel in it."""

import pytest

from modules.integrations import capabilities
from modules.integrations.base import SmsProvider, WhatsAppProvider
from modules.integrations.registry import registry


def test_whatsapp_is_a_capability_this_build_has():
    assert capabilities.CAPABILITY_WHATSAPP in capabilities.CAPABILITIES
    assert capabilities.CAPABILITY_LABELS[capabilities.CAPABILITY_WHATSAPP]


def test_the_two_channels_are_grouped_as_messaging():
    assert set(capabilities.MESSAGING_CAPABILITIES) == {
        capabilities.CAPABILITY_SMS,
        capabilities.CAPABILITY_WHATSAPP,
    }


def test_a_whatsapp_provider_declares_its_capability_without_being_told():
    assert WhatsAppProvider.capability == capabilities.CAPABILITY_WHATSAPP
    assert SmsProvider.capability == capabilities.CAPABILITY_SMS


def test_the_two_send_signatures_differ_because_the_channels_do():
    """WhatsApp never receives a body. Collapsing these into one `message`
    parameter would hide that, and the hiding is where the bug would live."""
    import inspect

    sms = set(inspect.signature(SmsProvider.send).parameters)
    whatsapp = set(inspect.signature(WhatsAppProvider.send).parameters)
    assert "body" in sms and "body" not in whatsapp
    assert "variables" in whatsapp and "variables" not in sms


def test_the_registry_still_validates_with_a_second_capability():
    registry.validate()


# ---------------------------------------------------------------------------
# One send path for both channels
# ---------------------------------------------------------------------------
#
# Fixtures below are module-local rather than in `tests/conftest.py`: they
# configure a tenant onto the SMS test double the same way
# `tests/test_integrations_routes.py` does inline in its own tests, via
# `configure_integration` / `set_integration_status` against `db_session` and
# `tenant`. There is no shared `app`/`enabled_fake_sms` fixture anywhere else
# to reuse.


@pytest.fixture
def enabled_fake_sms(db_session, tenant):
    """A school configured onto the SMS test double, with a template."""
    from core.database import db
    from modules.integrations.services import configure_integration, set_integration_status

    configure_integration(
        tenant.id,
        capability="sms",
        provider_key="fake_sms",
        configuration={"templates": {"login_otp": "test-template-1"}},
    )
    set_integration_status(tenant.id, capability="sms", status="enabled")
    db.session.commit()


@pytest.fixture
def enabled_fake_sms_without_templates(db_session, tenant):
    """The same school, configured with no template registered at all."""
    from core.database import db
    from modules.integrations.services import configure_integration, set_integration_status

    configure_integration(
        tenant.id, capability="sms", provider_key="fake_sms", configuration={}
    )
    set_integration_status(tenant.id, capability="sms", status="enabled")
    db.session.commit()


def test_a_send_on_an_unconfigured_channel_returns_a_result_not_an_exception(
    flask_app, tenant
):
    """A caller deciding what to do next should not have to catch anything to
    find out that a school has no provider."""
    from modules.integrations.messaging import send_message

    result = send_message(
        tenant_id=tenant.id,
        channel="whatsapp",
        purpose="login_otp",
        destination="+919876543210",
        variables=["418302", "5"],
    )
    assert result.success is False
    assert result.error_code == "configuration_error"
    assert result.billable_units == 0


def test_a_missing_template_stops_the_send_before_the_provider(
    flask_app, tenant, enabled_fake_sms_without_templates
):
    from modules.integrations.messaging import send_message

    result = send_message(
        tenant_id=tenant.id,
        channel="sms",
        purpose="login_otp",
        destination="+919876543210",
        variables=["418302", "5"],
        body="418302 is your NexSchool sign-in code.",
    )
    assert result.success is False
    assert result.error_code == "template_not_configured"
    assert result.billable_units == 0


def test_the_channels_resolve_independently(flask_app, tenant, enabled_fake_sms):
    """A school with SMS working and no WhatsApp must not have its SMS
    reported as broken, and vice versa."""
    from modules.integrations.messaging import messaging_health

    assert messaging_health(tenant.id, "sms").ready is True
    assert messaging_health(tenant.id, "whatsapp").ready is False
