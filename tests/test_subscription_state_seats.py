"""The school can see its own seats on the subscription page.

The panel sets seat limits per school; the school's own screen must show
where it stands against them, or the first it hears of a limit is a refused
admission. `seats` rides on the same `subscription.read` gate as the bill,
because a ceiling on headcount is part of the contract, not everybody's
business.
"""

from __future__ import annotations

import uuid

import pytest

from modules.auth.services import generate_access_token
from tests.auth._characterization import grant_permissions, make_tenant, make_user
from tests.conftest import _make_student


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _school_user(db_session, tenant, *, permissions):
    user = make_user(db_session, tenant, password="Member12345")
    grant_permissions(db_session, tenant, user, permissions)
    return {
        "Authorization": f"Bearer {generate_access_token(user)}",
        "X-Tenant-ID": tenant.id,
    }


def test_the_bill_reader_sees_seats_used_against_each_limit(client, db_session):
    tenant = make_tenant(db_session)
    tenant.max_active_students = 150
    tenant.max_employed_teachers = 20
    _make_student(db_session, tenant, name="Here", admission_suffix=f"s-{uuid.uuid4().hex[:6]}")
    gone = _make_student(db_session, tenant, name="Gone", admission_suffix=f"g-{uuid.uuid4().hex[:6]}")
    gone.student_status = "graduated"
    db_session.flush()
    headers = _school_user(db_session, tenant, permissions=("subscription.read",))

    body = client.get("/api/subscription/state", headers=headers).get_json()["data"]

    assert body["seats"] == {
        "students": {"used": 1, "limit": 150},
        "teachers": {"used": 0, "limit": 20},
    }


def test_a_school_with_no_ceiling_sees_null_limits(client, db_session):
    tenant = make_tenant(db_session)
    headers = _school_user(db_session, tenant, permissions=("subscription.read",))

    body = client.get("/api/subscription/state", headers=headers).get_json()["data"]

    assert body["seats"]["students"]["limit"] is None
    assert body["seats"]["teachers"]["limit"] is None


def test_a_teacher_does_not_see_the_seats(client, db_session):
    tenant = make_tenant(db_session)
    headers = _school_user(db_session, tenant, permissions=("student.read.all",))

    body = client.get("/api/subscription/state", headers=headers).get_json()["data"]

    assert "seats" not in body
