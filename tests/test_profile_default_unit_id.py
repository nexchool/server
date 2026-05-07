"""Tests for default_unit_id in GET /api/auth/profile response — pure-Python, no Flask."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _make_fake_user(default_unit_id=None):
    fake_user = MagicMock()
    fake_user.id = 1
    fake_user.email = "test@example.com"
    fake_user.name = "Test User"
    fake_user.email_verified = True
    fake_user.profile_picture_url = None
    fake_user.default_unit_id = default_unit_id
    fake_user.last_login_at = None
    fake_user.created_at = MagicMock()
    fake_user.created_at.isoformat.return_value = "2024-01-01T00:00:00"
    fake_user.tenant_id = "tenant-1"
    return fake_user


def _call_get_profile_inner(routes, fake_user):
    """Call the unwrapped get_profile function, bypassing Flask auth decorator."""
    captured = {}

    def fake_success_response(data, status_code):
        captured["data"] = data
        captured["status_code"] = status_code
        return ("ok", status_code)

    fake_g = type("G", (), {"current_user": fake_user})()

    # Access the underlying function via __wrapped__ to skip @auth_required
    inner_fn = routes.get_profile.__wrapped__

    fake_tenant_cls = MagicMock()
    fake_tenant_cls.query.get.return_value = None  # tenant lookup returns nothing → tenant_name stays None

    with (
        patch.object(routes, "resolve_tenant_for_auth", return_value=None),
        patch.object(routes, "g", fake_g),
        patch.object(routes, "success_response", fake_success_response),
        patch("modules.rbac.services.get_user_permissions", return_value=[]),
        patch("modules.rbac.services.get_user_roles", return_value=[]),
        patch("core.feature_flags.get_tenant_enabled_features", return_value=[]),
        patch.object(routes, "profile_picture_public_url", return_value=None),
        patch("core.models.Tenant", fake_tenant_cls),
    ):
        inner_fn()

    return captured


def test_get_profile_includes_default_unit_id_none():
    """Profile response includes default_unit_id key; value is None for a fresh user."""
    from modules.auth import routes

    captured = _call_get_profile_inner(routes, _make_fake_user(default_unit_id=None))

    user_data = captured["data"]["user"]
    assert "default_unit_id" in user_data, "default_unit_id key must be present in profile response"
    assert user_data["default_unit_id"] is None


def test_get_profile_includes_default_unit_id_when_set():
    """Profile response carries the default_unit_id value when the user has one set."""
    from modules.auth import routes

    captured = _call_get_profile_inner(routes, _make_fake_user(default_unit_id="unit-abc-123"))

    user_data = captured["data"]["user"]
    assert user_data["default_unit_id"] == "unit-abc-123"
