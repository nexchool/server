"""Phase 3 — calling other people's services, without the rest of the code
knowing who.

Nothing here sends anything. There is no real vendor in this build, on
purpose: choosing an SMS company is a commercial decision nobody has taken,
and Phase 2 shipped the billing catalog empty for the same reason. What is
tested is the machinery a future OTP feature will call, and the boundaries
that make it safe to call.

The assertions worth reading first:

  * `test_a_timeout_is_never_treated_as_safe_to_retry` — the one that costs
    money if it is wrong.
  * `test_a_secret_is_never_stored_returned_or_logged` — why the database
    holds the *name* of a credential and not the credential.
  * `test_integration_never_calculates_what_anything_costs` — the billing
    boundary, asserted structurally.
  * `test_the_test_double_refuses_to_run_in_production` — because a fake
    provider that shipped would swallow messages silently.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from core.database import db
from modules.billing.services import configure_tenant_service, upsert_provider, upsert_service
from modules.billing.constants import PRICING_METERED
from modules.billing.models import ServiceUsageRecord
from modules.billing.usage import AmbiguousService, record_usage
from modules.integrations import errors
from modules.integrations.capabilities import (
    CAPABILITY_SMS,
    STATUS_DISABLED,
    STATUS_ENABLED,
)
from modules.integrations.credentials import (
    credentials_present,
    describe_references,
    is_valid_reference,
    resolve_secret,
)
from modules.integrations.errors import (
    IntegrationError,
    NoIntegrationConfigured,
    UnknownCapability,
)
from modules.integrations.models import TenantIntegration
from modules.integrations.providers.fake import (
    BEHAVIOUR_KEY,
    BEHAVIOUR_RATE_LIMITED,
    BEHAVIOUR_REJECTED,
    BEHAVIOUR_TIMEOUT,
    BEHAVIOUR_UNAVAILABLE,
    FakeSmsProvider,
)
from modules.integrations.registry import (
    ProviderRegistry,
    RegistryInvalid,
    UnknownProvider,
    registry,
)
from modules.integrations.resolver import resolve_provider
from modules.integrations.results import STATUS_ACCEPTED, MessageSendResult
from modules.integrations.services import (
    IntegrationConfigurationError,
    configure_integration,
    describe_capabilities,
    describe_tenant_integrations,
    set_integration_status,
)
from modules.integrations.sms import send_sms, sms_health
from tests.auth._characterization import make_tenant

FAKE = FakeSmsProvider.key


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _routed(db_session, tenant, *, configuration=None, status=STATUS_ENABLED):
    """A school whose SMS goes through the test double."""
    configure_integration(
        tenant.id,
        capability=CAPABILITY_SMS,
        provider_key=FAKE,
        configuration=configuration or {},
    )
    if status == STATUS_ENABLED:
        set_integration_status(
            tenant.id, capability=CAPABILITY_SMS, status=STATUS_ENABLED
        )
    db_session.flush()


def _billable(db_session, tenant, *, provider_key=None, service_key=CAPABILITY_SMS):
    """Commercial terms for SMS, so a send has somewhere to be recorded.

    Defaults to the same vendor key the integration routes to. That agreement
    is the design — `tenant_integrations.provider_key` and
    `service_providers.key` are one vendor identity — and a fixture that broke
    it would be testing a misconfiguration.
    """
    provider = upsert_provider(key=provider_key or FAKE, name="A Vendor")
    service = upsert_service(
        provider_key=provider.key,
        key=service_key,
        name="SMS",
        unit="sms",
        pricing_mode=PRICING_METERED,
        provider_unit_cost=Decimal("0.02"),
    )
    configure_tenant_service(
        tenant.id,
        service_key=service.key,
        provider_key=provider.key,
        customer_unit_price=Decimal("0.05"),
    )
    db_session.flush()
    return provider, service


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

def test_this_build_registers_no_real_vendor():
    """Not an omission. Choosing an SMS company is a decision nobody has taken,
    and a provider that appeared without one being made would be that decision
    taken by accident."""
    assert registry.keys() == [FAKE]
    assert registry.get(FAKE).is_test_double is True


def test_two_providers_under_one_key_will_not_start():
    with pytest.raises(RegistryInvalid):
        ProviderRegistry([FakeSmsProvider(), FakeSmsProvider()])


def test_a_provider_that_disagrees_with_itself_will_not_start():
    class Confused(FakeSmsProvider):
        pass

    confused = Confused()
    confused.key = "something_else"
    registry_under_test = ProviderRegistry([])
    registry_under_test._by_key = {"fake_sms": confused}

    with pytest.raises(RegistryInvalid):
        registry_under_test.validate()


def test_a_provider_claiming_an_undefined_capability_will_not_start():
    class Impossible(FakeSmsProvider):
        key = "impossible"
        capability = "telepathy"

    with pytest.raises(RegistryInvalid):
        ProviderRegistry([Impossible()])


def test_an_unknown_provider_is_refused_never_substituted(db_session):
    """A school configured onto a vendor this build lacks must be told, not
    quietly rerouted to whatever else is registered."""
    with pytest.raises(UnknownProvider):
        registry.get("a_vendor_we_do_not_have")


def test_the_registry_can_be_asked_who_does_what():
    assert [p.key for p in registry.for_capability(CAPABILITY_SMS)] == [FAKE]
    assert registry.for_capability("telepathy") == []


def test_the_capability_listing_names_credentials_but_never_values():
    listed = describe_capabilities()

    sms = [c for c in listed if c["capability"] == CAPABILITY_SMS][0]
    assert sms["providers"][0]["key"] == FAKE
    assert sms["providers"][0]["required_credentials"] == []


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def test_a_school_gets_the_provider_it_was_pointed_at(db_session):
    tenant = make_tenant(db_session)
    _routed(db_session, tenant)

    resolved = resolve_provider(tenant_id=tenant.id, capability=CAPABILITY_SMS)

    assert resolved.provider_key == FAKE
    assert resolved.integration.tenant_id == tenant.id


def test_two_schools_may_use_different_providers(db_session):
    """The reason resolution is tenant-scoped rather than global."""
    ours = make_tenant(db_session)
    theirs = make_tenant(db_session)
    _routed(db_session, ours)
    configure_integration(
        theirs.id, capability=CAPABILITY_SMS, provider_key=FAKE,
        configuration={"sender_id": "THEIRS"},
    )
    set_integration_status(theirs.id, capability=CAPABILITY_SMS, status=STATUS_ENABLED)
    db_session.flush()

    assert resolve_provider(tenant_id=ours.id, capability=CAPABILITY_SMS).configuration == {}
    assert resolve_provider(
        tenant_id=theirs.id, capability=CAPABILITY_SMS
    ).configuration == {"sender_id": "THEIRS"}


def test_a_disabled_integration_is_not_selected(db_session):
    tenant = make_tenant(db_session)
    _routed(db_session, tenant, status=STATUS_DISABLED)

    with pytest.raises(NoIntegrationConfigured):
        resolve_provider(tenant_id=tenant.id, capability=CAPABILITY_SMS)


def test_a_school_with_nothing_configured_gets_a_clean_refusal(db_session):
    tenant = make_tenant(db_session)

    with pytest.raises(NoIntegrationConfigured) as raised:
        resolve_provider(tenant_id=tenant.id, capability=CAPABILITY_SMS)

    assert raised.value.code == errors.CONFIGURATION_ERROR


def test_an_unknown_capability_is_refused(db_session):
    tenant = make_tenant(db_session)

    with pytest.raises(UnknownCapability):
        resolve_provider(tenant_id=tenant.id, capability="telepathy")


def test_resolution_without_a_school_is_refused(db_session):
    """Not a technicality: a tenant-less resolution would pick somebody's
    provider, and a confident wrong answer is worse than no answer."""
    with pytest.raises(IntegrationError):
        resolve_provider(tenant_id="", capability=CAPABILITY_SMS)


def test_one_school_cannot_resolve_another_s_integration(db_session):
    ours = make_tenant(db_session)
    theirs = make_tenant(db_session)
    _routed(db_session, theirs)

    with pytest.raises(NoIntegrationConfigured):
        resolve_provider(tenant_id=ours.id, capability=CAPABILITY_SMS)


def test_the_test_double_refuses_to_run_in_production(db_session, flask_app):
    """A fake provider that shipped would swallow messages silently."""
    tenant = make_tenant(db_session)
    _routed(db_session, tenant)

    testing, debug = flask_app.config["TESTING"], flask_app.config["DEBUG"]
    flask_app.config["TESTING"] = False
    flask_app.config["DEBUG"] = False
    try:
        with pytest.raises(IntegrationError) as raised:
            resolve_provider(tenant_id=tenant.id, capability=CAPABILITY_SMS)
    finally:
        flask_app.config["TESTING"] = testing
        flask_app.config["DEBUG"] = debug

    assert raised.value.code == errors.CONFIGURATION_ERROR
    assert "test provider" in raised.value.message


# ---------------------------------------------------------------------------
# What comes back
# ---------------------------------------------------------------------------

def test_a_send_returns_a_normalized_result(db_session):
    tenant = make_tenant(db_session)
    _routed(db_session, tenant)
    _billable(db_session, tenant)

    result = send_sms(
        tenant_id=tenant.id,
        destination="+919876500000",
        message="Your code is 123456",
        purpose="login_otp",
    )

    assert result.success is True
    assert result.status == STATUS_ACCEPTED
    assert result.provider_message_id
    assert result.operation_id
    assert result.error_code is None


def test_acceptance_is_not_called_delivery(db_session):
    """A provider taking a request is not a handset receiving a message, and a
    layer that called the first one 'delivered' would be lying in a way nobody
    could catch later."""
    tenant = make_tenant(db_session)
    _routed(db_session, tenant)
    _billable(db_session, tenant)

    result = send_sms(
        tenant_id=tenant.id, destination="+919876500000", message="hi", purpose="test"
    )

    assert result.status == STATUS_ACCEPTED
    assert result.status != "delivered"


@pytest.mark.parametrize(
    "behaviour,expected",
    [
        (BEHAVIOUR_RATE_LIMITED, errors.RATE_LIMITED),
        (BEHAVIOUR_TIMEOUT, errors.TIMEOUT),
        (BEHAVIOUR_REJECTED, errors.PROVIDER_REJECTED),
        (BEHAVIOUR_UNAVAILABLE, errors.PROVIDER_UNAVAILABLE),
    ],
)
def test_a_provider_failure_is_normalized_not_raised(db_session, behaviour, expected):
    """'The message did not send' is an outcome a caller handles, not a
    surprise it should have to catch."""
    tenant = make_tenant(db_session)
    _routed(db_session, tenant, configuration={BEHAVIOUR_KEY: behaviour})
    _billable(db_session, tenant)

    result = send_sms(
        tenant_id=tenant.id, destination="+919876500000", message="hi", purpose="test"
    )

    assert result.success is False
    assert result.error_code == expected


def test_a_timeout_is_never_treated_as_safe_to_retry():
    """The assertion that costs money if it is wrong.

    A timeout means we do not know what happened. The provider may well have
    accepted the request and sent the message; a retry would send a second one
    and charge the school twice.
    """
    assert errors.is_retryable(errors.TIMEOUT) is False
    assert errors.is_retryable(errors.RATE_LIMITED) is True
    assert errors.is_retryable(errors.PROVIDER_UNAVAILABLE) is True
    assert errors.is_retryable(errors.UNKNOWN_PROVIDER_ERROR) is False
    assert errors.is_retryable(errors.VALIDATION_ERROR) is False


def test_configuration_problems_are_told_apart_from_weather():
    """A school waiting for somebody to fix a credential should not be told
    'try again'."""
    assert errors.is_configuration_problem(errors.AUTHENTICATION_ERROR) is True
    assert errors.is_configuration_problem(errors.CONFIGURATION_ERROR) is True
    assert errors.is_configuration_problem(errors.RATE_LIMITED) is False


def test_a_school_with_no_provider_gets_a_result_not_an_exception(db_session):
    """A caller deciding whether to fall back to another channel should not
    have to catch something to find out."""
    tenant = make_tenant(db_session)

    result = send_sms(
        tenant_id=tenant.id, destination="+919876500000", message="hi", purpose="test"
    )

    assert result.success is False
    assert result.error_code == errors.CONFIGURATION_ERROR
    assert result.billable_units == 0


def test_a_provider_that_raises_does_not_become_a_server_error(db_session, monkeypatch):
    tenant = make_tenant(db_session)
    _routed(db_session, tenant)

    def explode(**kwargs):
        raise RuntimeError("the client has a bug")

    monkeypatch.setattr(registry.get(FAKE), "send", explode)

    result = send_sms(
        tenant_id=tenant.id, destination="+919876500000", message="hi", purpose="test"
    )

    assert result.success is False
    assert result.error_code == errors.UNKNOWN_PROVIDER_ERROR


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

def test_a_secret_is_never_stored_returned_or_logged(db_session, monkeypatch, caplog):
    """The database holds the *name* of an environment variable, never a value.

    So a database dump contains no provider secrets, and an API response that
    forgot to redact one has nothing to reveal.
    """
    tenant = make_tenant(db_session)
    monkeypatch.setenv("A_TEST_PROVIDER_KEY", "sk-the-actual-secret")
    configure_integration(
        tenant.id,
        capability=CAPABILITY_SMS,
        provider_key=FAKE,
        credential_references={"api_key": "A_TEST_PROVIDER_KEY"},
    )
    db_session.flush()

    row = TenantIntegration.query.filter_by(tenant_id=tenant.id).first()
    stored = {c.name: getattr(row, c.name) for c in row.__table__.columns}

    with caplog.at_level("DEBUG"):
        described = describe_tenant_integrations(tenant.id)

    assert "sk-the-actual-secret" not in repr(stored)
    assert "sk-the-actual-secret" not in repr(described)
    assert "sk-the-actual-secret" not in caplog.text
    # What an operator does get: the name, and whether it is set.
    assert described[0]["credentials"]["api_key"] == {
        "reference": "A_TEST_PROVIDER_KEY",
        "is_set": True,
    }


def test_a_pasted_secret_is_refused_by_the_field_built_to_prevent_it(db_session):
    tenant = make_tenant(db_session)

    with pytest.raises(IntegrationConfigurationError):
        configure_integration(
            tenant.id,
            capability=CAPABILITY_SMS,
            provider_key=FAKE,
            credential_references={"api_key": "sk-live-abc123-an-actual-key"},
        )


def test_a_reference_is_a_variable_name_not_a_value():
    assert is_valid_reference("SMS_PROVIDER_API_KEY") is True
    assert is_valid_reference("sk-live-abc") is False
    assert is_valid_reference("lowercase_name") is False
    assert is_valid_reference("") is False


def test_absence_of_a_credential_is_reportable_without_revealing_presence(monkeypatch):
    monkeypatch.setenv("PRESENT_CREDENTIAL", "value")
    monkeypatch.delenv("ABSENT_CREDENTIAL", raising=False)

    assert credentials_present({"a": "PRESENT_CREDENTIAL"}) is True
    assert credentials_present({"a": "ABSENT_CREDENTIAL"}) is False
    assert describe_references({"a": "PRESENT_CREDENTIAL"}) == {
        "a": {"reference": "PRESENT_CREDENTIAL", "is_set": True}
    }
    assert resolve_secret("ABSENT_CREDENTIAL") is None


def test_the_message_body_and_the_number_stay_out_of_the_log(db_session, caplog):
    """For OTP the message body *is* the secret, and a phone number is not a
    thing to leave in a log file."""
    tenant = make_tenant(db_session)
    _routed(db_session, tenant)
    _billable(db_session, tenant)

    with caplog.at_level("DEBUG"):
        send_sms(
            tenant_id=tenant.id,
            destination="+919876512345",
            message="Your NexSchool code is 483920",
            purpose="login_otp",
        )

    assert "483920" not in caplog.text
    assert "Your NexSchool code" not in caplog.text
    assert "+919876512345" not in caplog.text
    assert "9876512345" not in caplog.text
    # The last two digits survive, so a support engineer with the number in
    # front of them can confirm they are on the right line.
    assert "…45/" in caplog.text


# ---------------------------------------------------------------------------
# Usage, and the boundary with billing
# ---------------------------------------------------------------------------

def test_a_successful_send_reaches_the_usage_ledger(db_session):
    tenant = make_tenant(db_session)
    _routed(db_session, tenant)
    _billable(db_session, tenant)

    send_sms(
        tenant_id=tenant.id, destination="+919876500000", message="hi", purpose="login_otp"
    )
    db_session.flush()

    records = ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).all()
    assert len(records) == 1
    assert records[0].usage_type == "login_otp"
    assert records[0].unit == "sms"


def test_a_failed_send_is_not_billed(db_session):
    tenant = make_tenant(db_session)
    _routed(db_session, tenant, configuration={BEHAVIOUR_KEY: BEHAVIOUR_REJECTED})
    _billable(db_session, tenant)

    send_sms(
        tenant_id=tenant.id, destination="+919876500000", message="hi", purpose="login_otp"
    )
    db_session.flush()

    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 0


def test_the_provider_reference_is_what_makes_a_send_billed_once(db_session):
    """Idempotency is the provider's own identity, not a second deduplication
    scheme invented here."""
    tenant = make_tenant(db_session)
    _routed(db_session, tenant)
    _billable(db_session, tenant)

    for _ in range(2):
        send_sms(
            tenant_id=tenant.id,
            destination="+919876500000",
            message="hi",
            purpose="login_otp",
            idempotency_key="one-logical-send",
        )
    db_session.flush()

    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 1


def test_two_separate_sends_stay_two(db_session):
    """Collapsing lookalike sends would lose usage a provider will charge for."""
    tenant = make_tenant(db_session)
    _routed(db_session, tenant)
    _billable(db_session, tenant)

    for parent in ("+919876500001", "+919876500002"):
        send_sms(
            tenant_id=tenant.id, destination=parent, message="hi", purpose="login_otp"
        )
    db_session.flush()

    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 2


def test_a_send_a_school_has_no_terms_for_is_reported_not_lost(db_session, caplog):
    """The message is already gone. Raising would tell the caller it failed and
    invite a retry that sends a second one."""
    tenant = make_tenant(db_session)
    _routed(db_session, tenant)

    with caplog.at_level("ERROR"):
        result = send_sms(
            tenant_id=tenant.id, destination="+919876500000", message="hi", purpose="login_otp"
        )
    db_session.flush()

    assert result.success is True
    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 0
    assert "could not be recorded" in caplog.text


def test_usage_from_two_vendors_of_one_service_is_refused_rather_than_guessed(
    db_session,
):
    """The defect per-tenant provider selection made reachable.

    A service key is unique per provider, so two vendors can both sell `sms`.
    Recording usage by key alone had two answers and took whichever the
    database returned — billing the school at an arbitrary vendor's rates.
    """
    tenant = make_tenant(db_session)
    _billable(db_session, tenant, provider_key=_key("vendor-a"))
    _billable(db_session, tenant, provider_key=_key("vendor-b"))

    with pytest.raises(AmbiguousService):
        record_usage(
            tenant_id=tenant.id,
            service_key=CAPABILITY_SMS,
            quantity=1,
            usage_type="login_otp",
        )


def test_naming_the_vendor_resolves_the_ambiguity(db_session):
    tenant = make_tenant(db_session)
    first, _ = _billable(db_session, tenant, provider_key=_key("vendor-a"))
    _billable(db_session, tenant, provider_key=_key("vendor-b"))

    record = record_usage(
        tenant_id=tenant.id,
        service_key=CAPABILITY_SMS,
        provider_key=first.key,
        quantity=1,
        usage_type="login_otp",
    )
    db_session.flush()

    assert record is not None
    assert record.tenant_service.service.provider.key == first.key


def test_integration_never_calculates_what_anything_costs():
    """The billing boundary, asserted structurally rather than by discipline.

        integration → usage → billing

    never

        integration → billing calculation

    An integration module that imported a price would mean changing a price
    requires editing the send path.
    """
    import ast
    import pathlib

    root = pathlib.Path("modules/integrations")
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            if module and "billing.calculation" in module:
                raise AssertionError(f"{path} imports a billing calculation")
            if module and "billing.services" in module:
                raise AssertionError(f"{path} imports billing services")


def test_billing_never_calls_a_provider():
    """And the other direction. Billing must stay deterministic from stored
    configuration and usage — a total that depended on a vendor being up would
    not be a total."""
    import ast
    import pathlib

    banned = ("integrations", "urllib", "requests", "httpx", "boto3")
    for path in pathlib.Path("modules/billing").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                assert not any(word in name for word in banned), (
                    f"{path} imports {name}"
                )


def test_no_provider_client_can_forget_a_timeout():
    """The failure this module's HTTP helper exists to make impossible.

    The repository's existing outbound calls each set `timeout=30` as a
    copy-pasted literal and one sets nothing at all. Here there is no way to
    omit one — and nothing outside `http.py` may open a socket directly.
    """
    import ast
    import pathlib

    for path in pathlib.Path("modules/integrations").rglob("*.py"):
        if path.name == "http.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            for name in names:
                assert not any(
                    name.startswith(client)
                    for client in ("urllib", "requests", "httpx", "http.client", "socket")
                ), f"{path} opens its own connection instead of using http.py"


# ---------------------------------------------------------------------------
# Health, without spending anything
# ---------------------------------------------------------------------------

def test_a_health_check_sends_nothing(db_session, monkeypatch):
    """Finding out whether SMS works by sending an SMS charges the school and
    rings a real person's phone."""
    tenant = make_tenant(db_session)
    _routed(db_session, tenant)
    _billable(db_session, tenant)

    def must_not_be_called(**kwargs):
        raise AssertionError("a health check tried to send a message")

    monkeypatch.setattr(registry.get(FAKE), "send", must_not_be_called)

    report = sms_health(tenant.id)
    db_session.flush()

    assert report.ready is True
    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 0


def test_a_school_with_nothing_configured_reports_that_plainly(db_session):
    tenant = make_tenant(db_session)

    report = sms_health(tenant.id)

    assert report.ready is False
    assert report.checks == {"integration_row": False}


def test_health_does_not_claim_delivery_was_verified(db_session):
    tenant = make_tenant(db_session)
    configure_integration(tenant.id, capability=CAPABILITY_SMS, provider_key=FAKE)
    db_session.flush()

    # A provider with no free check to offer — which is most of them.
    def silent_health(configuration):
        report = FakeSmsProvider.health(registry.get(FAKE), configuration)
        report.provider_reachable = None
        report.detail = ""
        return report

    from modules.integrations import health as health_module

    original = registry.get(FAKE).health
    registry.get(FAKE).health = silent_health
    try:
        report = health_module.capability_health(
            tenant_id=tenant.id, capability=CAPABILITY_SMS
        )
    finally:
        registry.get(FAKE).health = original

    assert "not verified" in report.detail


# ---------------------------------------------------------------------------
# Configuring it
# ---------------------------------------------------------------------------

def test_configuring_an_integration_never_starts_it(db_session):
    """Adding a row must not start carrying traffic."""
    tenant = make_tenant(db_session)

    integration = configure_integration(
        tenant.id, capability=CAPABILITY_SMS, provider_key=FAKE
    )
    db_session.flush()

    assert integration.status == STATUS_DISABLED
    with pytest.raises(NoIntegrationConfigured):
        resolve_provider(tenant_id=tenant.id, capability=CAPABILITY_SMS)


def test_disabling_keeps_the_configuration_and_the_history(db_session):
    """A school that pauses SMS over the summer has not lost its settings, and
    last term's messages still have to be explicable."""
    tenant = make_tenant(db_session)
    _routed(db_session, tenant, configuration={"sender_id": "SCHOOL"})
    _billable(db_session, tenant)
    send_sms(
        tenant_id=tenant.id, destination="+919876500000", message="hi", purpose="login_otp"
    )
    db_session.flush()

    set_integration_status(
        tenant.id, capability=CAPABILITY_SMS, status=STATUS_DISABLED
    )
    db_session.flush()

    row = TenantIntegration.query.filter_by(tenant_id=tenant.id).first()
    assert row.configuration == {"sender_id": "SCHOOL"}
    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 1


def test_enabling_something_that_cannot_work_is_refused(db_session, monkeypatch):
    """An integration switched on without its credentials produces a school
    whose messages fail silently."""
    tenant = make_tenant(db_session)
    monkeypatch.delenv("A_MISSING_CREDENTIAL", raising=False)
    configure_integration(
        tenant.id,
        capability=CAPABILITY_SMS,
        provider_key=FAKE,
        credential_references={"api_key": "A_MISSING_CREDENTIAL"},
    )
    db_session.flush()

    with pytest.raises(IntegrationConfigurationError) as raised:
        set_integration_status(
            tenant.id, capability=CAPABILITY_SMS, status=STATUS_ENABLED
        )

    assert "credentials" in str(raised.value).lower()


def test_a_refused_configuration_stores_nothing(db_session):
    """A rejected provider must not leave a half-configured row behind."""
    tenant = make_tenant(db_session)

    with pytest.raises(IntegrationConfigurationError):
        configure_integration(
            tenant.id,
            capability=CAPABILITY_SMS,
            provider_key="a_vendor_we_do_not_have",
        )

    assert TenantIntegration.query.filter_by(tenant_id=tenant.id).count() == 0


def test_a_capability_the_build_lacks_cannot_be_configured(db_session):
    tenant = make_tenant(db_session)

    with pytest.raises(IntegrationConfigurationError):
        configure_integration(
            tenant.id, capability="telepathy", provider_key=FAKE
        )


def test_a_provider_cannot_be_pointed_at_the_wrong_capability(db_session):
    tenant = make_tenant(db_session)

    class Emailer(FakeSmsProvider):
        key = "an_emailer"
        capability = "email"

    from modules.integrations import services as services_module

    with pytest.raises(IntegrationConfigurationError):
        configure_integration(
            tenant.id, capability=CAPABILITY_SMS, provider_key="an_emailer"
        )


def test_one_school_s_integration_is_not_another_s(db_session):
    ours = make_tenant(db_session)
    theirs = make_tenant(db_session)
    _routed(db_session, theirs, configuration={"sender_id": "THEIRS"})

    assert describe_tenant_integrations(ours.id) == []
    assert len(describe_tenant_integrations(theirs.id)) == 1
