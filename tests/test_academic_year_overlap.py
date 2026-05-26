"""Tests for find_overlapping_year — pure-Python, no Flask test client."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_year(year_id: str, name: str, start: str, end: str) -> MagicMock:
    y = MagicMock()
    y.id = year_id
    y.name = name
    y.start_date = date.fromisoformat(start)
    y.end_date = date.fromisoformat(end)
    return y


class _SACol:
    """Minimal SQLAlchemy column expression stand-in.

    SQLAlchemy column attributes support comparison operators that return
    BinaryExpression objects (not booleans). Python evaluates these comparisons
    eagerly when building the filter() argument list, so the mock column must
    implement them without raising TypeError.
    """

    def __le__(self, other):
        return MagicMock()

    def __ge__(self, other):
        return MagicMock()

    def __eq__(self, other):
        return MagicMock()

    def __ne__(self, other):
        return MagicMock()

    def is_(self, value):
        return MagicMock()


def _make_ay_cls(query_return):
    """Build a fake AcademicYear class whose query.filter chain returns *query_return* from .first()."""
    inner_q = MagicMock()
    inner_q.filter.return_value = inner_q
    inner_q.first.return_value = query_return

    cls = MagicMock()
    cls.query = MagicMock()
    cls.query.filter.return_value = inner_q
    # Use _SACol for all column attributes so comparison operators work
    cls.tenant_id = _SACol()
    cls.start_date = _SACol()
    cls.end_date = _SACol()
    cls.id = _SACol()
    return cls, inner_q


# ---------------------------------------------------------------------------
# Test: find_overlapping_year returns existing year when ranges overlap
# ---------------------------------------------------------------------------

def test_find_overlapping_year_returns_year_on_overlap(monkeypatch):
    """find_overlapping_year returns the conflicting year when ranges share at least one day."""
    from modules.academics.academic_year import services

    existing = _make_year("year-1", "2025-2026", "2025-04-01", "2026-03-31")
    fake_ay_cls, _ = _make_ay_cls(existing)

    monkeypatch.setattr(services, "AcademicYear", fake_ay_cls)

    result = services.find_overlapping_year(
        tenant_id="tenant-1",
        start_date=date(2025, 10, 1),
        end_date=date(2026, 9, 30),
    )

    assert result is existing


# ---------------------------------------------------------------------------
# Test: find_overlapping_year returns None when no overlap
# ---------------------------------------------------------------------------

def test_find_overlapping_year_returns_none_when_no_overlap(monkeypatch):
    """find_overlapping_year returns None when the query finds no conflicting year."""
    from modules.academics.academic_year import services

    fake_ay_cls, _ = _make_ay_cls(None)  # .first() returns None

    monkeypatch.setattr(services, "AcademicYear", fake_ay_cls)

    result = services.find_overlapping_year(
        tenant_id="tenant-1",
        start_date=date(2027, 4, 1),
        end_date=date(2028, 3, 31),
    )

    assert result is None


# ---------------------------------------------------------------------------
# Test: find_overlapping_year excludes given id (update path)
# ---------------------------------------------------------------------------

def test_find_overlapping_year_excludes_given_id(monkeypatch):
    """find_overlapping_year adds an id != exclude_id filter when exclude_id is provided."""
    from modules.academics.academic_year import services

    # The service code:
    #   q = AcademicYear.query.filter(...)     ← first filter call
    #   q = q.filter(AcademicYear.id != ...)   ← second filter call on q
    # So `AcademicYear.query.filter` returns `q`, and `q.filter` is called a second time.

    filter_calls = []

    q = MagicMock()

    def capturing_filter(*args, **kw):
        filter_calls.append(args)
        return q  # chaining: q.filter() returns q again

    q.filter.side_effect = capturing_filter
    q.first.return_value = None

    fake_ay_cls = MagicMock()
    fake_ay_cls.query = MagicMock()
    fake_ay_cls.query.filter.side_effect = capturing_filter
    fake_ay_cls.tenant_id = _SACol()
    fake_ay_cls.start_date = _SACol()
    fake_ay_cls.end_date = _SACol()
    fake_ay_cls.id = _SACol()

    monkeypatch.setattr(services, "AcademicYear", fake_ay_cls)

    services.find_overlapping_year(
        tenant_id="tenant-1",
        start_date=date(2025, 4, 1),
        end_date=date(2026, 3, 31),
        exclude_id="year-self",
    )

    # First call is the main overlap filter (3 conditions); second call is the id exclusion.
    # Both calls go through capturing_filter, so we expect at least 2 total calls.
    assert len(filter_calls) >= 2, (
        f"Expected at least 2 .filter() calls (overlap conditions + id exclusion), "
        f"got {len(filter_calls)}"
    )


# ---------------------------------------------------------------------------
# Test: overlap logic is correct at boundary (one shared day)
# ---------------------------------------------------------------------------

def test_find_overlapping_year_boundary_one_shared_day(monkeypatch):
    """Ranges that share exactly one day (end of A == start of B) are overlapping."""
    from modules.academics.academic_year import services

    # Range A: 2025-01-01 to 2025-12-31
    # Range B: 2025-12-31 to 2026-12-31  — shares exactly 2025-12-31
    existing = _make_year("year-1", "2025", "2025-01-01", "2025-12-31")
    fake_ay_cls, _ = _make_ay_cls(existing)

    monkeypatch.setattr(services, "AcademicYear", fake_ay_cls)

    result = services.find_overlapping_year(
        tenant_id="tenant-1",
        start_date=date(2025, 12, 31),
        end_date=date(2026, 12, 31),
    )

    assert result is existing
