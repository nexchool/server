"""Phase 3 — who may configure a school's providers, over HTTP.

One rule: **which vendor NexSchool buys from is not a school's setting.** It
is the same boundary Phase 2 drew around pricing, for the same reason — the
commercial relationship is NexSchool's, and a school that could point its own
SMS at a vendor could point it anywhere.

And one property: **no endpoint here returns a credential.** Not because every
handler remembers to redact one, but because the value is not in the database
to return — only the name of the environment variable it lives in.
"""

from __future__ import annotations

import uuid

import pytest

from modules.auth.services import generate_access_token
from modules.integrations.capabilities import (
    CAPABILITY_SMS,
    CAPABILITY_WHATSAPP,
    STATUS_DISABLED,
    STATUS_ENABLED,
)
from modules.integrations.providers.fake import FakeSmsProvider, FakeWhatsAppProvider
from modules.integrations.providers.meta_whatsapp import MetaWhatsAppProvider
from modules.integrations.providers.msg91 import Msg91Provider
from modules.integrations.services import configure_integration, set_integration_status
from tests.auth._characterization import grant_permissions, make_tenant, make_user

FAKE = FakeSmsProvider.key


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


# ---------------------------------------------------------------------------
# What this build can do
# ---------------------------------------------------------------------------

def test_an_operator_can_see_what_capabilities_exist(client, db_session):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.get("/api/platform/integration-capabilities", headers=headers)

    assert response.status_code == 200
    capabilities = response.get_json()["data"]["capabilities"]
    sms = [c for c in capabilities if c["capability"] == CAPABILITY_SMS][0]
    # `FAKE` (a test double) and `msg91` (a real vendor, registered but
    # unusable until MSG91_AUTH_KEY is set — see test_integrations_foundation.py).
    assert [p["key"] for p in sms["providers"]] == sorted([FAKE, Msg91Provider.key])
    by_key = {p["key"]: p for p in sms["providers"]}
    assert by_key[FAKE]["is_test_double"] is True
    assert by_key[Msg91Provider.key]["is_test_double"] is False
    assert by_key[Msg91Provider.key]["required_credentials"] == ["MSG91_AUTH_KEY"]


def test_an_operator_can_see_whatsapp_s_capabilities_too(client, db_session):
    """SMS's twin. Meta's Cloud API client (Task 8) is registered but shows up
    nowhere in a listing test until this asserts it."""
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.get("/api/platform/integration-capabilities", headers=headers)

    assert response.status_code == 200
    capabilities = response.get_json()["data"]["capabilities"]
    whatsapp = [c for c in capabilities if c["capability"] == CAPABILITY_WHATSAPP][0]
    assert [p["key"] for p in whatsapp["providers"]] == sorted(
        [FakeWhatsAppProvider.key, MetaWhatsAppProvider.key]
    )
    by_key = {p["key"]: p for p in whatsapp["providers"]}
    assert by_key[FakeWhatsAppProvider.key]["is_test_double"] is True
    assert by_key[MetaWhatsAppProvider.key]["is_test_double"] is False
    assert by_key[MetaWhatsAppProvider.key]["required_credentials"] == [
        "META_WHATSAPP_ACCESS_TOKEN"
    ]


def test_a_school_cannot_see_or_choose_its_own_provider(client, db_session):
    """The same boundary Phase 2 drew around pricing."""
    tenant = make_tenant(db_session)
    headers = _school_user(db_session, tenant)

    listing = client.get("/api/platform/integration-capabilities", headers=headers)
    reading = client.get(
        f"/api/platform/tenants/{tenant.id}/integrations", headers=headers
    )
    choosing = client.post(
        f"/api/platform/tenants/{tenant.id}/integrations",
        headers=headers,
        json={"capability": CAPABILITY_SMS, "provider_key": FAKE},
    )

    assert listing.status_code == 403
    assert reading.status_code == 403
    assert choosing.status_code == 403


def test_an_unauthenticated_caller_gets_nowhere(client, db_session):
    tenant = make_tenant(db_session)

    response = client.get(f"/api/platform/tenants/{tenant.id}/integrations")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Configuring
# ---------------------------------------------------------------------------

def test_configuring_leaves_the_integration_switched_off(client, db_session):
    """Adding a row must not start carrying traffic."""
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.post(
        f"/api/platform/tenants/{tenant.id}/integrations",
        headers=headers,
        json={
            "capability": CAPABILITY_SMS,
            "provider_key": FAKE,
            "configuration": {"sender_id": "SCHOOL"},
        },
    )

    assert response.status_code == 200
    integration = response.get_json()["data"]["integrations"][0]
    assert integration["status"] == STATUS_DISABLED
    assert integration["configuration"] == {"sender_id": "SCHOOL"}


def test_an_operator_can_switch_it_on_and_off(client, db_session):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)
    client.post(
        f"/api/platform/tenants/{tenant.id}/integrations",
        headers=headers,
        json={"capability": CAPABILITY_SMS, "provider_key": FAKE},
    )

    on = client.patch(
        f"/api/platform/tenants/{tenant.id}/integrations/{CAPABILITY_SMS}/status",
        headers=headers,
        json={"status": STATUS_ENABLED},
    )
    off = client.patch(
        f"/api/platform/tenants/{tenant.id}/integrations/{CAPABILITY_SMS}/status",
        headers=headers,
        json={"status": STATUS_DISABLED},
    )

    assert on.get_json()["data"]["integrations"][0]["status"] == STATUS_ENABLED
    assert off.get_json()["data"]["integrations"][0]["status"] == STATUS_DISABLED
    # Disabling is not deleting.
    assert len(off.get_json()["data"]["integrations"]) == 1


def test_an_unknown_provider_is_refused(client, db_session):
    """That nothing is stored is asserted at the service, in
    `test_a_refused_configuration_stores_nothing` — the route rolls back on
    error, which in a savepoint-based test also unwinds the fixtures, so a
    follow-up request here would be measuring the harness."""
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.post(
        f"/api/platform/tenants/{tenant.id}/integrations",
        headers=headers,
        json={"capability": CAPABILITY_SMS, "provider_key": "a_vendor_we_do_not_have"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "ValidationError"


def test_a_capability_this_build_lacks_is_refused(client, db_session):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.post(
        f"/api/platform/tenants/{tenant.id}/integrations",
        headers=headers,
        json={"capability": "telepathy", "provider_key": FAKE},
    )

    assert response.status_code == 400


def test_configuring_for_a_school_that_does_not_exist_is_not_found(client, db_session):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.post(
        "/api/platform/tenants/t-nobody/integrations",
        headers=headers,
        json={"capability": CAPABILITY_SMS, "provider_key": FAKE},
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Secrets, and health
# ---------------------------------------------------------------------------

def test_no_endpoint_returns_a_credential(client, db_session, monkeypatch):
    """Not because the handler redacts it — because the value is not stored."""
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)
    monkeypatch.setenv("A_ROUTE_TEST_KEY", "sk-the-actual-secret")

    created = client.post(
        f"/api/platform/tenants/{tenant.id}/integrations",
        headers=headers,
        json={
            "capability": CAPABILITY_SMS,
            "provider_key": FAKE,
            "credential_references": {"api_key": "A_ROUTE_TEST_KEY"},
        },
    )
    listed = client.get(
        f"/api/platform/tenants/{tenant.id}/integrations", headers=headers
    )

    for response in (created, listed):
        assert "sk-the-actual-secret" not in response.get_data(as_text=True)
    integration = listed.get_json()["data"]["integrations"][0]
    assert integration["credentials"]["api_key"] == {
        "reference": "A_ROUTE_TEST_KEY",
        "is_set": True,
    }


def test_a_pasted_secret_is_refused_over_http_too(client, db_session):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.post(
        f"/api/platform/tenants/{tenant.id}/integrations",
        headers=headers,
        json={
            "capability": CAPABILITY_SMS,
            "provider_key": FAKE,
            "credential_references": {"api_key": "sk-live-an-actual-key"},
        },
    )

    assert response.status_code == 400


def test_the_listing_reports_health_without_sending_anything(
    client, db_session, monkeypatch
):
    from modules.integrations.registry import registry

    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)
    configure_integration(tenant.id, capability=CAPABILITY_SMS, provider_key=FAKE)
    set_integration_status(tenant.id, capability=CAPABILITY_SMS, status=STATUS_ENABLED)
    db_session.flush()

    def must_not_be_called(**kwargs):
        raise AssertionError("listing integrations tried to send a message")

    monkeypatch.setattr(registry.get(FAKE), "send", must_not_be_called)

    integration = client.get(
        f"/api/platform/tenants/{tenant.id}/integrations", headers=headers
    ).get_json()["data"]["integrations"][0]

    assert integration["health"]["ready"] is True
    assert integration["health"]["provider_supported"] is True


def test_one_school_s_integrations_are_not_another_s(client, db_session):
    ours = make_tenant(db_session)
    theirs = make_tenant(db_session)
    headers = _platform_admin(db_session, ours)
    configure_integration(theirs.id, capability=CAPABILITY_SMS, provider_key=FAKE)
    db_session.flush()

    ours_listed = client.get(
        f"/api/platform/tenants/{ours.id}/integrations", headers=headers
    ).get_json()["data"]["integrations"]

    assert ours_listed == []
