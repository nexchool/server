"""The structure a school is arranged into, over GraphQL.

Campuses and academic years are what almost every other read hangs off, and
they are the first Academics reads to move. What is pinned here is mostly the
decision *not* to bundle them: they answer to different permissions, and a
person holding one but not the other still gets what they may see.

A client that wants both still asks once and pays for one round-trip. The
saving is in the transport; the authorities stay separate because they are
separate.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from graphql_api import GRAPHQL_PATH

BOTH = """
query {
  campuses { id name code status }
  academicYears { id name startDate endDate isActive }
}
"""

CAMPUSES = "query { campuses { id name code status } }"
YEARS = """
query Y($activeOnly: Boolean) {
  academicYears(activeOnly: $activeOnly) { name isActive }
}
"""


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def structure(db_session, tenant):
    """Two campuses and three years, one of them the one in progress."""
    from modules.academics.academic_year.models import AcademicYear
    from modules.school_units.models import SchoolUnit

    campuses = [
        SchoolUnit(
            id=_new_id("su-"), tenant_id=tenant.id, name=name,
            code=f"{code}-{uuid.uuid4().hex[:6]}",
        )
        for name, code in (("Naranpura Campus", "NRP"), ("Maninagar Campus", "MNG"))
    ]
    db_session.add_all(campuses)

    years = []
    for name, start, active in (
        ("2024-2025", date(2024, 6, 1), False),
        ("2025-2026", date(2025, 6, 1), False),
        ("2026-2027", date(2026, 6, 1), True),
    ):
        years.append(
            AcademicYear(
                id=_new_id("ay-"), tenant_id=tenant.id, name=name,
                start_date=start, end_date=date(start.year + 1, 3, 31),
                is_active=active,
            )
        )
    db_session.add_all(years)
    db_session.flush()
    return campuses, years


def _staff_with(db_session, tenant, *permission_keys):
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Staff",
    )
    db_session.add(user)
    db_session.flush()

    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Role-{suffix}")
    db_session.add(role)
    db_session.flush()
    for key in permission_keys:
        permission = Permission.query.filter_by(name=key).first()
        if permission is None:
            permission = Permission(id=_new_id("perm-"), name=key)
            db_session.add(permission)
            db_session.flush()
        db_session.add(
            RolePermission(
                tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
            )
        )
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")
    return user, generate_access_token(user)


def _ask(client, tenant, token, query, **variables):
    return client.post(
        GRAPHQL_PATH,
        json={"query": query, "variables": variables},
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {token}",
        },
    ).get_json()


def _codes(body):
    return [error["extensions"].get("code") for error in body.get("errors", [])]


# ---------------------------------------------------------------------------
# What a school is arranged into
# ---------------------------------------------------------------------------

def test_the_campuses_a_school_teaches_at(client, db_session, tenant, structure):
    _user, token = _staff_with(db_session, tenant, "school_unit.read")

    body = _ask(client, tenant, token, CAMPUSES)

    assert "errors" not in body, body
    names = {campus["name"] for campus in body["data"]["campuses"]}
    assert names == {"Naranpura Campus", "Maninagar Campus"}


def test_the_years_a_school_teaches_through(client, db_session, tenant, structure):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(client, tenant, token, YEARS)

    names = [year["name"] for year in body["data"]["academicYears"]]
    assert set(names) == {"2024-2025", "2025-2026", "2026-2027"}


def test_asking_for_only_the_year_in_progress(client, db_session, tenant, structure):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(client, tenant, token, YEARS, activeOnly=True)

    years = body["data"]["academicYears"]
    assert [year["name"] for year in years] == ["2026-2027"]
    assert years[0]["isActive"] is True


def test_both_are_answered_in_one_request(client, db_session, tenant, structure):
    """The round-trip saving, which is the part GraphQL is actually for."""
    _user, token = _staff_with(db_session, tenant, "school_unit.read", "class.read")

    body = _ask(client, tenant, token, BOTH)

    assert "errors" not in body, body
    assert len(body["data"]["campuses"]) == 2
    assert len(body["data"]["academicYears"]) == 3


# ---------------------------------------------------------------------------
# Two reads, two authorities — deliberately not merged
# ---------------------------------------------------------------------------

def test_reading_campuses_needs_the_campus_authority(
    client, db_session, tenant, structure
):
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(client, tenant, token, CAMPUSES)

    assert "FORBIDDEN" in _codes(body)


def test_reading_years_needs_the_class_authority(
    client, db_session, tenant, structure
):
    _user, token = _staff_with(db_session, tenant, "school_unit.read")

    body = _ask(client, tenant, token, YEARS)

    assert "FORBIDDEN" in _codes(body)


def test_holding_one_authority_still_answers_that_half(
    client, db_session, tenant, structure
):
    """Why these are two fields rather than one `academicScope`.

    Five structure reads answer to five different permissions. Bundled behind
    one guard, a person holding four of them would get a blank screen instead
    of the four they may see; bundled behind one field, one refusal would fail
    the whole response. Kept apart, a client asks for what it is allowed to
    and still pays for one round-trip.
    """
    _user, token = _staff_with(db_session, tenant, "class.read")

    body = _ask(client, tenant, token, YEARS)

    assert "errors" not in body, body
    assert len(body["data"]["academicYears"]) == 3


def test_another_schools_structure_is_not_visible(
    client, db_session, tenant, structure
):
    from core.models import Tenant
    from modules.school_units.models import SchoolUnit

    other = Tenant(
        id=_new_id("t-"), name="Other School",
        subdomain=f"other-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(other)
    db_session.flush()
    db_session.add(
        SchoolUnit(
            id=_new_id("su-"), tenant_id=other.id, name="Their Campus",
            code=f"THR-{uuid.uuid4().hex[:6]}",
        )
    )
    db_session.flush()

    _user, token = _staff_with(db_session, tenant, "school_unit.read")
    body = _ask(client, tenant, token, CAMPUSES)

    names = {campus["name"] for campus in body["data"]["campuses"]}
    assert "Their Campus" not in names
