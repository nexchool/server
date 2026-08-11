"""The GraphQL identity surface: who am I, and which experiences may I use."""

from __future__ import annotations

import uuid

import pytest

from graphql_api import GRAPHQL_PATH
from modules.people.backfill import backfill_tenant

ME_QUERY = "{ me { id fullName email availableContexts } }"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _signed_in_user(db_session, tenant, *, name="Meera Shah"):
    """A user with a valid access token, as the clients would present it."""
    from modules.auth.models import User
    from modules.auth.services import generate_access_token

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}",
        tenant_id=tenant.id,
        email=f"{suffix}@test.school",
        password_hash="x" * 60,
        name=name,
    )
    db_session.add(user)
    db_session.flush()
    return user, generate_access_token(user)


def _headers(tenant, token):
    return {
        "X-Tenant-Subdomain": tenant.subdomain,
        "Authorization": f"Bearer {token}",
    }


def _errors(response):
    return [error["extensions"].get("code") for error in response.get_json()["errors"]]


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------

def test_asking_who_i_am_without_signing_in_is_refused(client, tenant):
    response = client.post(
        GRAPHQL_PATH,
        json={"query": ME_QUERY},
        headers={"X-Tenant-Subdomain": tenant.subdomain},
    )

    assert response.status_code == 200
    assert _errors(response) == ["UNAUTHENTICATED"]


def test_a_token_from_another_tenant_is_refused(client, db_session, tenant):
    """Tenant isolation holds on GraphQL exactly as it does on REST.

    The unknown subdomain falls back to the default tenant, so the request
    resolves a tenant this user does not belong to — and identity is rejected
    rather than serving one organization's data to another.
    """
    user, token = _signed_in_user(db_session, tenant)
    backfill_tenant(tenant.id)

    response = client.post(
        GRAPHQL_PATH,
        json={"query": ME_QUERY},
        headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-Subdomain": "no-such-tenant",
        },
    )

    assert _errors(response) == ["UNAUTHENTICATED"]


def test_a_request_that_resolves_no_tenant_is_refused(client, db_session, tenant):
    user, token = _signed_in_user(db_session, tenant)
    backfill_tenant(tenant.id)

    # A host with an unknown subdomain resolves nothing: the default-tenant
    # fallback applies only to single-part hosts such as localhost.
    response = client.post(
        GRAPHQL_PATH,
        json={"query": ME_QUERY},
        headers={
            "Authorization": f"Bearer {token}",
            "Host": "nosuchschool.nexchool.in",
        },
    )

    assert _errors(response) == ["TENANT_REQUIRED"]


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def test_a_signed_in_person_sees_their_own_identity(client, db_session, tenant):
    user, token = _signed_in_user(db_session, tenant, name="Meera Shah")
    backfill_tenant(tenant.id)

    response = client.post(
        GRAPHQL_PATH, json={"query": ME_QUERY}, headers=_headers(tenant, token)
    )

    me = response.get_json()["data"]["me"]
    assert me["fullName"] == "Meera Shah"
    assert me["email"] == user.email
    assert me["id"] == user.person_id


def test_a_new_account_knows_its_person_without_any_backfill(client, db_session, tenant):
    """An account cannot exist without the human it belongs to.

    Nothing here runs the backfill: the person is created with the account.
    """
    user, token = _signed_in_user(db_session, tenant, name="Newly Created")

    response = client.post(
        GRAPHQL_PATH, json={"query": ME_QUERY}, headers=_headers(tenant, token)
    )

    me = response.get_json()["data"]["me"]
    assert me["fullName"] == "Newly Created"
    assert me["id"] == user.person_id


# ---------------------------------------------------------------------------
# Available contexts
# ---------------------------------------------------------------------------

def test_an_administrator_holds_the_staff_context(client, db_session, tenant):
    _, token = _signed_in_user(db_session, tenant)
    backfill_tenant(tenant.id)

    response = client.post(
        GRAPHQL_PATH, json={"query": ME_QUERY}, headers=_headers(tenant, token)
    )

    assert response.get_json()["data"]["me"]["availableContexts"] == ["STAFF"]


def test_a_student_holds_the_student_context(client, db_session, tenant):
    from modules.auth.services import generate_access_token
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:8]
    from modules.auth.models import User

    user = User(
        id=f"u-{suffix}",
        tenant_id=tenant.id,
        email=f"{suffix}@test.school",
        password_hash="x" * 60,
        name="Aarav Patel",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        Student(
            id=f"s-{suffix}",
            tenant_id=tenant.id,
            user_id=user.id,
            admission_number=f"ADM-{suffix}",
        )
    )
    db_session.flush()
    backfill_tenant(tenant.id)

    response = client.post(
        GRAPHQL_PATH,
        json={"query": ME_QUERY},
        headers=_headers(tenant, generate_access_token(user)),
    )

    assert response.get_json()["data"]["me"]["availableContexts"] == ["STUDENT"]


def test_no_parent_context_exists_while_households_share_a_login(
    client, db_session, tenant
):
    """ADR-011: a parent uses the student's credentials, so there is nothing to
    switch to. The context appears only when parent logins are issued."""
    from modules.auth.services import generate_access_token
    from modules.auth.models import User
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}",
        tenant_id=tenant.id,
        email=f"{suffix}@test.school",
        password_hash="x" * 60,
        name="Aarav Patel",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        Student(
            id=f"s-{suffix}",
            tenant_id=tenant.id,
            user_id=user.id,
            admission_number=f"ADM-{suffix}",
            father_name="Rajesh Patel",
            father_phone="9811111111",
        )
    )
    db_session.flush()
    backfill_tenant(tenant.id)

    response = client.post(
        GRAPHQL_PATH,
        json={"query": ME_QUERY},
        headers=_headers(tenant, generate_access_token(user)),
    )

    assert "PARENT" not in response.get_json()["data"]["me"]["availableContexts"]


# ---------------------------------------------------------------------------
# The boundary itself
# ---------------------------------------------------------------------------

def test_identity_does_not_know_academic():
    """Identity presents relationships; it must not go looking for them.

    Contexts are derived from what a person is to the organization, and People
    owns that question. When Identity reads Student or Teacher directly it has
    reached across a boundary the architecture forbids, and the reach is easy
    to reintroduce by accident — one convenient import in a resolver.
    """
    import ast
    import pathlib

    source = pathlib.Path("modules/auth/identity_service.py").read_text()

    reached_for = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
        if node.module.startswith(("modules.students", "modules.teachers",
                                   "modules.classes", "modules.academics"))
    }

    assert not reached_for, (
        f"Identity is reading Academic directly: {sorted(reached_for)}. "
        "Ask modules.people.relationships instead."
    )
