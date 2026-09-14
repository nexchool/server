"""The app-deep-link URL builders must produce a link the app can route.

`/--/` is a separator Expo Go needs when it is forwarding a link to one of
several projects behind its own shared `exp://` scheme in development. A
standalone build has no such ambiguity — it owns its scheme outright — so a
link carrying that segment does not match any of the app's registered routes
(app/(auth)/reset-password.tsx, app/(auth)/verify-email.tsx) and the app shows
"Unmatched Route" instead of the screen the email promised.
"""

from __future__ import annotations

import pytest

from config.settings import (
    get_app_verification_error_url,
    get_app_verification_success_url,
    get_reset_password_url,
)


@pytest.fixture
def production_scheme(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("FRONTEND_URL", "nexchool://")


def test_reset_password_link_has_no_dev_only_separator(production_scheme):
    url = get_reset_password_url("TOKEN123", "teacher@example.com")

    assert url == "nexchool://reset-password?token=TOKEN123&email=teacher@example.com"
    assert "/--/" not in url


def test_verification_success_link_has_no_dev_only_separator(production_scheme):
    url = get_app_verification_success_url("ACCESS", "REFRESH", "u-1", "teacher@example.com")

    assert url.startswith("nexchool://verify-email?")
    assert "/--/" not in url


def test_verification_error_link_has_no_dev_only_separator(production_scheme):
    url = get_app_verification_error_url("expired")

    assert url == "nexchool://verify-email?status=error&error=expired"
    assert "/--/" not in url
