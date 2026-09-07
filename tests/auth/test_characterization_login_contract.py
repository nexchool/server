"""Phase −1 — the login response, the session it writes, and the token it mints.

CHARACTERIZATION. These tests describe what `POST /api/auth/login` and
`_finalize_login` do **today**, not what the identity specification says they
should eventually do. Nothing here is an endorsement: where current behaviour
looks wrong it is asserted anyway, with a comment saying so, because the point
of the suite is that Phase 0 cannot change it by accident.

The one that matters most is `test_the_login_response_carries_exactly_these_keys`.
`_finalize_login` is explicitly meant to survive the Phase 0d refactor
unchanged; if a field appears, disappears or is renamed, that test fails.
"""

from __future__ import annotations

import uuid

import pytest

from tests.auth._characterization import (
    auth_cookie,
    decode_access_token,
    live_sessions_for,
    login,
    make_account,
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
# Group 1 — happy path and the response contract
# ---------------------------------------------------------------------------

def test_a_correct_password_signs_the_account_in(client, tenant, account):
    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["success"] is True
    assert body["message"] == "Login successful"


def test_the_login_response_carries_exactly_these_keys(client, tenant, account):
    """The `_finalize_login` contract. A future refactor that adds, removes or
    renames a top-level field fails here — which is the whole point."""
    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert set(data) == {
        "access_token",
        "refresh_token",
        "tenant_id",
        "subdomain",
        "tenant_name",
        "user",
        "permissions",
        "enabled_features",
        "is_platform_admin",
        "is_subadmin",
        "is_setup_complete",
        "force_password_reset",
        "allowed_unit_ids",
    }


def test_the_user_object_carries_exactly_these_keys(client, tenant, account):
    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert set(data["user"]) == {
        "id",
        "email",
        "name",
        "email_verified",
        "profile_picture_url",
    }


def test_the_response_describes_the_account_and_the_school(
    client, tenant, account
):
    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert data["user"]["id"] == account.id
    assert data["user"]["email"] == account.email
    assert data["user"]["email_verified"] is True
    assert data["tenant_id"] == str(tenant.id)
    assert data["subdomain"] == tenant.subdomain
    assert data["tenant_name"] == tenant.name


def test_a_signed_in_account_receives_its_permissions(client, tenant, account):
    """Permissions come from the person's employment, never from the account
    (ADR-013). An empty set is refused — see the failure suite."""
    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert isinstance(data["permissions"], list)
    assert "student.read.all" in data["permissions"]


def test_the_flags_a_client_boots_with(client, tenant, account):
    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert data["is_platform_admin"] is False
    assert data["is_subadmin"] is False
    assert data["force_password_reset"] is False
    assert isinstance(data["is_setup_complete"], bool)
    assert isinstance(data["enabled_features"], list)
    # Unrestricted branch scope is None, not an empty list — an empty list
    # would mean "no campuses at all" to every consumer.
    assert data["allowed_unit_ids"] is None


def test_enabled_features_are_the_tenants_effective_flags(
    client, tenant, account
):
    from core.feature_flags import get_tenant_enabled_features

    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert sorted(data["enabled_features"]) == sorted(
        get_tenant_enabled_features(tenant.id)
    )


# ---------------------------------------------------------------------------
# Group 1 — tokens and the cookie
# ---------------------------------------------------------------------------

def test_login_mints_an_access_token_and_a_refresh_token(
    client, tenant, account
):
    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert data["access_token"]
    assert data["refresh_token"]
    assert data["access_token"] != data["refresh_token"]


def test_the_access_token_carries_exactly_these_claims(client, tenant, account):
    """The claim set, pinned exactly.

    Phase 0d added `tid` (the school the token acts in) and `amr` (how its
    holder proved who they are — the standard name for that). `email` stays for
    a deprecation window: a mobile build in the field still reads it, and it is
    removed only after a full release cycle.

    Phase 8 added `jti` and `sid`. `sid` is the load-bearing one: validation
    checks that session is still live, which is what turned revocation from a
    promise about future refreshes into something felt on the next request.
    """
    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    claims = decode_access_token(data["access_token"])

    assert set(claims) == {
        "sub", "email", "is_platform_admin", "type", "iat", "exp", "tid", "amr",
        "jti", "sid",
    }
    assert claims["jti"]
    assert claims["sid"]
    assert claims["sub"] == account.id
    assert claims["email"] == account.email
    assert claims["is_platform_admin"] is False
    assert claims["type"] == "access"
    assert claims["tid"] == str(tenant.id)
    assert claims["amr"] == "email_password"


def test_the_refresh_token_is_opaque_and_carries_nothing(
    client, tenant, account
):
    """It used to be a JWT of `{sub, type, iat, exp}`.

    That was the whole of the collision defect: timestamps are whole seconds,
    so two sign-ins by one account inside one second produced byte-identical
    tokens. It is now 48 random bytes with no structure at all — nothing to
    decode, nothing to collide, and nothing about the holder recoverable from
    it if it leaks.
    """
    import jwt as pyjwt

    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    token = data["refresh_token"]
    assert token and len(token) >= 40
    with pytest.raises(pyjwt.DecodeError):
        decode_access_token(token)


def test_the_access_token_lifetime_is_the_configured_default(
    client, tenant, account
):
    from modules.auth.services import JWT_ACCESS_MINUTES

    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]
    claims = decode_access_token(data["access_token"])

    lifetime_minutes = (claims["exp"] - claims["iat"]) / 60
    assert lifetime_minutes == pytest.approx(JWT_ACCESS_MINUTES, abs=1)


def test_a_platform_session_timeout_setting_overrides_the_token_lifetime(
    client, db_session, tenant, account
):
    """`_finalize_login` reads `session_timeout_minutes` and clamps it to
    5..10080 minutes. Characterized because the refactor is meant to preserve
    it and nothing else covers it."""
    from core.models import PlatformSetting

    db_session.add(PlatformSetting(key="session_timeout_minutes", value="60"))
    db_session.flush()

    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]
    claims = decode_access_token(data["access_token"])

    assert (claims["exp"] - claims["iat"]) / 60 == pytest.approx(60, abs=1)


def test_login_sets_an_httponly_auth_cookie(client, tenant, account):
    """The panel authenticates from this cookie rather than a header."""
    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    )

    cookie = auth_cookie(response)
    assert cookie is not None, response.headers.getlist("Set-Cookie")
    assert "HttpOnly" in cookie
    assert cookie.split("auth-token=", 1)[1].split(";")[0] == (
        response.get_json()["data"]["access_token"]
    )


# ---------------------------------------------------------------------------
# Group 2 — the session row login writes
# ---------------------------------------------------------------------------

def test_a_successful_login_creates_exactly_one_session(
    client, db_session, tenant, account
):
    assert sessions_for(account.id) == []

    login(client, email=account.email, password=PASSWORD, tenant_id=tenant.id)

    assert len(sessions_for(account.id)) == 1


def test_the_refresh_token_is_never_stored_in_the_clear(
    client, db_session, tenant, account
):
    """It used to sit verbatim in a column, so a database dump was a set of
    working credentials. Only a digest is kept now; the value exists in the
    client's storage and nowhere else."""
    from modules.auth.refresh_models import RefreshToken, hash_refresh_token

    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]
    token = data["refresh_token"]

    session = sessions_for(account.id)[0]
    assert session.refresh_token is None

    row = RefreshToken.query.filter_by(session_id=session.id).one()
    assert row.token_hash == hash_refresh_token(token)
    assert token not in repr(
        {c.name: getattr(row, c.name) for c in row.__table__.columns}
    )


def test_a_new_session_starts_live_and_scoped_to_the_tenant(
    client, db_session, tenant, account
):
    login(client, email=account.email, password=PASSWORD, tenant_id=tenant.id)

    session = sessions_for(account.id)[0]
    assert session.user_id == account.id
    assert session.tenant_id == tenant.id
    assert session.revoked is False
    assert session.revoked_at is None
    assert session.created_at is not None
    assert session.refresh_token_expires_at is not None
    # Never touched, so a refresh can be told apart from a sign-in.
    assert session.last_accessed_at is None


def test_the_refresh_token_expiry_matches_the_configured_window(
    client, db_session, tenant, account
):
    from core.school_time import utc_now
    from modules.auth.services import JWT_REFRESH_DAYS

    login(client, email=account.email, password=PASSWORD, tenant_id=tenant.id)

    session = sessions_for(account.id)[0]
    days = (session.refresh_token_expires_at - utc_now()).total_seconds() / 86400
    assert days == pytest.approx(JWT_REFRESH_DAYS, abs=0.1)


def test_the_session_records_how_the_account_signed_in(
    client, db_session, tenant, account
):
    """Phase 0d is where `sessions.login_method` stopped being decorative.

    It had existed since migration 001 with a default of "email" and nothing
    had ever written it, so every session said "email" because of the column
    rather than because anything had observed how the person signed in. The
    pipeline writes the strategy key.
    """
    client.post(
        "/api/auth/login",
        json={"email": account.email, "password": PASSWORD, "tenant_id": tenant.id},
        headers={"X-Client-Surface": "admin-web"},
    )

    session = sessions_for(account.id)[0]
    assert session.login_method == "email_password"
    assert session.client_surface == "admin-web"
    assert session.authenticated_identifier_id is not None


def test_a_client_that_declares_no_surface_is_recorded_as_unknown(
    client, db_session, tenant, account
):
    """Old builds send no header and must keep working."""
    login(client, email=account.email, password=PASSWORD, tenant_id=tenant.id)

    assert sessions_for(account.id)[0].client_surface == "unknown"


# ---------------------------------------------------------------------------
# Group 3 — request metadata reaching the session
# ---------------------------------------------------------------------------

def test_the_session_records_the_callers_address_and_user_agent(
    client, db_session, tenant, account
):
    client.post(
        "/api/auth/login",
        json={"email": account.email, "password": PASSWORD, "tenant_id": tenant.id},
        headers={"User-Agent": "CharacterizationAgent/1.0"},
        environ_base={"REMOTE_ADDR": "203.0.113.9"},
    )

    session = sessions_for(account.id)[0]
    assert session.ip_address == "203.0.113.9"
    assert session.user_agent == "CharacterizationAgent/1.0"


def test_device_info_is_a_second_copy_of_the_user_agent(
    client, db_session, tenant, account
):
    """EXISTING BEHAVIOUR. `device_info` and `user_agent` are both filled from
    the same header, so the column carries no independent information."""
    client.post(
        "/api/auth/login",
        json={"email": account.email, "password": PASSWORD, "tenant_id": tenant.id},
        headers={"User-Agent": "CharacterizationAgent/1.0"},
    )

    session = sessions_for(account.id)[0]
    assert session.device_info == session.user_agent


def test_a_missing_user_agent_stores_an_empty_string_not_null(
    client, db_session, tenant, account
):
    client.post(
        "/api/auth/login",
        json={"email": account.email, "password": PASSWORD, "tenant_id": tenant.id},
        headers={"User-Agent": ""},
    )

    session = sessions_for(account.id)[0]
    assert session.user_agent == ""


# ---------------------------------------------------------------------------
# Group 13 — the rest of the `_finalize_login` contract
# ---------------------------------------------------------------------------

def test_signing_in_twice_opens_a_second_live_session(
    client, db_session, tenant, account
):
    """Sessions are additive; signing in on a second device does not evict the
    first. Revocation is what ends a session, never another login."""
    login(client, email=account.email, password=PASSWORD, tenant_id=tenant.id)
    login(client, email=account.email, password=PASSWORD, tenant_id=tenant.id)

    assert len(live_sessions_for(account.id)) == 2


def test_login_stamps_last_login_at(client, db_session, tenant, account):
    assert account.last_login_at is None

    login(client, email=account.email, password=PASSWORD, tenant_id=tenant.id)

    db_session.refresh(account)
    assert account.last_login_at is not None


def test_a_successful_login_clears_the_failure_counter(
    client, db_session, tenant, account
):
    account.failed_login_count = 3
    db_session.flush()

    login(client, email=account.email, password=PASSWORD, tenant_id=tenant.id)

    db_session.refresh(account)
    assert account.failed_login_count == 0
    assert account.login_locked_until is None


def test_an_unverified_email_is_refused_before_any_token_is_minted(
    client, db_session, tenant
):
    user = make_account(
        db_session, tenant, password=PASSWORD, email_verified=False
    )

    response = login(
        client, email=user.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "EmailNotVerified"
    assert sessions_for(user.id) == []


def test_an_account_with_no_permissions_is_refused(client, db_session, tenant):
    """EXISTING BEHAVIOUR worth knowing before Phase 0: the password was
    correct. `NoPermissions` is reached only *after* verification, so it is
    not a way to probe whether an account exists — a property the refactor
    must preserve."""
    from tests.auth._characterization import make_user

    user = make_user(db_session, tenant, password=PASSWORD)  # no employment

    response = login(
        client, email=user.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "NoPermissions"
    assert sessions_for(user.id) == []


def test_a_suspended_account_is_refused_and_gets_no_session(
    client, db_session, tenant, account
):
    account.is_suspended = True
    db_session.flush()

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "AccountSuspended"
    assert sessions_for(account.id) == []


def test_a_soft_deleted_account_cannot_sign_in(
    client, db_session, tenant, account
):
    from core.school_time import utc_now

    account.deleted_at = utc_now()
    db_session.flush()

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"


def test_a_sub_admin_is_reported_as_one(client, db_session, tenant):
    from modules.rbac.models import Role
    from tests.auth._characterization import make_user, new_id
    from tests.conftest import grant_profile_to

    user = make_user(db_session, tenant, password=PASSWORD)
    suffix = uuid.uuid4().hex[:8]
    role = Role(
        id=new_id("r-"),
        tenant_id=tenant.id,
        name=f"subadmin:{suffix}",
        is_subadmin=True,
    )
    db_session.add(role)
    db_session.flush()

    from modules.rbac.models import Permission, RolePermission

    permission = Permission.query.filter_by(name="student.read.all").first()
    if permission is None:
        permission = Permission(id=new_id("perm-"), name="student.read.all")
        db_session.add(permission)
        db_session.flush()
    db_session.add(
        RolePermission(
            tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
        )
    )
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")

    data = login(
        client, email=user.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert data["is_subadmin"] is True
