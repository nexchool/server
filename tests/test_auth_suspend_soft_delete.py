"""Login enforcement for suspended and soft-deleted users (Sub-Admins T2).

Covers:
  (a) A soft-deleted user (deleted_at IS NOT NULL) is invisible to
      User.get_user_by_email and to find_users_by_email_password, so it can
      never authenticate or receive reset/verification mail.
  (b) The login route returns 403 AccountSuspended for a suspended user,
      before any token is issued (both login paths share this gate).
  (c) A normal active, verified user still logs in successfully.

(a) uses the real-DB conftest fixtures (db_session, tenant) for full
PostgreSQL fidelity. (b)/(c) call the unwrapped login route with mocks so
the suspended gate is exercised without the limiter, platform settings,
RBAC seeding or session machinery.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


# ---------------------------------------------------------------------------
# (a) soft-deleted users are invisible to lookups — real DB
# ---------------------------------------------------------------------------

import uuid
from datetime import datetime


def _make_user(db_session, tenant, *, email, deleted_at=None):
    from modules.auth.models import User

    user = User(
        id=f"u-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant.id,
        email=email,
        password_hash="x" * 60,
        name="Lookup User",
        email_verified=True,
        deleted_at=deleted_at,
    )
    db_session.add(user)
    db_session.flush()
    return user


def test_soft_deleted_user_not_returned_by_get_user_by_email(db_session, tenant):
    """get_user_by_email skips users with deleted_at set."""
    from modules.auth.models import User

    email = f"deleted-{uuid.uuid4().hex[:8]}@test.school"
    _make_user(db_session, tenant, email=email, deleted_at=datetime.utcnow())

    found = User.get_user_by_email(email, tenant_id=tenant.id)
    assert found is None


def test_active_user_returned_by_get_user_by_email(db_session, tenant):
    """Sanity: a non-deleted user with the same lookup is still found."""
    from modules.auth.models import User

    email = f"active-{uuid.uuid4().hex[:8]}@test.school"
    _make_user(db_session, tenant, email=email, deleted_at=None)

    found = User.get_user_by_email(email, tenant_id=tenant.id)
    assert found is not None
    assert found.email == email


def test_soft_deleted_user_not_matched_by_cross_tenant_search(db_session, tenant):
    """find_users_by_email_password never returns a soft-deleted user."""
    from modules.auth.models import User
    from modules.auth.services import find_users_by_email_password

    email = f"xdel-{uuid.uuid4().hex[:8]}@test.school"
    user = _make_user(db_session, tenant, email=email, deleted_at=datetime.utcnow())
    user.set_password("secret123")
    db_session.flush()

    matches = find_users_by_email_password(email, "secret123")
    assert matches == []


# ---------------------------------------------------------------------------
# (b)/(c) login route suspended gate — mocked, no DB
# ---------------------------------------------------------------------------

def _fake_user(*, is_suspended=False, email_verified=True, is_platform_admin=False):
    u = MagicMock()
    u.id = "u-1"
    u.tenant_id = "tenant-1"
    u.email = "user@test.school"
    u.name = "Test User"
    u.is_suspended = is_suspended
    u.email_verified = email_verified
    u.is_platform_admin = is_platform_admin
    u.profile_picture_url = None
    u.failed_login_count = 0
    u.login_locked_until = None
    return u


def _fake_tenant():
    t = MagicMock()
    t.id = "tenant-1"
    t.name = "Test School"
    t.subdomain = "test"
    return t


def _call_login(routes, *, request_json, authed_user):
    """Invoke the unwrapped login route on the tenant-specified path."""
    captured = {}

    def fake_error_response(error=None, message=None, status_code=None):
        captured["error"] = error
        captured["message"] = message
        captured["status_code"] = status_code
        return ({"error": error, "message": message}, status_code)

    def fake_success_response(data=None, message=None, status_code=200):
        captured["data"] = data
        captured["message"] = message
        captured["status_code"] = status_code
        return (MagicMock(), status_code)

    fake_request = MagicMock()
    fake_request.get_json.return_value = request_json

    inner = routes.login.__wrapped__

    with (
        patch.object(routes, "request", fake_request),
        patch.object(routes, "error_response", fake_error_response),
        patch.object(routes, "success_response", fake_success_response),
        patch.object(routes, "resolve_tenant_for_auth", return_value=None),
        patch.object(routes, "get_tenant_id", return_value="tenant-1"),
        patch.object(routes, "User") as fake_user_cls,
        patch.object(routes, "authenticate_user", return_value=authed_user),
        patch.object(routes, "g", MagicMock(tenant=_fake_tenant())),
        patch("modules.rbac.role_seeder.seed_roles_for_tenant", return_value=None),
        patch("modules.rbac.services.get_user_permissions", return_value=["perm.x"]),
        patch.object(routes, "generate_access_token", return_value="access-tok"),
        patch.object(routes, "create_session", return_value=MagicMock(refresh_token="rt")),
        patch("core.feature_flags.get_tenant_enabled_features", return_value=[]),
        patch.object(routes, "profile_picture_public_url", return_value=None),
    ):
        fake_user_cls.get_user_by_email.return_value = authed_user
        result = inner()

    return captured, result


def test_login_blocks_suspended_user_with_403():
    """A suspended user is rejected with 403 AccountSuspended before tokens issue."""
    from modules.auth import routes

    captured, _ = _call_login(
        routes,
        request_json={
            "email": "user@test.school",
            "password": "pw123456",
            "tenant_id": "tenant-1",
        },
        authed_user=_fake_user(is_suspended=True),
    )

    assert captured["status_code"] == 403
    assert captured["error"] == "AccountSuspended"


def test_login_allows_active_user():
    """A normal active, verified user proceeds to a 200 success response."""
    from modules.auth import routes

    captured, _ = _call_login(
        routes,
        request_json={
            "email": "user@test.school",
            "password": "pw123456",
            "tenant_id": "tenant-1",
        },
        authed_user=_fake_user(is_suspended=False),
    )

    assert captured["status_code"] == 200
    assert captured["message"] == "Login successful"
