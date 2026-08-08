"""Reconciling records over GraphQL — the first write the platform accepts.

The schema had no Mutation root before this, so these tests pin what a
mutation must carry as much as what merging does: signed in, a school
resolved, and the authority for the action. A write that reaches every
school because no tenant resolved is the failure this transport makes easy,
so it is tested rather than trusted.
"""

from __future__ import annotations

import uuid

import pytest

from graphql_api import GRAPHQL_PATH

SUGGESTIONS = "{ duplicateSuggestions(limit: 10) { personId otherPersonId reason } }"

MERGE = """
mutation Merge($keep: ID!, $absorb: ID!) {
  mergePeople(keep: $keep, absorb: $absorb, reason: "same human") {
    personId
    fullName
    merge { keptPersonId absorbedPersonId reason }
  }
}
"""


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _headers(tenant, token):
    return {
        "X-Tenant-Subdomain": tenant.subdomain,
        "Authorization": f"Bearer {token}",
    }


def _errors(response):
    return [error["extensions"].get("code") for error in response.get_json()["errors"]]


def _person(db_session, tenant, name="Rajesh Patel", phone=None):
    from modules.people.models import Person

    person = Person(
        id=f"p-{uuid.uuid4().hex[:10]}",
        tenant_id=tenant.id,
        full_name=name,
        phone_number=phone,
    )
    db_session.add(person)
    db_session.flush()
    return person


def _signed_in(db_session, tenant, *, permissions=()):
    """An account whose employment holds the given Business Actions."""
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import employ_for, grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}",
        tenant_id=tenant.id,
        email=f"{suffix}@test.school",
        password_hash="x" * 60,
        name="Records Officer",
    )
    db_session.add(user)
    db_session.flush()
    employ_for(user, employee_number=f"EMP-{suffix}")

    if permissions:
        role = Role(
            id=f"r-{uuid.uuid4().hex[:8]}",
            tenant_id=tenant.id,
            name=f"Records-{suffix}",
        )
        db_session.add(role)
        db_session.flush()
        for key in permissions:
            permission = Permission.query.filter_by(name=key).first()
            if permission is None:
                permission = Permission(id=f"perm-{uuid.uuid4().hex[:8]}", name=key)
                db_session.add(permission)
                db_session.flush()
            db_session.add(
                RolePermission(
                    tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
                )
            )
        db_session.flush()
        grant_profile_to(user, role.id)

    return user, generate_access_token(user)


# ---------------------------------------------------------------------------
# What a mutation must carry
# ---------------------------------------------------------------------------

def test_the_schema_accepts_writes(flask_app):
    """There is a Mutation root at all — the thing Phase 3 builds on."""
    from graphql_api.schema import build_schema

    schema = build_schema(flask_app.config)
    assert schema.mutation is not None


def test_merging_without_signing_in_is_refused(client, tenant, db_session):
    keep = _person(db_session, tenant)
    absorb = _person(db_session, tenant)

    response = client.post(
        GRAPHQL_PATH,
        json={"query": MERGE, "variables": {"keep": keep.id, "absorb": absorb.id}},
        headers={"X-Tenant-Subdomain": tenant.subdomain},
    )

    assert response.status_code == 200
    assert "UNAUTHENTICATED" in _errors(response)


def test_merging_without_the_authority_is_refused(client, tenant, db_session):
    """Signed in is not enough — merging carries its own Business Action."""
    keep = _person(db_session, tenant)
    absorb = _person(db_session, tenant)
    _user, token = _signed_in(db_session, tenant)  # no permissions

    response = client.post(
        GRAPHQL_PATH,
        json={"query": MERGE, "variables": {"keep": keep.id, "absorb": absorb.id}},
        headers=_headers(tenant, token),
    )

    assert response.status_code == 200
    assert "FORBIDDEN" in _errors(response)


def test_suggestions_require_the_same_authority(client, tenant, db_session):
    _user, token = _signed_in(db_session, tenant)

    response = client.post(
        GRAPHQL_PATH, json={"query": SUGGESTIONS}, headers=_headers(tenant, token)
    )

    assert "FORBIDDEN" in _errors(response)


# ---------------------------------------------------------------------------
# What it does
# ---------------------------------------------------------------------------

def test_two_records_of_one_human_become_one(client, tenant, db_session):
    from modules.people.models import Person

    keep = _person(db_session, tenant, name="Rajesh Patel")
    absorb = _person(db_session, tenant, name="Rajesh Patel")
    _user, token = _signed_in(db_session, tenant, permissions=["person.merge"])

    response = client.post(
        GRAPHQL_PATH,
        json={"query": MERGE, "variables": {"keep": keep.id, "absorb": absorb.id}},
        headers=_headers(tenant, token),
    )

    body = response.get_json()
    assert "errors" not in body, body
    result = body["data"]["mergePeople"]
    assert result["personId"] == keep.id
    assert result["merge"]["absorbedPersonId"] == absorb.id
    assert result["merge"]["reason"] == "same human"

    # Retired, not erased: ADR-010 promises a merge is recoverable, so the
    # absorbed record is soft-deleted and what it held is kept in the merge.
    retired = Person.query.filter_by(id=absorb.id).first()
    assert retired.deleted_at is not None


def test_a_person_from_another_school_is_simply_not_found(
    client, tenant, db_session
):
    """The ORM scope restricts the read, so this is a 'no such person'."""
    from core.models import Tenant

    other = Tenant(
        id=f"t-{uuid.uuid4().hex[:8]}",
        name="Other School",
        subdomain=f"other-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(other)
    db_session.flush()

    keep = _person(db_session, tenant)
    theirs = _person(db_session, other, name="Someone Else")
    _user, token = _signed_in(db_session, tenant, permissions=["person.merge"])

    response = client.post(
        GRAPHQL_PATH,
        json={"query": MERGE, "variables": {"keep": keep.id, "absorb": theirs.id}},
        headers=_headers(tenant, token),
    )

    assert "NOT_FOUND" in _errors(response)


def test_suggestions_are_offered_to_someone_who_may_merge(
    client, tenant, db_session
):
    _person(db_session, tenant, name="Sunita Vyas", phone="9800022222")
    _person(db_session, tenant, name="Sunita Vyas", phone="9800022222")
    _user, token = _signed_in(db_session, tenant, permissions=["person.merge"])

    response = client.post(
        GRAPHQL_PATH, json={"query": SUGGESTIONS}, headers=_headers(tenant, token)
    )

    body = response.get_json()
    assert "errors" not in body, body
    found = body["data"]["duplicateSuggestions"]
    assert found and found[0]["reason"] == "same phone and name"
