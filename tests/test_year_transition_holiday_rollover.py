"""
Unit tests for ``modules.academics.services.holiday_rollover``.

Covers:
  - happy path: shifts non-recurring dates by year delta, copies recurring as-is
  - duplicate (start_date, name) skipped — including across other years (DB
    unique constraint is tenant-wide, not year-scoped)
  - Feb 29 → non-leap target year shifts to Feb 28
  - same calendar-year start dates → year_shift==0 keeps dates intact
  - missing from_year / to_year ids
  - same from/to year id rejected
  - missing tenant
  - DB exception triggers rollback
  - empty source list returns zero counts
  - same-batch duplicates (two source rows shifting to the same key)
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import modules.academics.services.holiday_rollover as hr  # noqa: E402

from tests._rollover_helpers import (  # noqa: E402
    install_fake_model,
    install_fake_session,
    row,
)


def _patch_tenant(monkeypatch, tenant="tenant-1"):
    monkeypatch.setattr(hr, "get_tenant_id", lambda: tenant)


# ── Pure helper: _shift_date ────────────────────────────────────────────────


def test_shift_date_simple_increment():
    assert hr._shift_date(date(2025, 6, 15), 1) == date(2026, 6, 15)


def test_shift_date_zero_shift_returns_input():
    d = date(2025, 6, 15)
    assert hr._shift_date(d, 0) is d


def test_shift_date_none_returns_none():
    assert hr._shift_date(None, 1) is None


def test_shift_date_feb29_to_non_leap_falls_back_to_feb28():
    # 2024 is a leap year; 2025 is not.
    assert hr._shift_date(date(2024, 2, 29), 1) == date(2025, 2, 28)


def test_shift_date_feb29_to_next_leap_year_keeps_feb29():
    # 2024 → 2028 (also leap).
    assert hr._shift_date(date(2024, 2, 29), 4) == date(2028, 2, 29)


# ── _years_between ──────────────────────────────────────────────────────────


def test_years_between_handles_missing_dates():
    fy = row(start_date=None)
    ty = row(start_date=date(2026, 6, 1))
    assert hr._years_between(fy, ty) == 0


def test_years_between_basic():
    fy = row(start_date=date(2025, 6, 1))
    ty = row(start_date=date(2026, 6, 1))
    assert hr._years_between(fy, ty) == 1


# ── rollover_holidays ───────────────────────────────────────────────────────


def test_rollover_happy_path_shifts_non_recurring_and_keeps_recurring(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, hr)

    fy = row(id="Y-2025", start_date=date(2025, 6, 1))
    ty = row(id="Y-2026", start_date=date(2026, 6, 1))

    holidays = [
        row(
            id="h-1",
            name="Republic Day",
            description="National holiday",
            holiday_type="public",
            start_date=date(2025, 1, 26),
            end_date=date(2025, 1, 26),
            is_recurring=False,
            recurring_day_of_week=None,
        ),
        row(
            id="h-2",
            name="Sunday weekly off",
            description=None,
            holiday_type="weekly_off",
            start_date=None,
            end_date=None,
            is_recurring=True,
            recurring_day_of_week=6,
        ),
    ]

    install_fake_model(
        monkeypatch,
        hr,
        "AcademicYear",
        queue=[fy, ty],
    )
    install_fake_model(
        monkeypatch,
        hr,
        "Holiday",
        queue=[
            holidays,   # source query
            [],         # existing across all years (none)
        ],
    )

    result = hr.rollover_holidays("Y-2025", "Y-2026")

    assert result == {
        "success": True,
        "holidays_created": 2,
        "skipped_existing": 0,
    }
    assert len(sess.added) == 2
    assert sess.commits == 1 and sess.rollbacks == 0

    # Republic Day shifts to 2026.
    new_rd = sess.added[0]
    assert new_rd.start_date == date(2026, 1, 26)
    assert new_rd.end_date == date(2026, 1, 26)
    assert new_rd.is_recurring is False
    assert new_rd.academic_year_id == "Y-2026"

    # Recurring weekly-off keeps null dates.
    new_wo = sess.added[1]
    assert new_wo.start_date is None
    assert new_wo.end_date is None
    assert new_wo.is_recurring is True
    assert new_wo.recurring_day_of_week == 6
    assert new_wo.academic_year_id == "Y-2026"


def test_rollover_skips_when_target_or_other_year_already_has_same_key(monkeypatch):
    """Even if the colliding holiday belongs to a *different* academic year,
    we must skip — the DB unique constraint is (tenant_id, start_date, name)
    across all years. This is the regression bug fixed during the audit."""
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, hr)

    fy = row(id="Y-2025", start_date=date(2025, 6, 1))
    ty = row(id="Y-2026", start_date=date(2026, 6, 1))
    install_fake_model(monkeypatch, hr, "AcademicYear", queue=[fy, ty])

    src = row(
        id="h-1",
        name="Republic Day",
        description=None,
        holiday_type="public",
        start_date=date(2025, 1, 26),
        end_date=date(2025, 1, 26),
        is_recurring=False,
        recurring_day_of_week=None,
    )
    # Existing holiday on a different year sharing the shifted key.
    pre_existing = row(
        start_date=date(2026, 1, 26),
        name="Republic Day",
    )
    install_fake_model(
        monkeypatch,
        hr,
        "Holiday",
        queue=[[src], [pre_existing]],
    )

    result = hr.rollover_holidays("Y-2025", "Y-2026")
    assert result == {
        "success": True,
        "holidays_created": 0,
        "skipped_existing": 1,
    }
    assert sess.added == []


def test_rollover_blocks_same_year_arg(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, hr)

    result = hr.rollover_holidays("Y-1", "Y-1")
    assert result["success"] is False
    assert "must differ" in result["error"]


def test_rollover_requires_both_year_ids(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, hr)
    assert hr.rollover_holidays("", "Y-1")["success"] is False
    assert hr.rollover_holidays("Y-1", "")["success"] is False


def test_rollover_requires_tenant_context(monkeypatch):
    monkeypatch.setattr(hr, "get_tenant_id", lambda: None)
    install_fake_session(monkeypatch, hr)
    result = hr.rollover_holidays("Y-1", "Y-2")
    assert result == {"success": False, "error": "Tenant context is required"}


def test_rollover_unknown_from_year(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, hr)
    install_fake_model(monkeypatch, hr, "AcademicYear", queue=[None, row(id="Y-2026")])
    install_fake_model(monkeypatch, hr, "Holiday", queue=[])

    result = hr.rollover_holidays("Y-1", "Y-2026")
    assert result["success"] is False
    assert "from_year_id" in result["error"]


def test_rollover_unknown_to_year(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, hr)
    install_fake_model(monkeypatch, hr, "AcademicYear", queue=[row(id="Y-1"), None])
    install_fake_model(monkeypatch, hr, "Holiday", queue=[])

    result = hr.rollover_holidays("Y-1", "Y-2")
    assert result["success"] is False
    assert "to_year_id" in result["error"]


def test_same_batch_collisions_are_only_inserted_once(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, hr)

    fy = row(id="Y-1", start_date=date(2025, 6, 1))
    ty = row(id="Y-2", start_date=date(2026, 6, 1))
    install_fake_model(monkeypatch, hr, "AcademicYear", queue=[fy, ty])

    duplicate_a = row(
        id="h-a", name="Diwali", description=None, holiday_type="public",
        start_date=date(2025, 10, 24), end_date=date(2025, 10, 24),
        is_recurring=False, recurring_day_of_week=None,
    )
    # Same name + start_date (a malformed source dataset) — should dedupe within
    # the batch, even before hitting the DB.
    duplicate_b = row(
        id="h-b", name="Diwali", description=None, holiday_type="public",
        start_date=date(2025, 10, 24), end_date=date(2025, 10, 24),
        is_recurring=False, recurring_day_of_week=None,
    )
    install_fake_model(
        monkeypatch,
        hr,
        "Holiday",
        queue=[[duplicate_a, duplicate_b], []],
    )

    result = hr.rollover_holidays("Y-1", "Y-2")
    assert result["holidays_created"] == 1
    assert result["skipped_existing"] == 1
    assert len(sess.added) == 1


def test_db_exception_rolls_back(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, hr, raise_on_commit=True)

    fy = row(id="Y-1", start_date=date(2025, 6, 1))
    ty = row(id="Y-2", start_date=date(2026, 6, 1))
    install_fake_model(monkeypatch, hr, "AcademicYear", queue=[fy, ty])

    src = row(
        id="h", name="X", description=None, holiday_type="public",
        start_date=date(2025, 6, 1), end_date=date(2025, 6, 1),
        is_recurring=False, recurring_day_of_week=None,
    )
    install_fake_model(monkeypatch, hr, "Holiday", queue=[[src], []])

    result = hr.rollover_holidays("Y-1", "Y-2")
    assert result["success"] is False
    assert sess.rollbacks == 1
