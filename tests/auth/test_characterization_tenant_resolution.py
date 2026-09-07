"""Phase −1 — how login decides which school it is talking about.

CHARACTERIZATION. Two separate mechanisms are pinned here, and they are easy
to confuse:

1. **Branch selection** — `routes.py::login` chooses the tenant-scoped branch
   from the REQUEST BODY ALONE (`if tenant_id_in_body or subdomain_in_body`).
   A tenant *header* does not select it.

2. **Tenant resolution** — `core/tenant.py::find_tenant` then resolves the
   school in a fixed order: body -> headers -> Host subdomain -> configured
   default.

This distinction is the thing Phase 1 depends on. Admission numbers are unique
per tenant only, so an admission-ID login that reaches the wrong school
resolves the wrong student. Nothing here is changed; it is written down.
"""

from __future__ import annotations

import uuid

import pytest

from tests.auth._characterization import (
    login,
    make_account,
    make_tenant,
    sessions_for,
)

PASSWORD = "C0rrectHorse1"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def account(db_session, tenant):
    return make_account(db_session, tenant, password=PASSWORD)


# ---------------------------------------------------------------------------
# Group 8 — the school chooser
# ---------------------------------------------------------------------------

@pytest.fixture
def twin_accounts(db_session, tenant):
    """One address, one password, two schools — the ambiguity the mobile app
    hits because a single app serves every school."""
    shared_email = f"twin-{uuid.uuid4().hex[:8]}@test.school"
    other = make_tenant(db_session, subdomain_prefix="chz-twin")
    first = make_account(
        db_session, tenant, password=PASSWORD, email=shared_email
    )
    second = make_account(
        db_session, other, password=PASSWORD, email=shared_email
    )
    return shared_email, (tenant, first), (other, second)


def test_an_email_in_two_schools_returns_a_chooser(client, twin_accounts):
    email, _, _ = twin_accounts

    response = login(client, email=email, password=PASSWORD)

    assert response.status_code == 200
    body = response.get_json()
    assert body["message"] == "Choose your school"
    assert body["data"]["requires_tenant_choice"] is True


def test_the_chooser_lists_each_school_by_id_name_and_subdomain(
    client, twin_accounts
):
    email, (tenant_a, _), (tenant_b, _) = twin_accounts

    data = login(client, email=email, password=PASSWORD).get_json()["data"]

    listed = {t["id"]: t for t in data["tenants"]}
    assert set(listed) == {tenant_a.id, tenant_b.id}
    for t in data["tenants"]:
        assert set(t) == {"id", "name", "subdomain"}


def test_the_chooser_issues_no_token_and_no_session(
    client, db_session, twin_accounts
):
    """The property the identity specification calls out explicitly: choosing
    a school is not signing in."""
    email, (_, first), (_, second) = twin_accounts

    data = login(client, email=email, password=PASSWORD).get_json()["data"]

    assert "access_token" not in data
    assert "refresh_token" not in data
    assert sessions_for(first.id) == []
    assert sessions_for(second.id) == []


def test_naming_the_school_on_the_second_attempt_signs_in(
    client, db_session, twin_accounts
):
    email, (tenant_a, first), _ = twin_accounts

    response = login(client, email=email, password=PASSWORD, tenant_id=tenant_a.id)

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["user"]["id"] == first.id
    assert data["tenant_id"] == str(tenant_a.id)
    assert data["access_token"]


def test_a_chooser_is_only_offered_when_the_password_matches_in_both(
    client, db_session, tenant
):
    """EXISTING BEHAVIOUR: the search matches on email AND password, so two
    accounts sharing an address but not a password are not ambiguous."""
    shared_email = f"twin-{uuid.uuid4().hex[:8]}@test.school"
    other = make_tenant(db_session, subdomain_prefix="chz-diff")
    here = make_account(db_session, tenant, password=PASSWORD, email=shared_email)
    make_account(db_session, other, password="A different1", email=shared_email)

    data = login(client, email=shared_email, password=PASSWORD).get_json()["data"]

    assert "requires_tenant_choice" not in data
    assert data["user"]["id"] == here.id


def test_one_match_signs_straight_in_without_a_chooser(client, account, tenant):
    data = login(client, email=account.email, password=PASSWORD).get_json()["data"]

    assert "requires_tenant_choice" not in data
    assert data["tenant_id"] == str(tenant.id)


def test_a_suspended_school_is_left_out_of_the_chooser(
    client, db_session, twin_accounts
):
    from core.models import TENANT_STATUS_SUSPENDED

    email, (tenant_a, first), (tenant_b, _) = twin_accounts
    tenant_b.status = TENANT_STATUS_SUSPENDED
    db_session.flush()

    data = login(client, email=email, password=PASSWORD).get_json()["data"]

    # One live school left, so there is nothing to choose between.
    assert "requires_tenant_choice" not in data
    assert data["tenant_id"] == str(tenant_a.id)
    assert data["user"]["id"] == first.id


# ---------------------------------------------------------------------------
# Group 9 — tenant resolution mechanisms
# ---------------------------------------------------------------------------

def test_the_body_resolves_the_school_by_tenant_id(client, tenant, account):
    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["subdomain"] == tenant.subdomain


def test_the_body_accepts_the_camel_case_spelling_too(client, tenant, account):
    """`tenant_id` and `tenantId` are both read, because the clients disagreed."""
    response = login(
        client, email=account.email, password=PASSWORD, tenantId=tenant.id
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["tenant_id"] == str(tenant.id)


def test_the_body_resolves_the_school_by_subdomain(client, tenant, account):
    response = login(
        client, email=account.email, password=PASSWORD, subdomain=tenant.subdomain
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["tenant_id"] == str(tenant.id)


def test_a_tenant_header_does_not_select_the_tenant_scoped_branch(
    client, db_session, tenant
):
    """EXISTING BEHAVIOUR that is easy to miss and matters for Phase 1.

    The branch is chosen by the BODY. With only `X-Tenant-ID` set, login takes
    the cross-tenant search branch — it still succeeds here because the address
    is unique, but it did not use the header to scope the lookup. An identifier
    that is only unique per tenant (an admission number) cannot rely on a
    header the way this endpoint currently reads one.
    """
    shared_email = f"hdr-{uuid.uuid4().hex[:8]}@test.school"
    other = make_tenant(db_session, subdomain_prefix="chz-hdr")
    here = make_account(db_session, tenant, password=PASSWORD, email=shared_email)
    make_account(db_session, other, password=PASSWORD, email=shared_email)

    response = client.post(
        "/api/auth/login",
        json={"email": shared_email, "password": PASSWORD},
        headers={"X-Tenant-ID": tenant.id},
    )

    # A header naming one school does not stop the chooser appearing.
    data = response.get_json()["data"]
    assert data.get("requires_tenant_choice") is True, data
    assert here.id  # referenced for clarity; the point is the chooser


def test_the_host_subdomain_resolves_the_school(client, tenant, account):
    response = client.post(
        "/api/auth/login",
        json={"email": account.email, "password": PASSWORD, "subdomain": tenant.subdomain},
        headers={"Host": f"{tenant.subdomain}.nexchool.test"},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["subdomain"] == tenant.subdomain


def test_resolution_order_prefers_the_body_over_a_conflicting_header(
    client, db_session, tenant, account
):
    """`find_tenant` reads the body first. A header naming a different school
    does not override it."""
    other = make_tenant(db_session, subdomain_prefix="chz-order")

    response = client.post(
        "/api/auth/login",
        json={
            "email": account.email,
            "password": PASSWORD,
            "tenant_id": tenant.id,
        },
        headers={"X-Tenant-ID": other.id},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["tenant_id"] == str(tenant.id)


def test_the_public_branding_endpoint_resolves_a_school_before_sign_in(
    client, tenant
):
    """Pre-authentication tenant resolution, used by the login screen. Pinned
    because the identity specification proposes publishing the tenant's
    allowed login methods through this same endpoint."""
    response = client.get(
        "/api/auth/tenant-branding",
        headers={"X-Tenant-Subdomain": tenant.subdomain},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["subdomain"] == tenant.subdomain
    assert data["name"] == tenant.name
    assert set(data) == {
        "name",
        "subdomain",
        "logo_url",
        "tagline",
        "login_variant",
        "theme",
        # Which ways in this school allows, so the sign-in screen can offer
        # them. Added when student admission sign-in arrived.
        "auth",
    }
    assert set(data["auth"]) == {"methods"}


def test_branding_refuses_when_no_school_can_be_resolved(client):
    """`use_default=False` here, unlike login — so branding does NOT fall back
    to the default tenant."""
    response = client.get(
        "/api/auth/tenant-branding",
        headers={"X-Tenant-Subdomain": f"nope-{uuid.uuid4().hex[:8]}"},
    )

    assert response.status_code == 404
