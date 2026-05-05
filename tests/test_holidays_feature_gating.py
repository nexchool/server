"""Holidays cross-feature gating: when `holiday_management` is disabled,
holiday helpers should treat every day as a working day so attendance
and leave logic don't see stale holidays.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import core.feature_flags as ff_mod
import modules.holidays.services as holidays_services


def test_get_holiday_for_date_returns_none_when_feature_off(monkeypatch):
    monkeypatch.setattr(ff_mod, "is_feature_enabled", lambda _t, _k: False)
    # Even if there's a matching row in the DB, the function must not query it.
    fake_holiday_query = MagicMock()
    fake_holiday_query.filter.return_value.filter.return_value.filter.return_value.filter.return_value.first.return_value = MagicMock()
    fake_model = MagicMock()
    fake_model.query = fake_holiday_query
    monkeypatch.setattr(holidays_services, "Holiday", fake_model)

    assert holidays_services.get_holiday_for_date(date(2026, 4, 28), "tenant-1") is None
    # Holiday.query should not have been touched.
    fake_holiday_query.filter.assert_not_called()


def test_get_holiday_for_date_does_not_short_circuit_when_feature_on(monkeypatch):
    """When holidays is enabled, the function must reach DB query code (we
    only check it does NOT return early; full SQLAlchemy-mocked path is
    out of scope for unit tests)."""
    monkeypatch.setattr(ff_mod, "is_feature_enabled", lambda _t, _k: True)

    fake_q = MagicMock()
    fake_model = MagicMock()
    fake_model.query = fake_q
    monkeypatch.setattr(holidays_services, "Holiday", fake_model)

    holidays_services.get_holiday_for_date(date(2026, 4, 28), "tenant-1")
    # The query was attempted (filter chain entered).
    assert fake_q.filter.called


def test_calendar_range_summary_returns_all_working_when_feature_off(monkeypatch):
    monkeypatch.setattr(ff_mod, "is_feature_enabled", lambda _t, _k: False)

    result = holidays_services.calendar_range_summary("tenant-1", "2026-04-01", "2026-04-07")
    assert result["success"] is True
    data = result["data"]
    assert data["total_days"] == 7
    assert data["working_days"] == 7
    assert data["occurrences"] == []


def test_get_working_days_info_skips_db_when_feature_off(monkeypatch):
    monkeypatch.setattr(ff_mod, "is_feature_enabled", lambda _t, _k: False)
    fake_q = MagicMock()
    fake_q.filter.side_effect = AssertionError("DB queried while holidays disabled")
    fake_model = MagicMock()
    fake_model.query = fake_q
    monkeypatch.setattr(holidays_services, "Holiday", fake_model)

    total, working, occ = holidays_services.get_working_days_info_for_range(
        date(2026, 4, 1), date(2026, 4, 5), "tenant-1"
    )
    assert total == working == 5
    assert occ == []
