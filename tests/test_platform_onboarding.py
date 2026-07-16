"""Handler-level tests for the platform onboarding + login-link routes and the
public login-link redeem route.

Pure-Python: decorators are unwrapped and Flask globals / services are
monkeypatched (following tests/test_subjects_mine.py), so no JWT/DB is stood up.
The seed engine itself is tested in tests/test_apply_subjects.py and the
seed_service tests; here we assert the platform wiring — target-tenant
resolution, audit, 404/503 handling, and the redeem session hand-off.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _raw(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _fake_request(json_body=None, files=None):
    return types.SimpleNamespace(
        get_json=lambda *a, **k: json_body if json_body is not None else {},
        files=files or {},
    )


# ---------------------------------------------------------------------------
# POST /api/auth/login-link/redeem  (public, single-use session hand-off)
# ---------------------------------------------------------------------------

def test_redeem_rejects_invalid_code(monkeypatch):
    from modules.auth import routes, handoff

    monkeypatch.setattr(handoff, "redeem", lambda code: None)
    monkeypatch.setattr(routes, "request", _fake_request({"code": "bad"}))

    captured = {}
    monkeypatch.setattr(
        routes,
        "error_response",
        lambda error, message, status_code: captured.update(error=error, status=status_code)
        or ("err", status_code),
    )

    resp = _raw(routes.login_link_redeem)()
    assert captured["status"] == 401
    assert captured["error"] == "InvalidLoginLink"


def test_redeem_valid_code_finalizes_god_login(monkeypatch):
    from modules.auth import routes, handoff
    import core.decorators.auth as auth_dec
    import core.models as core_models

    monkeypatch.setattr(
        handoff, "redeem", lambda code: {"admin_id": "pa-1", "tenant_id": "t-9"}
    )
    monkeypatch.setattr(routes, "request", _fake_request({"code": "good"}))

    fake_user = types.SimpleNamespace(id="pa-1", is_platform_admin=True)
    fake_tenant = types.SimpleNamespace(id="t-9", subdomain="acme")

    # _load_without_tenant_scope(loader) just runs the loader in these tests.
    monkeypatch.setattr(auth_dec, "_load_without_tenant_scope", lambda loader: fake_user)

    class _Q:
        def filter_by(self, **kw):
            return self

        def filter(self, *a):
            return self

        def first(self):
            return fake_tenant

    monkeypatch.setattr(
        core_models, "Tenant", types.SimpleNamespace(query=_Q(), status=None)
    )
    monkeypatch.setattr(routes, "g", types.SimpleNamespace())

    captured = {}
    monkeypatch.setattr(
        routes,
        "_finalize_login",
        lambda user, tenant, is_god_login: captured.update(
            user=user, tenant=tenant, god=is_god_login
        )
        or ("ok", 200),
    )

    resp = _raw(routes.login_link_redeem)()
    assert resp == ("ok", 200)
    assert captured["user"] is fake_user
    assert captured["tenant"] is fake_tenant
    assert captured["god"] is True
    assert routes.g.tenant_id == "t-9"


# ---------------------------------------------------------------------------
# POST /api/platform/tenants/<id>/login-link
# ---------------------------------------------------------------------------

def test_login_link_returns_url_and_audits(monkeypatch):
    from modules.platform import routes, services
    import modules.auth.handoff as handoff
    import config.settings as settings

    fake_tenant = types.SimpleNamespace(id="t-9", subdomain="acme")
    monkeypatch.setattr(routes, "_resolve_target_tenant", lambda tid: fake_tenant)
    monkeypatch.setattr(handoff, "issue", lambda admin_id, tenant_id: "CODE123")
    monkeypatch.setattr(
        settings, "get_admin_web_login_link_url", lambda code, sub: f"https://{sub}.x/enter?code={code}"
    )
    monkeypatch.setattr(
        routes, "g", types.SimpleNamespace(current_user=types.SimpleNamespace(id="pa-1"))
    )

    audited = {}
    monkeypatch.setattr(
        services,
        "log_platform_action",
        lambda **kw: audited.update(kw),
    )
    captured = {}
    monkeypatch.setattr(
        routes, "success_response", lambda data=None, **k: captured.update(data=data) or ("ok", 200)
    )

    _raw(routes.create_tenant_login_link)("t-9")
    assert captured["data"]["url"] == "https://acme.x/enter?code=CODE123"
    assert audited["action"] == "tenant.login_link_issued"
    assert audited["tenant_id"] == "t-9"


def test_login_link_503_when_issue_unavailable(monkeypatch):
    from modules.platform import routes
    import modules.auth.handoff as handoff

    monkeypatch.setattr(
        routes, "_resolve_target_tenant", lambda tid: types.SimpleNamespace(id="t-9", subdomain="acme")
    )
    monkeypatch.setattr(handoff, "issue", lambda admin_id, tenant_id: None)
    monkeypatch.setattr(routes, "g", types.SimpleNamespace(current_user=types.SimpleNamespace(id="pa-1")))

    captured = {}
    monkeypatch.setattr(
        routes,
        "error_response",
        lambda error, message, status_code: captured.update(status=status_code) or ("err", status_code),
    )
    _raw(routes.create_tenant_login_link)("t-9")
    assert captured["status"] == 503


def test_login_link_404_when_tenant_missing(monkeypatch):
    from modules.platform import routes

    monkeypatch.setattr(routes, "_resolve_target_tenant", lambda tid: None)
    captured = {}
    monkeypatch.setattr(
        routes, "not_found_response", lambda name: captured.update(name=name) or ("nf", 404)
    )
    _raw(routes.create_tenant_login_link)("missing")
    assert captured["name"] == "Tenant"


# ---------------------------------------------------------------------------
# POST /api/platform/tenants/<id>/seed/apply
# ---------------------------------------------------------------------------

def test_seed_apply_targets_path_tenant_and_audits(monkeypatch):
    from modules.platform import routes, services
    import modules.school_setup.seed_service as seed_service

    fake_tenant = types.SimpleNamespace(id="t-target", subdomain="acme")
    monkeypatch.setattr(routes, "_resolve_target_tenant", lambda tid: fake_tenant)
    monkeypatch.setattr(routes, "_parse_uploaded_config", lambda: ({"tenant": {}}, None))
    monkeypatch.setattr(routes, "g", types.SimpleNamespace(current_user=types.SimpleNamespace(id="pa-1")))

    seen = {}
    monkeypatch.setattr(
        seed_service,
        "seed_school",
        lambda tenant_id, config, dry_run, complete: seen.update(tenant_id=tenant_id)
        or {
            "classes": {"created": 4},
            "class_subjects": {"created": 20},
            "setup_complete": True,
        },
    )
    audited = {}
    monkeypatch.setattr(services, "log_platform_action", lambda **kw: audited.update(kw))
    monkeypatch.setattr(routes, "success_response", lambda data=None, **k: ("ok", 201))

    _raw(routes.platform_seed_apply)("t-target")
    assert seen["tenant_id"] == "t-target"
    assert routes.g.tenant_id == "t-target"
    assert audited["action"] == "tenant.seeded"
    assert audited["tenant_id"] == "t-target"


def test_seed_apply_404_when_tenant_missing(monkeypatch):
    from modules.platform import routes

    monkeypatch.setattr(routes, "_resolve_target_tenant", lambda tid: None)
    captured = {}
    monkeypatch.setattr(
        routes, "not_found_response", lambda name: captured.update(name=name) or ("nf", 404)
    )
    _raw(routes.platform_seed_apply)("missing")
    assert captured["name"] == "Tenant"


def test_resolve_target_tenant_active_only(flask_app, db_session):
    """Only ACTIVE tenants are valid onboarding / login-link targets — suspended
    and soft-deleted are excluded, matching every login path."""
    import uuid
    from core.models import (
        Tenant,
        TENANT_STATUS_ACTIVE,
        TENANT_STATUS_SUSPENDED,
        TENANT_STATUS_DELETED,
    )
    from modules.platform import routes

    def _mk(status):
        t = Tenant(
            id=uuid.uuid4().hex,
            name=status,
            subdomain=f"{status}-{uuid.uuid4().hex[:6]}",
            status=status,
        )
        db_session.add(t)
        return t

    active = _mk(TENANT_STATUS_ACTIVE)
    suspended = _mk(TENANT_STATUS_SUSPENDED)
    deleted = _mk(TENANT_STATUS_DELETED)
    db_session.flush()

    assert routes._resolve_target_tenant(active.id) is not None
    assert routes._resolve_target_tenant(suspended.id) is None
    assert routes._resolve_target_tenant(deleted.id) is None


def test_seed_preview_targets_path_tenant(monkeypatch):
    from modules.platform import routes
    import modules.school_setup.seed_service as seed_service

    fake_tenant = types.SimpleNamespace(id="t-p", subdomain="acme")
    monkeypatch.setattr(routes, "_resolve_target_tenant", lambda tid: fake_tenant)
    monkeypatch.setattr(routes, "_parse_uploaded_config", lambda: ({"tenant": {}}, None))
    monkeypatch.setattr(routes, "g", types.SimpleNamespace())

    seen = {}
    monkeypatch.setattr(
        seed_service,
        "preview_seed",
        lambda tenant_id, config, active_subdomain=None: seen.update(
            tenant_id=tenant_id, sub=active_subdomain
        )
        or {"diff": []},
    )
    monkeypatch.setattr(routes, "success_response", lambda data=None, **k: ("ok", 200))

    _raw(routes.platform_seed_preview)("t-p")
    assert seen["tenant_id"] == "t-p"
    assert seen["sub"] == "acme"
    assert routes.g.tenant_id == "t-p"
