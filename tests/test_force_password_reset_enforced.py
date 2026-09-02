"""A mandatory password change has to be mandatory on the server too.

Seven paths set `force_password_reset=True` — teacher creation and bulk import,
student creation, sub-admin creation, and three platform-admin resets. It was
read in exactly two places: the login response and the profile payload. So it
was a **suggestion to the client**. A provisioned account received a fully
privileged access token and could use every endpoint in the product by simply
not following the redirect, keeping the temporary password its administrator
had chosen — and for bulk-imported accounts that password is derived from the
person's own name.

Enforced now at the two places every caller passes through: `@auth_required`
for REST, `IsAuthenticated` for GraphQL.

**403, not 401.** The caller is authenticated; they are restricted. A 401 would
be a lie, and the Expo client now treats one as an expired session and signs
the user out — which would make the reset screen unreachable.

A short allowlist keeps the way out open: set the new password, read your own
profile and the feature list the client boots with, or log out.
"""

from __future__ import annotations

import uuid

import pytest

from graphql_api import GRAPHQL_PATH

PASSWORD = "Provision3d!"
NEW_PASSWORD = "Ch0senByMe!"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _account(db_session, tenant, *, must_reset: bool):
    """Somebody who may read students, flagged or not."""
    from modules.auth.models import User
    from modules.auth.services import generate_access_token
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        name="Newly Provisioned", force_password_reset=must_reset,
    )
    user.set_password(PASSWORD)
    db_session.add(user)
    db_session.flush()

    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Role-{suffix}")
    db_session.add(role)
    db_session.flush()
    permission = Permission.query.filter_by(name="student.read.all").first()
    if permission is None:
        permission = Permission(id=_new_id("perm-"), name="student.read.all")
        db_session.add(permission)
        db_session.flush()
    db_session.add(RolePermission(
        tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
    ))
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")
    return user, generate_access_token(user)


def _headers(tenant, token):
    return {
        "X-Tenant-Subdomain": tenant.subdomain,
        "Authorization": f"Bearer {token}",
    }


# ---------------------------------------------------------------------------
# Blocked
# ---------------------------------------------------------------------------

def test_a_flagged_account_cannot_use_the_rest_api(client, db_session, tenant):
    _user, token = _account(db_session, tenant, must_reset=True)

    response = client.get("/api/students/", headers=_headers(tenant, token))

    assert response.status_code == 403, response.get_json()
    body = response.get_json()
    assert "PasswordResetRequired" in str(body), body


def test_the_refusal_is_not_a_401(client, db_session, tenant):
    """401 would sign the Expo client out and hide the reset screen."""
    _user, token = _account(db_session, tenant, must_reset=True)

    response = client.get("/api/students/", headers=_headers(tenant, token))

    assert response.status_code != 401


def test_a_flagged_account_cannot_use_graphql(client, db_session, tenant):
    """Password operations are REST, so GraphQL has no legitimate use here."""
    _user, token = _account(db_session, tenant, must_reset=True)

    body = client.post(
        GRAPHQL_PATH,
        json={"query": "query { students(first: 1) { totalCount } }"},
        headers=_headers(tenant, token),
    ).get_json()

    assert body.get("errors"), body
    codes = [e["extensions"].get("code") for e in body["errors"]]
    assert codes == ["PASSWORD_RESET_REQUIRED"], (
        "a client must be able to tell this apart from a plain FORBIDDEN — "
        "one means 'you cannot', the other means 'do this first'"
    )


# ---------------------------------------------------------------------------
# The way out stays open
# ---------------------------------------------------------------------------

def test_a_flagged_account_can_set_its_new_password(client, db_session, tenant):
    _user, token = _account(db_session, tenant, must_reset=True)

    response = client.post(
        "/api/auth/password/force-reset",
        json={"new_password": NEW_PASSWORD},
        headers=_headers(tenant, token),
    )

    assert response.status_code == 200, response.get_json()


def test_a_flagged_account_can_read_its_own_profile(client, db_session, tenant):
    """The client reads this to render, including the reset screen itself."""
    _user, token = _account(db_session, tenant, must_reset=True)

    response = client.get("/api/auth/profile", headers=_headers(tenant, token))

    assert response.status_code == 200, response.get_json()


def test_a_flagged_account_can_log_out(client, db_session, tenant):
    _user, token = _account(db_session, tenant, must_reset=True)

    response = client.post("/api/auth/logout", headers=_headers(tenant, token))

    assert response.status_code != 403, response.get_json()


def test_the_block_lifts_once_the_password_is_changed(client, db_session, tenant):
    user, token = _account(db_session, tenant, must_reset=True)

    assert client.get(
        "/api/students/", headers=_headers(tenant, token)
    ).status_code == 403

    changed = client.post(
        "/api/auth/password/force-reset",
        json={"new_password": NEW_PASSWORD},
        headers=_headers(tenant, token),
    )
    assert changed.status_code == 200, changed.get_json()

    db_session.refresh(user)
    assert user.force_password_reset is False
    assert client.get(
        "/api/students/", headers=_headers(tenant, token)
    ).status_code == 200


# ---------------------------------------------------------------------------
# Everyone else is untouched
# ---------------------------------------------------------------------------

def test_an_ordinary_account_is_unaffected(client, db_session, tenant):
    _user, token = _account(db_session, tenant, must_reset=False)

    assert client.get(
        "/api/students/", headers=_headers(tenant, token)
    ).status_code == 200
