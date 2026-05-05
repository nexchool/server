"""Unit tests for the per-tenant feature_flags module — pure-logic only.

DB-backed paths (`get_tenant_feature_flags`, `is_feature_enabled`) are
covered by rebinding `Tenant` on `core.models` to a fake before the function
imports it locally, sidestepping the Flask app-context requirement of the
real Flask-SQLAlchemy `Model.query` descriptor.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from core.feature_flags import (
    CORE_FEATURES,
    OPTIONAL_FEATURES,
    default_feature_flags,
    get_tenant_enabled_features,
    get_tenant_feature_flags,
    is_feature_enabled,
)


def _install_fake_tenant(monkeypatch, stored_flags):
    """Replace core.models.Tenant with a stub that returns a tenant whose
    `feature_flags` is `stored_flags` (or None means "tenant missing")."""
    import core.models as core_models

    fake_tenant = None
    if stored_flags is not _MISSING:
        fake_tenant = MagicMock()
        fake_tenant.feature_flags = stored_flags

    fake_query = MagicMock()
    fake_query.get.return_value = fake_tenant

    fake_model = MagicMock()
    fake_model.query = fake_query

    monkeypatch.setattr(core_models, "Tenant", fake_model)


_MISSING = object()


# --- pure ---

def test_default_feature_flags_includes_all_optional():
    flags = default_feature_flags()
    assert set(flags.keys()) == set(OPTIONAL_FEATURES)
    assert all(v is True for v in flags.values())


def test_default_feature_flags_excludes_core():
    flags = default_feature_flags()
    for core in CORE_FEATURES:
        assert core not in flags


# --- DB-backed (via fake) ---

def test_get_tenant_feature_flags_treats_missing_as_enabled(monkeypatch):
    _install_fake_tenant(monkeypatch, {"attendance": False})
    flags = get_tenant_feature_flags("t1")
    assert flags["attendance"] is False
    for key in OPTIONAL_FEATURES:
        if key == "attendance":
            continue
        assert flags[key] is True
    for key in CORE_FEATURES:
        assert flags[key] is True


def test_get_tenant_feature_flags_handles_missing_tenant(monkeypatch):
    _install_fake_tenant(monkeypatch, _MISSING)
    flags = get_tenant_feature_flags("missing")
    assert all(flags[k] is True for k in OPTIONAL_FEATURES)
    assert all(flags[k] is True for k in CORE_FEATURES)


def test_get_tenant_feature_flags_handles_non_dict_storage(monkeypatch):
    _install_fake_tenant(monkeypatch, None)
    flags = get_tenant_feature_flags("t1")
    assert all(flags[k] is True for k in OPTIONAL_FEATURES)


def test_get_tenant_enabled_features_returns_only_truthy(monkeypatch):
    _install_fake_tenant(monkeypatch, {"attendance": False, "fees_management": True})
    enabled = get_tenant_enabled_features("t1")
    assert "attendance" not in enabled
    assert "fees_management" in enabled
    for key in CORE_FEATURES:
        assert key in enabled


def test_is_feature_enabled_core_always_true_even_when_disabled_in_storage(monkeypatch):
    """Tampering with stored flags can't disable a CORE feature."""
    _install_fake_tenant(monkeypatch, {"students": False, "attendance": False})
    assert is_feature_enabled("t1", "students") is True
    assert is_feature_enabled("t1", "attendance") is False


def test_is_feature_enabled_unknown_key_defaults_true(monkeypatch):
    """Unknown keys are not gated — fail-open avoids breaking new modules
    before their key is registered."""
    _install_fake_tenant(monkeypatch, {})
    assert is_feature_enabled("t1", "totally_made_up") is True


def test_is_feature_enabled_optional_explicit_true(monkeypatch):
    _install_fake_tenant(monkeypatch, {"transport": True})
    assert is_feature_enabled("t1", "transport") is True
