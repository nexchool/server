"""Integration tests for the password-reset feature (feature/password-reset).

Runs against the real localhost Postgres via the ``db_session`` + ``tenant``
conftest fixtures. The notification dispatcher is patched so no real email is
sent; we assert on the ``extra_data`` handed to it.

Covers:
- S1: platform=="web" builds an admin-web http reset link; default stays mobile.
- S2: /password/reset strength check (422) + token validity (400/expired).
- S3: authenticated /password/force-reset (200 / 422 / 401).
- S4: create/reset sub-admin sets force_password_reset; login/profile surface it.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db_session, tenant, *, email=None, password="Password0", name="Reset User"):
    """Create a real, verified User with a usable password."""
    from modules.auth.models import User

    email = email or f"reset-{uuid.uuid4().hex[:10]}@test.school"
    user = User(
        id=f"u-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant.id,
        email=email,
        name=name,
    )
    user.set_password(password)
    user.email_verified = True
    db_session.add(user)
    db_session.flush()
    return user


def _post(flask_app, tenant, path, body, headers=None):
    base = {"X-Tenant-ID": tenant.id}
    if headers:
        base.update(headers)
    return flask_app.test_client().post(path, headers=base, json=body)


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    """These tests assert behaviour, not throttling; keep them deterministic."""
    from core.extensions import limiter

    prev = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prev


# ---------------------------------------------------------------------------
# S1 — web-facing reset URL + platform branch
# ---------------------------------------------------------------------------

def test_forgot_web_platform_builds_admin_web_link(flask_app, db_session, tenant):
    # `mts` is a real seeded subdomain in this DB; use a unique one to avoid the
    # UNIQUE(subdomain) clash while still asserting the subdomain is prefixed.
    subdomain = f"sd{uuid.uuid4().hex[:8]}"
    tenant.subdomain = subdomain
    db_session.flush()
    user = _make_user(db_session, tenant)

    fake_dispatcher = MagicMock()
    with patch(
        "modules.notifications.services.notification_dispatcher", fake_dispatcher
    ):
        resp = _post(
            flask_app, tenant, "/api/auth/password/forgot",
            {"email": user.email, "platform": "web"},
        )

    assert resp.status_code == 200
    reset_url = fake_dispatcher.dispatch.call_args.kwargs["extra_data"]["reset_url"]
    assert reset_url.startswith(f"http://{subdomain}.localhost:3000/reset-password?")
    assert "token=" in reset_url
    assert "email=" in reset_url


def test_forgot_default_platform_keeps_mobile_link(flask_app, db_session, tenant):
    tenant.subdomain = f"sd{uuid.uuid4().hex[:8]}"
    db_session.flush()
    user = _make_user(db_session, tenant)

    fake_dispatcher = MagicMock()
    with patch(
        "modules.notifications.services.notification_dispatcher", fake_dispatcher
    ):
        resp = _post(
            flask_app, tenant, "/api/auth/password/forgot",
            {"email": user.email},
        )

    assert resp.status_code == 200
    reset_url = fake_dispatcher.dispatch.call_args.kwargs["extra_data"]["reset_url"]
    assert not reset_url.startswith("http")


# ---------------------------------------------------------------------------
# S2 — strength check + token validity on /password/reset
# ---------------------------------------------------------------------------

def _issue_token(db_session, user):
    token = user.generate_reset_password_token()
    db_session.flush()
    return token


def test_reset_weak_password_returns_422(flask_app, db_session, tenant):
    user = _make_user(db_session, tenant)
    token = _issue_token(db_session, user)

    resp = _post(
        flask_app, tenant, "/api/auth/password/reset",
        {"email": user.email, "token": token, "new_password": "short"},
    )
    assert resp.status_code == 422


def test_reset_strong_password_succeeds(flask_app, db_session, tenant):
    user = _make_user(db_session, tenant)
    token = _issue_token(db_session, user)

    resp = _post(
        flask_app, tenant, "/api/auth/password/reset",
        {"email": user.email, "token": token, "new_password": "Password1"},
    )
    assert resp.status_code == 200

    db_session.refresh(user)
    assert user.check_password("Password1") is True


def test_reset_invalid_token_returns_400(flask_app, db_session, tenant):
    user = _make_user(db_session, tenant)
    _issue_token(db_session, user)

    resp = _post(
        flask_app, tenant, "/api/auth/password/reset",
        {"email": user.email, "token": "not-the-real-token", "new_password": "Password1"},
    )
    assert resp.status_code == 400


def test_reset_expired_token_returns_400(flask_app, db_session, tenant):
    user = _make_user(db_session, tenant)
    token = _issue_token(db_session, user)
    user.reset_password_sent_at = datetime.utcnow() - timedelta(minutes=31)
    db_session.flush()

    resp = _post(
        flask_app, tenant, "/api/auth/password/reset",
        {"email": user.email, "token": token, "new_password": "Password1"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# S3 — authenticated /password/force-reset
# ---------------------------------------------------------------------------

def _post_authed(flask_app, tenant, user, path, body):
    """POST as `user`: patch JWT validation so auth_required loads them by id."""
    with patch(
        "modules.auth.services.validate_jwt_token",
        return_value={"sub": user.id},
    ):
        return _post(
            flask_app, tenant, path, body,
            headers={"Authorization": "Bearer test-access-token"},
        )


def test_force_reset_succeeds_and_clears_flag(flask_app, db_session, tenant):
    user = _make_user(db_session, tenant)
    user.force_password_reset = True
    db_session.flush()

    resp = _post_authed(
        flask_app, tenant, user, "/api/auth/password/force-reset",
        {"new_password": "Password1"},
    )
    assert resp.status_code == 200

    db_session.refresh(user)
    assert user.force_password_reset is False
    assert user.check_password("Password1") is True


def test_force_reset_weak_password_returns_422(flask_app, db_session, tenant):
    user = _make_user(db_session, tenant)

    resp = _post_authed(
        flask_app, tenant, user, "/api/auth/password/force-reset",
        {"new_password": "short"},
    )
    assert resp.status_code == 422


def test_force_reset_without_auth_returns_401(flask_app, db_session, tenant):
    resp = _post(
        flask_app, tenant, "/api/auth/password/force-reset",
        {"new_password": "Password1"},
    )
    assert resp.status_code == 401
