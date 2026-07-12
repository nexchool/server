"""Public tenant-branding endpoint: login_variant (opt-in) + tagline passthrough."""


def _get_branding(flask_app, tenant):
    client = flask_app.test_client()
    return client.get(
        "/api/auth/tenant-branding",
        headers={"X-Tenant-ID": tenant.id},
    )


def test_branding_defaults_login_variant_when_unset(flask_app, tenant):
    resp = _get_branding(flask_app, tenant)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["name"] == tenant.name
    # Opt-in: no flag set -> the standard login.
    assert data["login_variant"] == "default"
    assert "tagline" in data
    assert "logo_url" in data


def test_branding_returns_stored_login_variant_and_tagline(flask_app, db_session, tenant):
    tenant.feature_flags = {"login_variant": "greenwood"}
    tenant.tagline = "Learn. Grow. Lead."
    db_session.flush()

    resp = _get_branding(flask_app, tenant)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["login_variant"] == "greenwood"
    assert data["tagline"] == "Learn. Grow. Lead."


def test_branding_empty_flags_defaults_variant(flask_app, db_session, tenant):
    tenant.feature_flags = {}
    db_session.flush()
    resp = _get_branding(flask_app, tenant)
    assert resp.get_json()["data"]["login_variant"] == "default"
