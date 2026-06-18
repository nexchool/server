"""Wrong-method and empty-body requests on auth routes return clean 4xx, never 500.

Regression: ``GET /api/auth/login`` returned 500 because werkzeug's ``MethodNotAllowed``
(405) had no dedicated handler and fell through to the catch-all ``Exception`` handler,
which flattened every error to 500 (app.py ``handle_unhandled_exception``). The fix
preserves HTTPException status codes + headers, so a wrong-method request now returns 405.

These tests hit the URL map (405 is decided before the view runs) and the login
validation branch — neither needs the database.
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def test_get_login_returns_405_not_500(flask_app):
    resp = flask_app.test_client().get("/api/auth/login")
    assert resp.status_code == 405
    body = resp.get_json()
    assert body is not None and body["success"] is False
    assert body["error"] == "MethodNotAllowed"
    # message is the generic status text, never the verbose werkzeug description
    # (guards against leaking a future abort(..., description="<sensitive>")).
    assert body["message"] == "Method Not Allowed"
    assert "requested URL" not in body["message"]


def test_get_login_405_advertises_allowed_methods(flask_app):
    resp = flask_app.test_client().get("/api/auth/login")
    assert resp.status_code == 405
    assert "POST" in (resp.headers.get("Allow") or "")


def test_post_only_auth_routes_reject_get_with_405(flask_app):
    client = flask_app.test_client()
    for path in (
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/password/forgot",
        "/api/auth/password/reset",
    ):
        resp = client.get(path)
        assert resp.status_code == 405, f"GET {path} -> {resp.status_code}, expected 405"


def test_post_login_without_body_returns_400(flask_app):
    from core.extensions import limiter

    previous = limiter.enabled
    limiter.enabled = False
    try:
        resp = flask_app.test_client().post("/api/auth/login")
        assert resp.status_code == 400
        body = resp.get_json()
        assert body is not None and body["success"] is False
    finally:
        limiter.enabled = previous
