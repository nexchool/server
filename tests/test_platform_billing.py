"""Unit tests for platform billing math and tenant pricing helpers.

`Tenant`/`Student`/`db.session` are replaced via `monkeypatch` to avoid
Flask-SQLAlchemy's app-context requirement; only the math is exercised.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from modules.platform.services import (
    _to_date,
    _to_decimal,
    list_feature_catalog,
)
import modules.platform.services as platform_services


# --- _to_decimal ---

def test_to_decimal_none_returns_none():
    assert _to_decimal(None) is None
    assert _to_decimal("") is None


def test_to_decimal_parses_string_and_number():
    assert _to_decimal("12.5") == Decimal("12.5")
    assert _to_decimal(12.5) == Decimal("12.5")
    assert _to_decimal(0) == Decimal("0")


def test_to_decimal_invalid_raises():
    with pytest.raises(ValueError):
        _to_decimal("not-a-number")


# --- _to_date ---

def test_to_date_iso_string():
    assert _to_date("2026-04-28") == date(2026, 4, 28)


def test_to_date_passthrough_date_object():
    d = date(2026, 1, 1)
    assert _to_date(d) is d


def test_to_date_empty_returns_none():
    assert _to_date(None) is None
    assert _to_date("") is None


def test_to_date_bad_format_raises():
    with pytest.raises(ValueError):
        _to_date("28-04-2026")


# --- calculate_tenant_billing helpers ---

def _mock_tenant(price=None, discount=None, start=None, end=None):
    t = MagicMock()
    t.id = "tenant-1"
    t.price_per_student_per_year = (
        Decimal(str(price)) if price is not None else None
    )
    t.discount_percentage = (
        Decimal(str(discount)) if discount is not None else None
    )
    t.discount_start_date = start
    t.discount_end_date = end
    return t


def _install_billing_mocks(monkeypatch, tenant, active_count):
    fake_tenant_query = MagicMock()
    fake_tenant_query.get.return_value = tenant
    fake_tenant_model = MagicMock()
    fake_tenant_model.query = fake_tenant_query
    monkeypatch.setattr(platform_services, "Tenant", fake_tenant_model)

    fake_session = MagicMock()
    chain = fake_session.query.return_value.filter.return_value.filter
    chain.return_value.count.return_value = active_count
    monkeypatch.setattr(platform_services.db, "session", fake_session)


def test_billing_no_price_returns_zero(monkeypatch):
    tenant = _mock_tenant(price=None)
    _install_billing_mocks(monkeypatch, tenant, active_count=100)
    result = platform_services.calculate_tenant_billing(
        "tenant-1", on_date=date(2026, 4, 28)
    )
    assert result["success"] is True
    assert result["base_amount"] == 0.0
    assert result["total"] == 0.0


def test_billing_basic_no_discount(monkeypatch):
    tenant = _mock_tenant(price=1000, discount=0)
    _install_billing_mocks(monkeypatch, tenant, active_count=50)
    result = platform_services.calculate_tenant_billing(
        "tenant-1", on_date=date(2026, 4, 28)
    )
    assert result["active_students"] == 50
    assert result["base_amount"] == 50000.0
    assert result["discount_active"] is False
    assert result["total"] == 50000.0


def test_billing_discount_active_within_window(monkeypatch):
    tenant = _mock_tenant(
        price=1000,
        discount=10,
        start=date(2026, 1, 1),
        end=date(2026, 12, 31),
    )
    _install_billing_mocks(monkeypatch, tenant, active_count=100)
    result = platform_services.calculate_tenant_billing(
        "tenant-1", on_date=date(2026, 4, 28)
    )
    assert result["discount_active"] is True
    assert result["discount_amount"] == 10000.0
    assert result["total"] == 90000.0


def test_billing_discount_outside_window_not_applied(monkeypatch):
    tenant = _mock_tenant(
        price=1000,
        discount=10,
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
    )
    _install_billing_mocks(monkeypatch, tenant, active_count=100)
    result = platform_services.calculate_tenant_billing(
        "tenant-1", on_date=date(2026, 4, 28)
    )
    assert result["discount_active"] is False
    assert result["discount_amount"] == 0.0
    assert result["total"] == 100000.0


def test_billing_open_ended_window_with_only_start(monkeypatch):
    """Only start date set → discount applies indefinitely after start."""
    tenant = _mock_tenant(price=500, discount=20, start=date(2026, 1, 1), end=None)
    _install_billing_mocks(monkeypatch, tenant, active_count=10)
    result = platform_services.calculate_tenant_billing(
        "tenant-1", on_date=date(2030, 6, 1)
    )
    assert result["discount_active"] is True


def test_billing_unknown_tenant(monkeypatch):
    fake_tenant_query = MagicMock()
    fake_tenant_query.get.return_value = None
    fake_tenant_model = MagicMock()
    fake_tenant_model.query = fake_tenant_query
    monkeypatch.setattr(platform_services, "Tenant", fake_tenant_model)

    result = platform_services.calculate_tenant_billing(
        "missing", on_date=date(2026, 4, 28)
    )
    assert result["success"] is False
    assert result["error"] == "Tenant not found"


# --- update_tenant_feature_flags ---

def test_update_tenant_feature_flags_drops_core_keys(monkeypatch):
    """Core features cannot be disabled; unknown keys are silently dropped."""
    tenant = MagicMock()
    tenant.feature_flags = {}

    fake_tenant_query = MagicMock()
    fake_tenant_query.get.return_value = tenant
    fake_tenant_model = MagicMock()
    fake_tenant_model.query = fake_tenant_query
    monkeypatch.setattr(platform_services, "Tenant", fake_tenant_model)
    monkeypatch.setattr(platform_services.db, "session", MagicMock())
    monkeypatch.setattr(
        platform_services, "log_platform_action", lambda **_kw: None
    )
    monkeypatch.setattr(
        platform_services,
        "get_tenant_feature_flags",
        lambda _tenant_id: {"students": True, "attendance": False},
    )

    result = platform_services.update_tenant_feature_flags(
        tenant_id="t1",
        platform_admin_id="admin",
        flags={"students": False, "attendance": False, "junk_key": True},
    )
    assert result["success"] is True
    assert "students" not in tenant.feature_flags  # core key dropped
    assert "junk_key" not in tenant.feature_flags  # unknown key dropped
    assert tenant.feature_flags["attendance"] is False


# --- list_feature_catalog ---

def test_list_feature_catalog_groups_core_and_optional():
    catalog = list_feature_catalog()
    keys = {item["key"] for item in catalog}
    assert "students" in keys
    assert "attendance" in keys
    by_key = {item["key"]: item for item in catalog}
    assert by_key["students"]["category"] == "core"
    assert by_key["students"]["toggleable"] is False
    assert by_key["attendance"]["category"] == "optional"
    assert by_key["attendance"]["toggleable"] is True
