"""CORS must permit the custom headers our own browser clients actually send.

A browser refuses to send the real request when a preflight response omits a
header the client asked for, and `fetch` surfaces that as a bare network
failure — so a missing entry here looks like "the API is unreachable", not
like a CORS problem. Every custom header admin-web / panel attach to a
request has to be on the allowlist.
"""

import pytest


PREFLIGHT_HEADERS = {
    "Origin": "http://localhost:3001",
    "Access-Control-Request-Method": "POST",
}


def _allowed_headers(flask_app, requested: str) -> set[str]:
    """Return the lower-cased header names a preflight is granted."""
    client = flask_app.test_client()
    response = client.options(
        "/api/auth/login",
        headers={**PREFLIGHT_HEADERS, "Access-Control-Request-Headers": requested},
    )
    granted = response.headers.get("Access-Control-Allow-Headers", "")
    return {h.strip().lower() for h in granted.split(",") if h.strip()}


@pytest.mark.parametrize(
    "header",
    ["content-type", "authorization", "x-tenant-id", "x-client-surface"],
)
def test_preflight_allows_header_sent_by_browser_clients(flask_app, header):
    assert header in _allowed_headers(flask_app, f"content-type,{header}")


def test_login_preflight_allows_the_exact_header_set_panel_sends(flask_app):
    """The panel login request: Content-Type + X-Client-Surface, no token yet."""
    requested = "content-type,x-client-surface"
    assert _allowed_headers(flask_app, requested) >= {"content-type", "x-client-surface"}
