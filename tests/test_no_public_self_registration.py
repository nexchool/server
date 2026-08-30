"""Nobody signs themselves up to a school.

`POST /api/auth/register` was unauthenticated, unrated, and resolved its tenant
with `use_default=True` — so a request naming no school at all landed in
`DEFAULT_TENANT_SUBDOMAIN`, which production sets to `default`. It then created
a real account, granted it `DEFAULT_USER_ROLE` ("Student"), and emailed a
verification link to the address the registrant had just typed, so the attacker
verified themselves. The Student profile carries `student.read.self`,
`attendance.read.self`, `academics.read`, `timetable.read` and
`examination.read`.

It was reachable from a **Sign Up link in the shipped mobile app**, so this was
not dormant attack surface — it was an invitation.

Removed rather than rate-limited, because the product has no self-service
signup and never had one: a school issues credentials. Students arrive through
bulk import or admission, staff through the admin console, tenants through the
panel. Under ADR-011 a household shares the pupil's login, so there is not even
a parent to sign up.
"""

from __future__ import annotations

import uuid

import pytest


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def test_the_public_registration_endpoint_is_gone(client, tenant):
    email = f"stranger-{uuid.uuid4().hex[:8]}@example.test"

    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Str0ng!Passw0rd", "name": "A Stranger"},
        headers={"X-Tenant-Subdomain": tenant.subdomain},
    )

    assert response.status_code in (404, 405), (
        "public self-registration must not exist"
    )


def test_a_stranger_naming_no_school_creates_nothing(client, db_session):
    """The dangerous shape: no tenant named, so it used to fall back to `default`."""
    from modules.auth.models import User

    email = f"stranger-{uuid.uuid4().hex[:8]}@example.test"

    client.post(
        "/api/auth/register",
        json={"email": email, "password": "Str0ng!Passw0rd"},
    )

    assert User.query.filter_by(email=email).first() is None, (
        "an unauthenticated request must never create an account"
    )
