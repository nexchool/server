"""``@auth_required`` re-checks account status on a VALID access token.

A live access token outlives suspension / soft-delete (~15 min) unless status
is re-checked on every request. These tests drive the decorator's valid-token
branch directly with a pushed request context and a mocked ``validate_jwt_token``
so no DB or real JWT is needed:

  (a) active user        -> the wrapped route runs (200)
  (b) suspended user     -> 401 (immediate cutoff)
  (c) soft-deleted user  -> 401 (immediate cutoff)

401 (not 403) is intentional: admin-web's api.ts treats 401 as "log out +
redirect to /login", where a re-login then surfaces the proper 403
AccountSuspended message.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _fake_user(*, is_suspended=False, deleted_at=None):
    return SimpleNamespace(
        id="u-1",
        is_suspended=is_suspended,
        deleted_at=deleted_at,
    )


def _call_protected(flask_app, user):
    """Invoke a route wrapped by @auth_required with a valid access token.

    Returns (status_code, ran) where ``ran`` is True only if the wrapped route
    body executed (i.e. auth passed).
    """
    from core.decorators.auth import auth_required

    ran = {"value": False}

    @auth_required
    def protected_route():
        ran["value"] = True
        return ("ok", 200)

    with flask_app.test_request_context(
        "/protected",
        method="GET",
        headers={"Authorization": "Bearer valid-access-token"},
    ):
        with (
            patch(
                "modules.auth.services.validate_jwt_token",
                return_value={"sub": user.id},
            ),
            patch("modules.auth.models.User") as fake_user_cls,
        ):
            fake_user_cls.query.get.return_value = user
            result = protected_route()

    status = result[1] if isinstance(result, tuple) else result.status_code
    return status, ran["value"]


def test_active_user_passes_with_valid_token(flask_app):
    status, ran = _call_protected(flask_app, _fake_user())
    assert status == 200
    assert ran is True


def test_suspended_user_rejected_with_401(flask_app):
    status, ran = _call_protected(flask_app, _fake_user(is_suspended=True))
    assert status == 401
    assert ran is False


def test_soft_deleted_user_rejected_with_401(flask_app):
    from datetime import datetime

    status, ran = _call_protected(
        flask_app, _fake_user(deleted_at=datetime.utcnow())
    )
    assert status == 401
    assert ran is False
