"""A super-admin switching a module off must reach a signed-in admin at once.

Before this, it did not. `enabled_features` was handed out at login and never
questioned again, so a school kept a Transport link it was no longer entitled
to until somebody logged out and back in — and found out by clicking it and
landing on a 403.

Every `/api/*` response now carries `X-Feature-Stamp`: a short value derived
from the enabled set. The client keeps the last one it saw and re-reads its
profile when a response disagrees. No polling; the signal rides along with
work the app was doing anyway.

The three things that have to hold, and each has been a bug in something:
the stamp is on the response, it changes when and only when the modules
change, and a browser on another origin is allowed to read it.
"""

from __future__ import annotations

import uuid

import pytest

from core.feature_flags import OPTIONAL_FEATURES, feature_stamp


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def admin_headers(db_session, tenant):
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Role
    from modules.rbac.role_seeder import seed_roles_for_tenant
    from tests.conftest import grant_profile_to

    seed_roles_for_tenant(tenant.id)
    admin_role = Role.query.filter_by(name="Admin", tenant_id=tenant.id).first()

    user = User(
        id=f"u-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant.id,
        email=f"stamp-admin-{uuid.uuid4().hex[:8]}@test.school",
        name="Stamp Admin",
        email_verified=True,
    )
    user.set_password("Password123")
    db_session.add(user)
    db_session.flush()
    grant_profile_to(user, admin_role.id)

    return {
        "Authorization": f"Bearer {generate_access_token(user)}",
        "X-Tenant-ID": tenant.id,
    }


def _stamp_of(client, headers) -> str | None:
    """The stamp on a response that actually answered.

    Read from a live endpoint, and the status asserted, because every `/api/*`
    response carries the header — including a 404. Pointed at a route that has
    since moved to GraphQL, these tests would go on passing while proving
    nothing.
    """
    response = client.get("/api/teachers/", headers=headers)
    assert response.status_code == 200, response.status_code
    return response.headers.get("X-Feature-Stamp")


# ---------------------------------------------------------------------------
# What is on offer
# ---------------------------------------------------------------------------

def test_only_things_a_school_can_be_without_are_switchable():
    """Pins the list, because two other places have to agree with it.

    admin-web mirrors it in `src/lib/optionalModules.ts`, which its own test
    uses to prove each one has a page that refuses. And a super-admin sees
    these as checkboxes — a key here that the product cannot survive without
    is a switch that decapitates a live school.

    Changing this list is a business decision, so it should be a deliberate
    edit here rather than a side effect of adding a module. If you do change
    it, update admin-web's copy in the same breath.
    """
    assert set(OPTIONAL_FEATURES) == {
        "attendance",
        "fees_management",
        "timetable",
        "transport",
        "hostel",
        "notifications",
        "academic_calendar",
    }


def test_the_product_itself_cannot_be_switched_off():
    """Students, teachers, classes and the structure they hang off.

    These were switchable. Nobody ever switched them off, which is the point:
    they are not options, and offering them as options only ever risked
    somebody finding out the hard way.
    """
    from core.feature_flags import is_feature_enabled

    for key in ("students", "teachers", "classes", "academics_advanced", "search",
                "student_management", "teacher_management", "class_management"):
        assert key not in OPTIONAL_FEATURES, f"{key} must not be switchable"
        assert is_feature_enabled("any-tenant", key) is True


# ---------------------------------------------------------------------------
# The stamp itself
# ---------------------------------------------------------------------------

def test_the_same_modules_produce_the_same_stamp():
    """Saving settings without changing them must not look like a change.

    Otherwise every visit to the super-admin's tenant form would push a
    pointless profile refresh onto every signed-in user of that school.
    """
    flags = {key: True for key in OPTIONAL_FEATURES}
    assert feature_stamp(flags) == feature_stamp(dict(flags))


def test_turning_a_module_off_changes_the_stamp():
    flags = {key: True for key in OPTIONAL_FEATURES}
    assert feature_stamp(flags) != feature_stamp(flags | {"transport": False})


def test_an_absent_key_reads_as_enabled():
    """A tenant created before a module existed has it, rather than losing it.

    The stamp has to agree with that rule, or those tenants would refresh
    their profile on every response forever.
    """
    complete = {key: True for key in OPTIONAL_FEATURES}
    partial = {key: True for key in OPTIONAL_FEATURES if key != "hostel"}
    assert feature_stamp(partial) == feature_stamp(complete)


# ---------------------------------------------------------------------------
# Reaching the client
# ---------------------------------------------------------------------------

def test_api_responses_carry_the_stamp(client, admin_headers):
    assert _stamp_of(client, admin_headers) is not None


def test_switching_a_module_off_changes_what_the_client_sees(
    client, admin_headers, db_session, tenant
):
    """The whole point: the next request tells the client, without a re-login."""
    tenant.feature_flags = {key: True for key in OPTIONAL_FEATURES}
    db_session.flush()
    before = _stamp_of(client, admin_headers)

    tenant.feature_flags = {key: True for key in OPTIONAL_FEATURES} | {"transport": False}
    db_session.flush()
    after = _stamp_of(client, admin_headers)

    assert before is not None and after is not None
    assert before != after


def test_a_repeated_request_does_not_look_like_a_change(
    client, admin_headers, db_session, tenant
):
    """A stable stamp is what keeps this from refreshing on every response."""
    tenant.feature_flags = {key: True for key in OPTIONAL_FEATURES}
    db_session.flush()
    assert _stamp_of(client, admin_headers) == _stamp_of(client, admin_headers)


def test_the_browser_is_allowed_to_read_the_stamp(flask_app):
    """A response header a cross-origin browser cannot read is not a signal.

    admin-web is served from a different origin than the API in production. A
    missing entry here fails nowhere, silently, and only there — locally
    everything goes through one nginx and works.
    """
    exposed = flask_app.config.get("CORS_EXPOSE_HEADERS") or []
    assert "X-Feature-Stamp" in exposed


def test_the_profile_reports_the_current_modules(
    client, admin_headers, db_session, tenant
):
    """What the client re-reads once the stamp tells it to.

    The stamp only says "something changed"; this is the answer to "what".
    """
    tenant.feature_flags = {key: True for key in OPTIONAL_FEATURES} | {"hostel": False}
    db_session.flush()

    body = client.get("/api/auth/profile", headers=admin_headers).get_json()
    features = body["data"]["enabled_features"]

    assert "hostel" not in features
    assert "transport" in features
