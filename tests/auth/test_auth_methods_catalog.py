"""What the panel is missing: a catalog of methods, not just configured rules.

`ensure_default_policy` seeds one rule per subject kind, all `email_password`
(see `modules/auth/policy.py`) — and "absence means denied" is that module's
deliberate semantic. So a school has no row at all for
`admission_id_password`, `mobile_otp` or `mobile_pin` until an operator turns
one on, and the panel's Login & access card renders one switch per *existing*
rule. It can never offer a method nobody has a rule for yet, which is exactly
backwards for the task that exists to unblock testing them.

The fix mirrors `GET /platform/integration-capabilities`: a build/config
split. `modules/integrations/services.py::describe_capabilities` reads the
provider registry, not the database, because which providers exist is a
property of the deployed code. `AuthenticationStrategyRegistry.describe_methods`
does the same for sign-in methods — and it reads each strategy's own declared
attributes rather than a hand-maintained list, so a fifth strategy shows up
here by being registered, not by somebody remembering to edit this file too.
"""

from __future__ import annotations

import uuid

import pytest

from modules.auth.services import generate_access_token
from modules.auth.strategies import registry
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


# ---------------------------------------------------------------------------
# The registry helper itself
# ---------------------------------------------------------------------------


def test_describe_methods_lists_every_registered_strategy():
    """A method with no school policy row must still appear — this reads the
    registry, never a tenant's `TenantAuthPolicyRule` table."""
    described = registry.describe_methods()

    assert {m["key"] for m in described} == set(registry.keys())


def test_describe_methods_reports_is_paid_truthfully():
    """`mobile_otp` sends an SMS and costs money; nothing else does today.
    The panel needs this to know which methods require a working messaging
    channel — see `_method_needs_messaging` in `modules/platform/routes.py`,
    which already reads the same attribute for the same reason."""
    described = {m["key"]: m for m in registry.describe_methods()}

    assert described["mobile_otp"]["is_paid"] is True
    assert described["email_password"]["is_paid"] is False
    assert described["admission_id_password"]["is_paid"] is False
    assert described["mobile_pin"]["is_paid"] is False


def test_describe_methods_reads_the_strategy_s_own_declared_attributes():
    """Not a parallel list: the values must trace back to the class."""
    described = {m["key"]: m for m in registry.describe_methods()}

    admission = described["admission_id_password"]
    assert admission["identifier_type"] == "admission_id"
    assert admission["credential_type"] == "password"
    assert admission["requires_tenant"] is True

    otp = described["mobile_otp"]
    assert otp["credential_type"] is None
    assert otp["counts_toward_account_lockout"] is False


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------


def test_the_route_lists_a_method_no_school_has_a_rule_for(client, db_session):
    """No `ensure_default_policy` call happens anywhere in this test — this
    tenant has no `TenantAuthPolicy` row at all, and the three non-default
    methods must still be listed."""
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.get("/api/platform/auth-methods", headers=headers)

    assert response.status_code == 200
    methods = response.get_json()["data"]["methods"]
    keys = {m["key"] for m in methods}
    assert {
        "email_password",
        "admission_id_password",
        "mobile_otp",
        "mobile_pin",
    } <= keys


def test_the_route_reports_is_paid_truthfully(client, db_session):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.get("/api/platform/auth-methods", headers=headers)

    by_key = {m["key"]: m for m in response.get_json()["data"]["methods"]}
    assert by_key["mobile_otp"]["is_paid"] is True
    assert by_key["email_password"]["is_paid"] is False


def test_a_school_cannot_see_the_catalog(client, db_session):
    """The same boundary Phase 2 drew around pricing and Phase 3 drew around
    integrations: which methods exist is NexSchool's to know, not a school's
    setting to read."""
    tenant = make_tenant(db_session)
    headers = _school_user(db_session, tenant)

    response = client.get("/api/platform/auth-methods", headers=headers)

    assert response.status_code == 403


def test_an_unauthenticated_caller_cannot_see_the_catalog(client):
    response = client.get("/api/platform/auth-methods")

    assert response.status_code == 401
