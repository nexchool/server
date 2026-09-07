"""Phase 2 — who may see and change third-party billing, over HTTP.

The model tests prove the arithmetic. These prove the boundary around it, and
there are only two rules to remember:

  * **What NexSchool pays its vendors is platform-admin only.** It is a
    supplier negotiation, and a school that could read it would know
    NexSchool's margin on every service.
  * **What a school is charged is the school's own business**, behind the
    permission that already guards the rest of its commercials.

There is deliberately no endpoint that writes usage. Usage is written by
NexSchool's own subsystems inside a request that is already authenticated and
already tenant-scoped; an HTTP surface would be a way to write billing data
from outside, and nothing needs one yet.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from core.database import db
from modules.auth.services import generate_access_token
from modules.billing.services import configure_tenant_service, upsert_provider, upsert_service
from modules.billing.constants import PRICING_METERED
from tests.auth._characterization import grant_permissions, make_tenant, make_user


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def sms(db_session):
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


def _platform_admin(db_session, tenant):
    operator = make_user(
        db_session,
        tenant,
        password="Platform12345",
        email=f"ops-{uuid.uuid4().hex[:8]}@nexchool.test",
        is_platform_admin=True,
    )
    return {"Authorization": f"Bearer {generate_access_token(operator)}"}


def _school_user(db_session, tenant, *, permissions):
    user = make_user(db_session, tenant, password="Member12345")
    grant_permissions(db_session, tenant, user, permissions)
    return {
        "Authorization": f"Bearer {generate_access_token(user)}",
        "X-Tenant-ID": tenant.id,
    }


# ---------------------------------------------------------------------------
# The catalog is NexSchool's, not a school's
# ---------------------------------------------------------------------------

def test_a_platform_operator_can_read_the_catalog_with_our_costs_in_it(
    client, db_session, sms
):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.get("/api/platform/service-catalog", headers=headers)

    assert response.status_code == 200
    providers = response.get_json()["data"]["providers"]
    ours = [p for p in providers if p["key"] == sms.provider.key][0]
    # Shown here on purpose: this is the screen where somebody decides what to
    # charge for it.
    assert ours["services"][0]["provider_unit_cost"] == 0.02


def test_a_school_administrator_cannot_reach_the_catalog_at_all(client, db_session, sms):
    tenant = make_tenant(db_session)
    headers = _school_user(db_session, tenant, permissions=("subscription.read",))

    catalog = client.get("/api/platform/service-catalog", headers=headers)
    add = client.post(
        "/api/platform/service-catalog/providers",
        headers=headers,
        json={"key": "sneaky", "name": "Sneaky"},
    )

    assert catalog.status_code == 403
    assert add.status_code == 403


def test_a_school_cannot_set_its_own_prices(client, db_session, sms):
    """Pricing is a commercial agreement, not a setting."""
    tenant = make_tenant(db_session)
    headers = _school_user(db_session, tenant, permissions=("subscription.read",))

    response = client.post(
        f"/api/platform/tenants/{tenant.id}/services",
        headers=headers,
        json={"service_key": sms.key, "customer_unit_price": 0},
    )

    assert response.status_code == 403


def test_a_nonsense_pricing_mode_is_refused_rather_than_stored(client, db_session, sms):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.post(
        f"/api/platform/tenants/{tenant.id}/services",
        headers=headers,
        json={"service_key": sms.key, "pricing_mode": "whatever_we_feel_like"},
    )

    assert response.status_code == 400


def test_configuring_a_service_for_a_school_that_does_not_exist_is_not_found(
    client, db_session, sms
):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.post(
        "/api/platform/tenants/t-nobody/services",
        headers=headers,
        json={"service_key": sms.key},
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# The annual statement
# ---------------------------------------------------------------------------

def test_the_statement_shows_an_operator_both_numbers(client, db_session, sms):
    tenant = make_tenant(db_session, price_per_student_per_year=Decimal("1000"))
    headers = _platform_admin(db_session, tenant)
    configure_tenant_service(
        tenant.id,
        service_key=sms.key,
        customer_unit_price=Decimal("0.05"),
        estimated_annual_quantity=Decimal("120000"),
    )
    db_session.flush()

    data = client.get(
        f"/api/platform/tenants/{tenant.id}/annual-statement", headers=headers
    ).get_json()["data"]

    assert data["is_estimate"] is True
    assert data["services"][0]["estimated_annual_provider_cost"] == 2400.0
    assert data["services"][0]["estimated_annual_customer_charge"] == 6000.0
    assert data["estimated_annual_total"] == data["subscription_total"] + 6000.0


def test_a_school_cannot_read_the_platform_statement(client, db_session):
    tenant = make_tenant(db_session)
    headers = _school_user(db_session, tenant, permissions=("subscription.read",))

    response = client.get(
        f"/api/platform/tenants/{tenant.id}/annual-statement", headers=headers
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# What a school sees on its own screen
# ---------------------------------------------------------------------------

def test_a_school_sees_its_charges_but_never_our_costs(client, db_session, sms):
    tenant = make_tenant(db_session, price_per_student_per_year=Decimal("1000"))
    headers = _school_user(db_session, tenant, permissions=("subscription.read",))
    configure_tenant_service(
        tenant.id,
        service_key=sms.key,
        customer_unit_price=Decimal("0.05"),
        estimated_annual_quantity=Decimal("120000"),
    )
    db_session.flush()

    body = client.get("/api/subscription/state", headers=headers).get_json()["data"]

    assert body["services"][0]["estimated_annual_customer_charge"] == 6000.0
    assert "estimated_annual_provider_cost" not in body["services"][0]
    # The cost is 2400; nowhere in the payload, under any key.
    assert "2400" not in repr(body)


def test_a_teacher_sees_neither_the_bill_nor_the_services(client, db_session, sms):
    """Standing is everybody's business; the contract is not."""
    tenant = make_tenant(db_session, price_per_student_per_year=Decimal("1000"))
    headers = _school_user(db_session, tenant, permissions=("student.read.all",))
    configure_tenant_service(
        tenant.id, service_key=sms.key, estimated_annual_quantity=Decimal("1000")
    )
    db_session.flush()

    body = client.get("/api/subscription/state", headers=headers).get_json()["data"]

    assert "subscription" in body
    assert "billing" not in body
    assert "services" not in body


def test_a_school_with_no_services_sees_the_payload_it_always_saw(client, db_session):
    """Backward compatibility at the surface a school actually reads."""
    tenant = make_tenant(db_session, price_per_student_per_year=Decimal("1000"))
    headers = _school_user(db_session, tenant, permissions=("subscription.read",))

    body = client.get("/api/subscription/state", headers=headers).get_json()["data"]

    assert body["services"] == []
    assert set(body["billing"]) == {
        "active_students",
        "price_per_student_per_year",
        "base_amount",
        "discount_percentage",
        "discount_active",
        "discount_amount",
        "total",
        "currency",
    }


def test_one_school_cannot_read_another_s_services(client, db_session, sms):
    ours = make_tenant(db_session)
    theirs = make_tenant(db_session)
    configure_tenant_service(
        theirs.id,
        service_key=sms.key,
        customer_unit_price=Decimal("0.99"),
        estimated_annual_quantity=Decimal("100000"),
    )
    db_session.flush()
    headers = _school_user(db_session, ours, permissions=("subscription.read",))

    body = client.get("/api/subscription/state", headers=headers).get_json()["data"]

    assert body["services"] == []
    assert "0.99" not in repr(body)


def test_the_platform_billing_payload_is_unchanged(client, db_session):
    """The consolidation must not have moved a key the panel reads."""
    tenant = make_tenant(db_session, price_per_student_per_year=Decimal("1000"))
    headers = _platform_admin(db_session, tenant)

    data = client.get(
        f"/api/platform/tenants/{tenant.id}/billing", headers=headers
    ).get_json()["data"]

    assert set(data) == {
        "success",
        "tenant_id",
        "on_date",
        "active_students",
        "price_per_student_per_year",
        "base_amount",
        "discount_percentage",
        "discount_active",
        "discount_window",
        "discount_amount",
        "total",
        "currency",
    }
