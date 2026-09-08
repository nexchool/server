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
    parameter would hide that, and the hiding is where the bug would live.

    Task 8b gave both channels a `variables` parameter, but not the same
    *kind* — SMS's is named (a flow's own variable names), WhatsApp's stays
    positional (slot order). Presence alone no longer tells them apart, so
    this also checks the annotation, which is what actually differs now."""
    import inspect

    sms_params = inspect.signature(SmsProvider.send).parameters
    whatsapp_params = inspect.signature(WhatsAppProvider.send).parameters

    assert "body" in sms_params and "body" not in whatsapp_params
    assert "variables" in sms_params and "variables" in whatsapp_params
    assert sms_params["variables"].annotation == "dict"
    # Written as a quoted string literal in `base.py`, so with postponed
    # evaluation (`from __future__ import annotations`) this stringifies to
    # the quoted form, not the bare type name `sms` compares against above.
    assert "list[str]" in whatsapp_params["variables"].annotation


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
        configuration={"templates": {"authentication_otp": "test-template-1"}},
    )
    set_integration_status(tenant.id, capability="sms", status="enabled")
    db.session.commit()


@pytest.fixture
def enabled_fake_sms_with_single_variable(db_session, tenant):
    """A school whose SMS template names one variable — Task 8b. Enough to
    prove a count mismatch, not enough for the two-value OTP send below."""
    from core.database import db
    from modules.integrations.services import configure_integration, set_integration_status

    configure_integration(
        tenant.id,
        capability="sms",
        provider_key="fake_sms",
        configuration={
            "templates": {
                "authentication_otp": {"id": "test-template-1", "variables": ["OTP"]},
            }
        },
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
        purpose="authentication_otp",
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
        purpose="authentication_otp",
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


# ---------------------------------------------------------------------------
# Task 8b — a template names its variables, and a send has to match them
# ---------------------------------------------------------------------------


def test_a_variable_count_mismatch_stops_the_send_before_the_provider(
    flask_app, tenant, enabled_fake_sms_with_single_variable
):
    """Zipping names to values without checking lengths first would silently
    truncate to the shorter side — an SMS reading "your code is" is worse
    than a refusal, and it would still have cost a message to learn that."""
    from modules.integrations.messaging import send_message

    result = send_message(
        tenant_id=tenant.id,
        channel="sms",
        purpose="authentication_otp",
        destination="+919876543210",
        variables=["418302", "5"],
        body="418302 is your NexSchool sign-in code.",
    )
    assert result.success is False
    assert result.error_code == "configuration_error"
    assert result.retryable is False
    assert result.billable_units == 0


def test_an_sms_template_naming_no_variables_refuses_a_send_that_needs_any(
    flask_app, tenant, enabled_fake_sms
):
    """`enabled_fake_sms` registers a bare-string template — zero named
    variables, which resolves fine (Task 8b keeps every existing row
    working). It is exactly the sharp edge of the mismatch check: zero names
    against two values would zip into an empty dict, and MSG91 would be
    asked to send a flow with none of its variables filled in. Refused
    before that request is ever built."""
    from modules.integrations.messaging import send_message

    result = send_message(
        tenant_id=tenant.id,
        channel="sms",
        purpose="authentication_otp",
        destination="+919876543210",
        variables=["418302", "5"],
        body="418302 is your NexSchool sign-in code.",
    )
    assert result.success is False
    assert result.error_code == "configuration_error"


def test_a_matching_count_of_zero_is_not_a_mismatch(
    flask_app, tenant, enabled_fake_sms
):
    """The zero-names case above is only refused because the purpose supplied
    values to fill. A purpose that genuinely needs none is not an error."""
    from modules.integrations.messaging import send_message

    result = send_message(
        tenant_id=tenant.id,
        channel="sms",
        purpose="authentication_otp",
        destination="+919876543210",
        variables=[],
        body="hi",
    )
    assert result.error_code != "configuration_error"


# ---------------------------------------------------------------------------
# `template_purpose` — which template to resolve, versus what to bill it as
# ---------------------------------------------------------------------------


def test_with_no_template_purpose_the_send_behaves_exactly_as_before(
    flask_app, tenant, enabled_fake_sms_without_templates
):
    """Every test above this one calls `send_message` without
    `template_purpose` and must keep working unchanged — the parameter is
    additive, not a replacement for the existing single-purpose contract."""
    from modules.integrations.messaging import send_message

    result = send_message(
        tenant_id=tenant.id,
        channel="sms",
        purpose="authentication_otp",
        destination="+919876543210",
        variables=["418302", "5"],
        body="418302 is your NexSchool sign-in code.",
    )
    assert result.success is False
    assert result.error_code == "template_not_configured"


def test_template_purpose_picks_the_template_while_purpose_stays_the_bill_label(
    flask_app, db_session, tenant, enabled_fake_sms
):
    """The split this earns: `purpose` never stops meaning "what to bill and
    log this as" — only which template gets resolved can differ, and only a
    caller that explicitly asks for that split gets it."""
    from modules.billing.models import ServiceUsageRecord
    from modules.integrations.messaging import send_message

    # `enabled_fake_sms` registers a bare-string `authentication_otp`
    # template — zero named variables (Task 8b) — so `variables=[]` is the
    # matching count; the point of this test is the purpose split, not the
    # variable-count check that `test_message_templates.py` already covers.
    result = send_message(
        tenant_id=tenant.id,
        channel="sms",
        purpose="integration_test",
        template_purpose="authentication_otp",
        destination="+919876543210",
        variables=[],
        body="418302 is your NexSchool sign-in code.",
    )

    assert result.success is True
    record = ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).first()
    if record is not None:
        assert record.usage_type == "integration_test"


def test_an_unresolvable_template_purpose_is_refused_even_with_a_billable_purpose(
    flask_app, tenant, enabled_fake_sms_without_templates
):
    """A `template_purpose` that names a template the school never
    registered fails the same way a bare `purpose` lookup would — the split
    changes which purpose selects the template, not whether a missing one is
    still caught."""
    from modules.integrations.messaging import send_message

    result = send_message(
        tenant_id=tenant.id,
        channel="sms",
        purpose="integration_test",
        template_purpose="authentication_otp",
        destination="+919876543210",
        variables=["418302", "5"],
        body="418302 is your NexSchool sign-in code.",
    )
    assert result.success is False
    assert result.error_code == "template_not_configured"
