"""Phase 2 — billing for things NexSchool buys from somebody else.

NexSchool has always billed one thing: students, once a year, at one rate.
This is the foundation for the second kind of charge — a service bought by the
unit from a vendor, where what NexSchool pays and what the school pays are two
different numbers that move independently.

Nothing here authenticates anybody or sends anything. OTP is the use case that
motivated it and is deliberately not in this phase; what is tested is that the
billing machinery an OTP feature will one day call is correct, isolated and
safe to point at a provider's webhook.

The assertions worth reading first:

  * `test_what_we_pay_our_vendor_is_not_what_the_school_is_charged` — the
    distinction the whole model exists for.
  * `test_a_school_never_sees_what_nexschool_pays_its_provider` — and that it
    survives a component gaining new fields.
  * `test_the_same_provider_event_twice_is_one_usage_row` — a replayed webhook
    must not double a bill.
  * `test_a_school_with_no_services_bills_exactly_what_it_billed_before` — the
    backward-compatibility promise, asserted rather than assumed.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from core.database import db
from core.school_time import utc_now
from modules.billing.calculation import (
    annual_estimate,
    customer_facing,
    monthly_run_rate,
    subscription_component,
)
from modules.billing.constants import (
    ESTIMATE_BASIS_CONFIGURED,
    ESTIMATE_BASIS_NONE,
    ESTIMATE_BASIS_OBSERVED,
    PRICING_FIXED,
    PRICING_METERED,
    PRICING_PASS_THROUGH,
)
from modules.billing.models import (
    ProviderService,
    ServiceProvider,
    ServiceUsageRecord,
    TenantService,
)
from modules.billing.services import (
    BillingConfigurationError,
    configure_tenant_service,
    describe_tenant_services,
    tenant_annual_statement,
    upsert_provider,
    upsert_service,
)
from modules.billing.usage import (
    UnknownService,
    observed_usage,
    record_usage,
    usage_total,
)
from tests.auth._characterization import make_tenant


def _key(prefix: str) -> str:
    """Catalog keys are globally unique, and committed tenants accumulate in a
    developer's database run after run — so every key is its own."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def sms(db_session):
    """A vendor selling SMS at 2 paise a message, NexSchool's cost."""
    provider = upsert_provider(key=_key("smsco"), name="An SMS Company")
    service = upsert_service(
        provider_key=provider.key,
        key=_key("sms"),
        name="Transactional SMS",
        unit="sms",
        pricing_mode=PRICING_METERED,
        provider_unit_cost=Decimal("0.02"),
    )
    db_session.flush()
    return service


def _school(db_session, **pricing):
    tenant = make_tenant(db_session, **pricing)
    return tenant


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------

def test_a_vendor_and_what_it_sells_are_two_different_things(db_session, sms):
    """One provider may sell several services, each with its own unit."""
    email = upsert_service(
        provider_key=sms.provider.key,
        key=_key("email"),
        name="Transactional Email",
        unit="email",
        pricing_mode=PRICING_METERED,
        provider_unit_cost=Decimal("0.001"),
    )
    db_session.flush()

    assert email.provider_id == sms.provider_id
    assert {sms.unit, email.unit} == {"sms", "email"}


def test_the_catalog_is_keyed_so_correcting_it_does_not_duplicate_it(db_session, sms):
    """Re-running configuration is how an operator fixes a typo."""
    again = upsert_service(
        provider_key=sms.provider.key,
        key=sms.key,
        name="Transactional SMS (India)",
        unit="sms",
        pricing_mode=PRICING_METERED,
        provider_unit_cost=Decimal("0.025"),
    )
    db_session.flush()

    assert again.id == sms.id
    assert ProviderService.query.filter_by(key=sms.key).count() == 1
    assert again.provider_unit_cost == Decimal("0.0250")


def test_a_service_needs_a_unit_and_a_pricing_mode_that_exists(db_session, sms):
    with pytest.raises(BillingConfigurationError):
        upsert_service(
            provider_key=sms.provider.key,
            key=_key("bad"),
            name="No unit",
            unit="",
            pricing_mode=PRICING_METERED,
        )
    with pytest.raises(BillingConfigurationError):
        upsert_service(
            provider_key=sms.provider.key,
            key=_key("bad"),
            name="Nonsense mode",
            unit="sms",
            pricing_mode="whatever_we_feel_like",
        )


# ---------------------------------------------------------------------------
# Cost is not price
# ---------------------------------------------------------------------------

def test_what_we_pay_our_vendor_is_not_what_the_school_is_charged(db_session, sms):
    """The distinction the whole model exists for.

    NexSchool pays 2 paise and charges 5. Neither number is computed from the
    other, so NexSchool can change vendor without changing what a school pays,
    and can discount a school without renegotiating with a vendor.
    """
    tenant = _school(db_session)
    configuration = configure_tenant_service(
        tenant.id,
        service_key=sms.key,
        customer_unit_price=Decimal("0.05"),
        estimated_annual_quantity=Decimal("120000"),
    )
    db_session.flush()

    estimate = annual_estimate(configuration)

    assert estimate["estimated_annual_quantity"] == 120000.0
    assert estimate["estimated_annual_provider_cost"] == 2400.0
    assert estimate["estimated_annual_customer_charge"] == 6000.0


def test_changing_the_vendor_price_does_not_move_the_school_s_bill(db_session, sms):
    tenant = _school(db_session)
    configuration = configure_tenant_service(
        tenant.id,
        service_key=sms.key,
        customer_unit_price=Decimal("0.05"),
        estimated_annual_quantity=Decimal("1000"),
    )
    db_session.flush()
    before = annual_estimate(configuration)["estimated_annual_customer_charge"]

    sms.provider_unit_cost = Decimal("0.04")
    db_session.flush()
    after = annual_estimate(configuration)

    assert after["estimated_annual_customer_charge"] == before == 50.0
    assert after["estimated_annual_provider_cost"] == 40.0


def test_a_fixed_price_ignores_how_much_was_used(db_session, sms):
    tenant = _school(db_session)
    configuration = configure_tenant_service(
        tenant.id,
        service_key=sms.key,
        pricing_mode=PRICING_FIXED,
        customer_fixed_price=Decimal("9999.00"),
        estimated_annual_quantity=Decimal("500000"),
    )
    db_session.flush()

    estimate = annual_estimate(configuration)

    assert estimate["estimated_annual_customer_charge"] == 9999.0
    # The cost still tracks usage — that is what NexSchool actually spends.
    assert estimate["estimated_annual_provider_cost"] == 10000.0


def test_pass_through_is_the_one_mode_where_the_two_are_equal(db_session, sms):
    """And it is equal because the school was told it would be, not by accident."""
    tenant = _school(db_session)
    configuration = configure_tenant_service(
        tenant.id,
        service_key=sms.key,
        pricing_mode=PRICING_PASS_THROUGH,
        estimated_annual_quantity=Decimal("1000"),
    )
    db_session.flush()

    estimate = annual_estimate(configuration)

    assert estimate["estimated_annual_provider_cost"] == 20.0
    assert estimate["estimated_annual_customer_charge"] == 20.0


def test_a_school_on_its_own_terms_overrides_the_catalog(db_session, sms):
    tenant = _school(db_session)
    configuration = configure_tenant_service(
        tenant.id,
        service_key=sms.key,
        customer_unit_price=Decimal("0.03"),
        provider_unit_cost=Decimal("0.015"),
        estimated_annual_quantity=Decimal("10000"),
    )
    db_session.flush()

    estimate = annual_estimate(configuration)

    assert estimate["estimated_annual_provider_cost"] == 150.0
    assert estimate["estimated_annual_customer_charge"] == 300.0


# ---------------------------------------------------------------------------
# The estimate says it is an estimate
# ---------------------------------------------------------------------------

def test_an_estimate_says_what_it_is_standing_on(db_session, sms):
    tenant = _school(db_session)
    configuration = configure_tenant_service(tenant.id, service_key=sms.key)
    db_session.flush()

    # Nothing configured and nothing recorded: the honest answer is zero.
    assert annual_estimate(configuration)["estimate_basis"] == ESTIMATE_BASIS_NONE

    configuration.estimated_annual_quantity = Decimal("5000")
    db_session.flush()
    assert annual_estimate(configuration)["estimate_basis"] == ESTIMATE_BASIS_CONFIGURED


def test_with_nothing_configured_the_estimate_annualises_what_was_recorded(
    db_session, sms
):
    tenant = _school(db_session)
    configure_tenant_service(tenant.id, service_key=sms.key)
    db_session.flush()

    # 30 days of history at 100 a day.
    now = utc_now()
    for day in range(30):
        record_usage(
            tenant_id=tenant.id,
            service_key=sms.key,
            quantity=100,
            usage_type="sms_sent",
            occurred_at=now - timedelta(days=day),
            external_reference=f"evt-{day}",
        )
    db_session.flush()

    component = describe_tenant_services(tenant.id)[0]

    assert component["estimate_basis"] == ESTIMATE_BASIS_OBSERVED
    # ~3,000 over ~29 days annualises to roughly 37,000 — an estimate, and
    # asserted as a range because it is one.
    assert 30000 < component["estimated_annual_quantity"] < 45000


def test_a_configured_estimate_wins_over_observed_usage(db_session, sms):
    """An operator who has been told what a school plans to use outranks a guess."""
    tenant = _school(db_session)
    configure_tenant_service(
        tenant.id, service_key=sms.key, estimated_annual_quantity=Decimal("50000")
    )
    record_usage(
        tenant_id=tenant.id, service_key=sms.key, quantity=999, usage_type="sms_sent"
    )
    db_session.flush()

    component = describe_tenant_services(tenant.id)[0]

    assert component["estimate_basis"] == ESTIMATE_BASIS_CONFIGURED
    assert component["estimated_annual_quantity"] == 50000.0


def test_a_statement_never_calls_itself_an_invoice(db_session, sms):
    tenant = _school(db_session, price_per_student_per_year=Decimal("1000"))

    statement = tenant_annual_statement(tenant.id, active_students=10)

    assert statement["is_estimate"] is True
    assert "invoice" not in repr(statement).lower()


# ---------------------------------------------------------------------------
# Usage is a ledger, not a counter
# ---------------------------------------------------------------------------

def test_usage_is_recorded_with_the_unit_it_was_measured_in(db_session, sms):
    tenant = _school(db_session)
    configure_tenant_service(tenant.id, service_key=sms.key)
    db_session.flush()

    record = record_usage(
        tenant_id=tenant.id,
        service_key=sms.key,
        quantity=3,
        usage_type="sms_otp_sent",
        source="notifications",
    )
    db_session.flush()

    assert record.unit == "sms"
    assert record.quantity == Decimal("3.0000")
    assert record.usage_type == "sms_otp_sent"


def test_the_same_provider_event_twice_is_one_usage_row(db_session, sms):
    """A replayed webhook must not double a bill."""
    tenant = _school(db_session)
    configure_tenant_service(tenant.id, service_key=sms.key)
    db_session.flush()

    first = record_usage(
        tenant_id=tenant.id,
        service_key=sms.key,
        quantity=1,
        usage_type="sms_otp_sent",
        external_reference="provider-message-42",
    )
    second = record_usage(
        tenant_id=tenant.id,
        service_key=sms.key,
        quantity=1,
        usage_type="sms_otp_sent",
        external_reference="provider-message-42",
    )
    db_session.flush()

    assert first is not None
    # Reported by returning None, not by raising: a provider retry is an
    # ordinary event, not an error.
    assert second is None
    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 1


def test_two_real_events_that_look_alike_stay_two_events(db_session, sms):
    """Deduplicating by shape would lose usage a provider will charge for.

    Two OTPs to two parents in the same second are two messages. Only a named
    event is deduplicable; an unnamed one is recorded.
    """
    tenant = _school(db_session)
    configure_tenant_service(tenant.id, service_key=sms.key)
    db_session.flush()
    moment = utc_now()

    for _ in range(2):
        record_usage(
            tenant_id=tenant.id,
            service_key=sms.key,
            quantity=1,
            usage_type="sms_otp_sent",
            occurred_at=moment,
        )
    db_session.flush()

    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 2


def test_the_same_reference_from_two_schools_is_two_events(db_session, sms):
    """Provider ids are only unique within a provider's account, and two
    schools are two customers. Scoping the key by tenant is what stops one
    school's replay from suppressing another's real usage."""
    ours = _school(db_session)
    theirs = _school(db_session)
    for tenant in (ours, theirs):
        configure_tenant_service(tenant.id, service_key=sms.key)
    db_session.flush()

    for tenant in (ours, theirs):
        record_usage(
            tenant_id=tenant.id,
            service_key=sms.key,
            quantity=1,
            usage_type="sms_otp_sent",
            external_reference="shared-id",
        )
    db_session.flush()

    assert ServiceUsageRecord.query.filter_by(tenant_id=ours.id).count() == 1
    assert ServiceUsageRecord.query.filter_by(tenant_id=theirs.id).count() == 1


def test_usage_for_a_service_a_school_does_not_have_is_refused(db_session, sms):
    """Not silently created. A charge nobody signed up for is a bug."""
    tenant = _school(db_session)

    with pytest.raises(UnknownService):
        record_usage(
            tenant_id=tenant.id,
            service_key=sms.key,
            quantity=1,
            usage_type="sms_otp_sent",
        )


def test_usage_is_answerable_between_two_dates(db_session, sms):
    """The thing a counter cannot do, and the reason this is a ledger."""
    tenant = _school(db_session)
    configuration = configure_tenant_service(tenant.id, service_key=sms.key)
    db_session.flush()
    now = utc_now()

    for days_ago, quantity in ((200, 500), (10, 30), (1, 7)):
        record_usage(
            tenant_id=tenant.id,
            service_key=sms.key,
            quantity=quantity,
            usage_type="sms_sent",
            occurred_at=now - timedelta(days=days_ago),
            external_reference=f"evt-{days_ago}",
        )
    db_session.flush()

    everything = usage_total(configuration.id, tenant_id=tenant.id)
    recent = usage_total(
        configuration.id, tenant_id=tenant.id, since=now - timedelta(days=30)
    )

    assert everything == Decimal("537")
    assert recent == Decimal("37")


# ---------------------------------------------------------------------------
# One school cannot see another's
# ---------------------------------------------------------------------------

def test_one_school_s_usage_is_not_another_s(db_session, sms):
    ours = _school(db_session)
    theirs = _school(db_session)
    our_configuration = configure_tenant_service(ours.id, service_key=sms.key)
    configure_tenant_service(theirs.id, service_key=sms.key)
    db_session.flush()

    record_usage(
        tenant_id=theirs.id, service_key=sms.key, quantity=1000, usage_type="sms_sent"
    )
    db_session.flush()

    assert usage_total(our_configuration.id, tenant_id=ours.id) == Decimal("0")
    assert observed_usage(our_configuration.id, tenant_id=ours.id) == (Decimal("0"), 0)


def test_one_school_s_prices_are_not_another_s(db_session, sms):
    ours = _school(db_session)
    theirs = _school(db_session)
    configure_tenant_service(
        ours.id, service_key=sms.key, customer_unit_price=Decimal("0.05")
    )
    configure_tenant_service(
        theirs.id, service_key=sms.key, customer_unit_price=Decimal("0.99")
    )
    db_session.flush()

    ours_described = describe_tenant_services(ours.id)

    assert len(ours_described) == 1
    assert ours_described[0]["customer_unit_price"] == 0.05


def test_a_statement_only_contains_this_school_s_services(db_session, sms):
    ours = _school(db_session, price_per_student_per_year=Decimal("500"))
    theirs = _school(db_session)
    configure_tenant_service(
        theirs.id,
        service_key=sms.key,
        customer_unit_price=Decimal("0.05"),
        estimated_annual_quantity=Decimal("100000"),
    )
    db_session.flush()

    statement = tenant_annual_statement(ours.id, active_students=4)

    assert statement["services"] == []
    assert statement["estimated_annual_total"] == 2000.0


def test_the_usage_ledger_is_tenant_scoped_by_the_orm_not_only_by_hand(
    db_session, sms, flask_app
):
    """A bare query, of the kind an unwary future caller would write.

    `ServiceUsageRecord` inherits `TenantBaseModel`, which is what applies the
    scope — a model holding tenant data that does not inherit it is simply
    unscoped however it is annotated. This asserts the inheritance is real.

    Inside a **request** context specifically: the scope is deliberately inert
    without one, so that Celery jobs and scripts can read across schools. A
    test that set `g.tenant_id` in a bare app context would pass or fail for
    reasons that have nothing to do with the model.
    """
    ours = _school(db_session)
    theirs = _school(db_session)
    for tenant in (ours, theirs):
        configure_tenant_service(tenant.id, service_key=sms.key)
    db_session.flush()
    record_usage(
        tenant_id=theirs.id, service_key=sms.key, quantity=5, usage_type="sms_sent"
    )
    db_session.flush()

    with flask_app.test_request_context():
        from flask import g

        g.tenant_id = ours.id
        visible = ServiceUsageRecord.query.all()

    assert visible == []


# ---------------------------------------------------------------------------
# What a school is allowed to see
# ---------------------------------------------------------------------------

def test_a_school_never_sees_what_nexschool_pays_its_provider(db_session, sms):
    tenant = _school(db_session, price_per_student_per_year=Decimal("1000"))
    configure_tenant_service(
        tenant.id,
        service_key=sms.key,
        customer_unit_price=Decimal("0.05"),
        estimated_annual_quantity=Decimal("120000"),
    )
    db_session.flush()

    statement = tenant_annual_statement(tenant.id, active_students=10)
    for_the_school = customer_facing(statement)

    assert statement["provider_cost_total"] == 2400.0
    assert "provider_cost_total" not in for_the_school
    assert "2400" not in repr(for_the_school)
    for component in for_the_school["services"]:
        assert "estimated_annual_provider_cost" not in component
    # What they are charged is still there — this strips cost, not the bill.
    assert for_the_school["services"][0]["estimated_annual_customer_charge"] == 6000.0


def test_stripping_cost_reaches_wherever_it_is_nested(db_session):
    """By field name, recursively — so a component that later gains a cost
    field is safe without anybody remembering to update this."""
    payload = {
        "services": [
            {"provider_unit_cost": 9, "deeper": {"estimated_annual_provider_cost": 9}}
        ],
        "provider_cost_total": 9,
        "estimated_annual_total": 100,
    }

    assert customer_facing(payload) == {
        "services": [{"deeper": {}}],
        "estimated_annual_total": 100,
    }


def test_the_catalog_hides_our_cost_unless_asked(db_session, sms):
    """The default is the safety property: a serializer that leaked it by
    accident would leak it everywhere at once."""
    assert "provider_unit_cost" not in sms.to_dict()
    assert sms.to_dict(include_provider_cost=True)["provider_unit_cost"] == 0.02


# ---------------------------------------------------------------------------
# The bill a school already had
# ---------------------------------------------------------------------------

def test_a_school_with_no_services_bills_exactly_what_it_billed_before(db_session):
    """The backward-compatibility promise, asserted rather than assumed."""
    tenant = _school(db_session, price_per_student_per_year=Decimal("1200"))

    statement = tenant_annual_statement(tenant.id, active_students=250)

    assert statement["services"] == []
    assert statement["services_total"] == 0.0
    assert statement["subscription_total"] == 300000.0
    assert statement["estimated_annual_total"] == statement["subscription_total"]


def test_a_third_party_charge_is_added_never_folded_in(db_session, sms):
    """A school reading its bill can see which part is which."""
    tenant = _school(db_session, price_per_student_per_year=Decimal("1000"))
    configure_tenant_service(
        tenant.id,
        service_key=sms.key,
        customer_unit_price=Decimal("0.05"),
        estimated_annual_quantity=Decimal("20000"),
    )
    db_session.flush()

    statement = tenant_annual_statement(tenant.id, active_students=100)

    assert statement["subscription_total"] == 100000.0
    assert statement["services_total"] == 1000.0
    assert statement["estimated_annual_total"] == 101000.0
    assert statement["services"][0]["component_key"] == f"service:{sms.key}"


def test_a_paused_service_stops_costing_without_losing_its_terms(db_session, sms):
    tenant = _school(db_session, price_per_student_per_year=Decimal("1000"))
    configure_tenant_service(
        tenant.id,
        service_key=sms.key,
        customer_unit_price=Decimal("0.05"),
        estimated_annual_quantity=Decimal("20000"),
    )
    db_session.flush()

    configure_tenant_service(
        tenant.id,
        service_key=sms.key,
        is_enabled=False,
        customer_unit_price=Decimal("0.05"),
        estimated_annual_quantity=Decimal("20000"),
    )
    db_session.flush()

    statement = tenant_annual_statement(tenant.id, active_students=10)

    assert statement["services"] == []
    assert statement["estimated_annual_total"] == 10000.0
    # The rates survive, so resuming is not a renegotiation.
    assert TenantService.query.filter_by(tenant_id=tenant.id).count() == 1
    assert describe_tenant_services(tenant.id)[0]["is_enabled"] is False


def test_the_subscription_sum_is_the_one_the_platform_already_used(db_session):
    """The consolidation, checked against the behaviour it replaced.

    `calculate_tenant_billing` and the school's own dashboard now share this
    function. Its output for the same inputs must be what the old arithmetic
    produced, or the consolidation moved somebody's bill.
    """
    from datetime import date

    tenant = _school(
        db_session,
        price_per_student_per_year=Decimal("1500"),
        discount_percentage=Decimal("10"),
        discount_start_date=date(2026, 1, 1),
        discount_end_date=date(2026, 12, 31),
    )

    inside = subscription_component(tenant, 200, on_date=date(2026, 6, 1))
    outside = subscription_component(tenant, 200, on_date=date(2027, 6, 1))

    assert inside["base_amount"] == 300000.0
    assert inside["discount_active"] is True
    assert inside["discount_amount"] == 30000.0
    assert inside["total"] == 270000.0
    assert outside["discount_active"] is False
    assert outside["total"] == 300000.0


def test_an_unpriced_school_bills_nothing_rather_than_failing(db_session):
    """`price_per_student_per_year` is nullable and has no default. That is
    existing behaviour and this phase does not change it — it pins it."""
    tenant = _school(db_session)

    statement = tenant_annual_statement(tenant.id, active_students=500)

    assert statement["estimated_annual_total"] == 0.0


def test_the_monthly_figure_is_a_twelfth_as_it_always_was(db_session):
    assert monthly_run_rate(Decimal("120000")) == 10000.0
    assert monthly_run_rate(Decimal("0")) == 0.0


def test_a_statement_for_a_school_that_does_not_exist_is_none(db_session):
    assert tenant_annual_statement("t-nobody", active_students=1) is None


# ---------------------------------------------------------------------------
# Authentication does not do arithmetic
# ---------------------------------------------------------------------------

def test_the_authentication_code_knows_nothing_about_money():
    """A structural assertion, and the one most worth keeping.

    When OTP is built it will record that a message was sent and stop. It must
    never multiply a rate by a quantity — the moment a strategy knows a price,
    changing a price means editing the login path, and a bug in billing
    becomes a bug in signing in.

    Checked structurally — by what these modules import and what names they
    bind — rather than by grepping their prose. The pipeline's docstring does
    say the word "cost", in a sentence about not spending money on a login
    attempt, and a test that failed on that would be measuring the comments.
    """
    import ast
    import inspect

    from modules.auth import pipeline, policy
    from modules.auth.strategies import email_password, identifier_password

    money = ("price", "cost", "charge", "tariff", "billing")

    for module in (pipeline, policy, email_password, identifier_password):
        tree = ast.parse(inspect.getsource(module))

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "billing" not in node.module, (
                    f"{module.__name__} imports from {node.module}"
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "billing" not in alias.name, (
                        f"{module.__name__} imports {alias.name}"
                    )
            # A name that reads like money means arithmetic crept in.
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                assert not any(word in node.id.lower() for word in money), (
                    f"{module.__name__} binds {node.id!r}"
                )
