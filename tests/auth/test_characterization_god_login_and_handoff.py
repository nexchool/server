"""Phase −1 — the operator's two ways into a tenant, and the forced-reset gate.

CHARACTERIZATION. Two things are pinned here that the identity specification
promises to preserve untouched through every later phase:

1. **God-login precedence.** A real tenant user with those credentials always
   wins; the platform admin is tried only when no tenant user authenticated.
2. **The one-time login link.** Possession of a short-lived, single-use,
   hashed-at-rest Redis code IS the credential, and it fails closed.

`tests/test_superadmin_god_login.py` already covers the permission side of
god-mode. What is added here is the part that the refactor could break without
noticing: the response contract, the session it writes, and the handoff route
end to end.

The forced-password-reset group covers the LOGIN side of that gate;
`tests/test_force_password_reset_enforced.py` already covers enforcement on
the protected API.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from tests.auth._characterization import (
    login,
    make_account,
    make_platform_admin,
    make_tenant,
    sessions_for,
)

PASSWORD = "Sup3rSecret1"
TENANT_PASSWORD = "Ten4ntSecret1"
NEW_PASSWORD = "Ch0senByMe99"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def home_tenant(db_session):
    return make_tenant(db_session, subdomain_prefix="chz-hq")


@pytest.fixture
def platform_admin(db_session, home_tenant):
    return make_platform_admin(db_session, home_tenant, password=PASSWORD)


class FakeRedis:
    """Enough Redis for handoff: set(nx/ex) and the atomic GET+DEL eval."""

    def __init__(self):
        self.store = {}

    def set(self, k, v, ex=None, nx=False):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    def eval(self, script, numkeys, *keys):
        value = self.store.pop(keys[0], None)
        return value


def _patch_redis(fake):
    from core import cache

    return patch.object(cache, "redis_client", return_value=fake)


# ---------------------------------------------------------------------------
# Group 11 — god-login
# ---------------------------------------------------------------------------

def test_a_platform_admin_enters_any_tenant_with_their_own_password(
    client, tenant, platform_admin
):
    response = login(
        client, email=platform_admin.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 200, response.get_json()
    data = response.get_json()["data"]
    assert data["is_platform_admin"] is True
    assert data["tenant_id"] == str(tenant.id)


def test_god_login_reports_the_entered_tenant_not_the_admins_home(
    client, tenant, home_tenant, platform_admin
):
    data = login(
        client, email=platform_admin.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert data["tenant_id"] == str(tenant.id)
    assert data["tenant_id"] != str(home_tenant.id)
    assert data["subdomain"] == tenant.subdomain


def test_god_login_returns_the_synthetic_permission_and_no_features(
    client, tenant, platform_admin
):
    """EXISTING BEHAVIOUR: god-mode is a single synthetic key plus an empty
    feature list — plan gating is not applied to the operator."""
    data = login(
        client, email=platform_admin.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert data["permissions"] == ["system.manage"]
    assert data["enabled_features"] == []
    assert data["is_subadmin"] is False


def test_god_login_uses_the_same_response_contract_as_a_normal_login(
    client, tenant, platform_admin
):
    """Both paths go through `_finalize_login`, so the key set must match."""
    data = login(
        client, email=platform_admin.email, password=PASSWORD, tenant_id=tenant.id
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


def test_the_god_session_belongs_to_the_admins_home_tenant(
    client, db_session, tenant, home_tenant, platform_admin
):
    """EXISTING BEHAVIOUR, and the reason `load_without_tenant_scope` exists:
    the session row lives in the admin's OWN tenant while the request is scoped
    to the entered one."""
    login(client, email=platform_admin.email, password=PASSWORD, tenant_id=tenant.id)

    session = sessions_for(platform_admin.id)[0]
    assert session.tenant_id == home_tenant.id
    assert session.tenant_id != tenant.id


def test_the_access_token_marks_the_platform_admin(client, tenant, platform_admin):
    from tests.auth._characterization import decode_access_token

    data = login(
        client, email=platform_admin.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert decode_access_token(data["access_token"])["is_platform_admin"] is True


def test_a_tenant_user_sharing_the_admins_address_wins(
    client, db_session, tenant, platform_admin
):
    """The precedence rule the specification requires be preserved: god-login
    is tried only when no tenant user authenticated."""
    twin = make_account(
        db_session, tenant, password=TENANT_PASSWORD, email=platform_admin.email
    )

    data = login(
        client,
        email=platform_admin.email,
        password=TENANT_PASSWORD,
        tenant_id=tenant.id,
    ).get_json()["data"]

    assert data["is_platform_admin"] is False
    assert data["user"]["id"] == twin.id


def test_the_admins_own_password_still_works_alongside_a_twin(
    client, db_session, tenant, platform_admin
):
    """The other half of precedence: the twin does not shadow the operator."""
    make_account(
        db_session, tenant, password=TENANT_PASSWORD, email=platform_admin.email
    )

    data = login(
        client, email=platform_admin.email, password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert data["is_platform_admin"] is True


def test_god_login_is_audited_with_the_entered_subdomain(
    client, db_session, tenant, platform_admin
):
    from core.models import AuditLog

    login(client, email=platform_admin.email, password=PASSWORD, tenant_id=tenant.id)

    entry = AuditLog.query.filter_by(
        action="tenant.admin_web_entered",
        platform_admin_id=platform_admin.id,
        tenant_id=tenant.id,
    ).first()
    assert entry is not None
    assert entry.extra_data == {"subdomain": tenant.subdomain}


def test_a_normal_login_writes_no_platform_audit_entry(
    client, db_session, tenant
):
    from core.models import AuditLog

    account = make_account(db_session, tenant, password=TENANT_PASSWORD)

    login(client, email=account.email, password=TENANT_PASSWORD, tenant_id=tenant.id)

    assert (
        AuditLog.query.filter_by(
            action="tenant.admin_web_entered", tenant_id=tenant.id
        ).first()
        is None
    )


# ---------------------------------------------------------------------------
# Group 12 — the one-time login link
# ---------------------------------------------------------------------------

def test_a_minted_code_opens_a_god_session_for_that_tenant(
    client, db_session, tenant, platform_admin
):
    from modules.auth import handoff

    with _patch_redis(FakeRedis()):
        code = handoff.issue(platform_admin.id, tenant.id)
        response = client.post("/api/auth/login-link/redeem", json={"code": code})

    assert response.status_code == 200, response.get_json()
    data = response.get_json()["data"]
    assert data["is_platform_admin"] is True
    assert data["tenant_id"] == str(tenant.id)
    assert data["permissions"] == ["system.manage"]
    assert data["access_token"]


def test_redemption_returns_the_same_shape_as_password_login(
    client, db_session, tenant, platform_admin
):
    """Both call `_finalize_login`, so admin-web's session handling is
    identical on either path."""
    from modules.auth import handoff

    with _patch_redis(FakeRedis()):
        code = handoff.issue(platform_admin.id, tenant.id)
        data = client.post(
            "/api/auth/login-link/redeem", json={"code": code}
        ).get_json()["data"]

    assert set(data) == set(
        login(
            client,
            email=platform_admin.email,
            password=PASSWORD,
            tenant_id=tenant.id,
        ).get_json()["data"]
    )


def test_a_code_can_only_be_redeemed_once(
    client, db_session, tenant, platform_admin
):
    from modules.auth import handoff

    with _patch_redis(FakeRedis()):
        code = handoff.issue(platform_admin.id, tenant.id)
        first = client.post("/api/auth/login-link/redeem", json={"code": code})
        second = client.post("/api/auth/login-link/redeem", json={"code": code})

    assert first.status_code == 200
    assert second.status_code == 401
    assert second.get_json()["error"] == "InvalidLoginLink"


def test_an_unknown_code_is_refused(client, tenant):
    with _patch_redis(FakeRedis()):
        response = client.post(
            "/api/auth/login-link/redeem", json={"code": "never-issued"}
        )

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidLoginLink"


def test_an_empty_code_is_refused(client, tenant):
    with _patch_redis(FakeRedis()):
        response = client.post("/api/auth/login-link/redeem", json={"code": ""})

    assert response.status_code == 401


def test_redemption_fails_closed_when_redis_is_unavailable(
    client, db_session, tenant, platform_admin
):
    from modules.auth import handoff

    fake = FakeRedis()
    with _patch_redis(fake):
        code = handoff.issue(platform_admin.id, tenant.id)

    with _patch_redis(None):
        response = client.post("/api/auth/login-link/redeem", json={"code": code})

    assert response.status_code == 401


def test_a_code_for_a_suspended_tenant_is_refused(
    client, db_session, tenant, platform_admin
):
    """Mirrors the password path: a suspended school blocks everyone, operator
    included. Un-suspend from the panel first."""
    from core.models import TENANT_STATUS_SUSPENDED

    from modules.auth import handoff

    with _patch_redis(FakeRedis()):
        code = handoff.issue(platform_admin.id, tenant.id)
        tenant.status = TENANT_STATUS_SUSPENDED
        db_session.flush()
        response = client.post("/api/auth/login-link/redeem", json={"code": code})

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidLoginLink"


def test_a_code_naming_a_non_platform_account_is_refused(
    client, db_session, tenant
):
    """Only a platform admin can be handed off, whatever the code says."""
    from modules.auth import handoff

    ordinary = make_account(db_session, tenant, password=TENANT_PASSWORD)

    with _patch_redis(FakeRedis()):
        code = handoff.issue(ordinary.id, tenant.id)
        response = client.post("/api/auth/login-link/redeem", json={"code": code})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Group 10 — the forced-password-reset gate, from the login side
# ---------------------------------------------------------------------------

def test_an_unflagged_account_reports_no_forced_reset(client, db_session, tenant):
    account = make_account(db_session, tenant, password=TENANT_PASSWORD)

    data = login(
        client, email=account.email, password=TENANT_PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert data["force_password_reset"] is False


def test_a_flagged_account_still_signs_in_and_is_told_so(
    client, db_session, tenant
):
    """EXISTING BEHAVIOUR: the flag does not block login. A fully-formed
    session and token are issued; the restriction bites afterwards, on every
    other route."""
    account = make_account(
        db_session, tenant, password=TENANT_PASSWORD, force_password_reset=True
    )

    data = login(
        client, email=account.email, password=TENANT_PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    assert data["force_password_reset"] is True
    assert data["access_token"]
    assert len(sessions_for(account.id)) == 1


def test_a_flagged_account_may_still_read_its_own_profile(
    client, db_session, tenant
):
    """`/api/auth/profile` is on the allow-list, so the client can render the
    reset screen."""
    account = make_account(
        db_session, tenant, password=TENANT_PASSWORD, force_password_reset=True
    )
    tokens = login(
        client, email=account.email, password=TENANT_PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    response = client.get(
        "/api/auth/profile",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {tokens['access_token']}",
        },
    )

    assert response.status_code == 200


def test_a_flagged_account_is_refused_elsewhere_with_403_not_401(
    client, db_session, tenant
):
    """403, because the caller IS signed in — a 401 would sign the Expo client
    out of the session it needs to set the new password."""
    account = make_account(
        db_session,
        tenant,
        password=TENANT_PASSWORD,
        permissions=("student.read.all",),
        force_password_reset=True,
    )
    tokens = login(
        client, email=account.email, password=TENANT_PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    response = client.get(
        "/api/students/",
        headers={
            "X-Tenant-Subdomain": tenant.subdomain,
            "Authorization": f"Bearer {tokens['access_token']}",
        },
    )

    assert response.status_code == 403
    assert "PasswordResetRequired" in str(response.get_json())


def test_setting_a_new_password_clears_the_flag_and_reopens_the_api(
    client, db_session, tenant
):
    account = make_account(
        db_session,
        tenant,
        password=TENANT_PASSWORD,
        permissions=("student.read.all",),
        force_password_reset=True,
    )
    tokens = login(
        client, email=account.email, password=TENANT_PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]
    headers = {
        "X-Tenant-Subdomain": tenant.subdomain,
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-Refresh-Token": tokens["refresh_token"],
    }

    reset = client.post(
        "/api/auth/password/force-reset",
        json={"new_password": NEW_PASSWORD},
        headers=headers,
    )

    assert reset.status_code == 200, reset.get_json()
    db_session.refresh(account)
    assert account.force_password_reset is False
    assert client.get("/api/students/", headers=headers).status_code == 200


def test_the_exempt_path_list_is_what_it_is(client):
    """Pinned as data. The gate is only as good as this list, and the list is
    the difference between 'set your password' and 'you are locked out'."""
    from core.authentication import PASSWORD_RESET_EXEMPT_PATHS

    assert PASSWORD_RESET_EXEMPT_PATHS == frozenset(
        {
            "/api/auth/password/force-reset",
            "/api/auth/logout",
            "/api/auth/profile",
            "/api/auth/enabled-features",
        }
    )
