"""A gate-pass time typed at the hostel means the hostel's clock.

`_parse_datetime` takes the departure and expected-return stamps. One with an
offset is an instant and is kept. One without is a wall-clock somebody typed
and used to come back *naive* — stored as UTC by Postgres, five and a half
hours late, and unable to be compared with the aware clock that decides
whether a pass is overdue.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from flask import g

from modules.hostel.routes import _parse_datetime

UTC = timezone.utc


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def test_a_wall_clock_time_is_the_hostel_s_clock(ctx):
    got = _parse_datetime("2026-10-01T18:00:00", "expected_return_datetime")
    assert got.tzinfo is not None
    assert got == datetime(2026, 10, 1, 12, 30, tzinfo=UTC)


def test_an_instant_with_an_offset_is_kept(ctx):
    assert _parse_datetime("2026-10-01T12:30:00Z", "x") == datetime(2026, 10, 1, 12, 30, tzinfo=UTC)
    assert _parse_datetime("2026-10-01T18:00:00+05:30", "x") == datetime(2026, 10, 1, 12, 30, tzinfo=UTC)


def test_nonsense_is_refused(ctx):
    with pytest.raises(ValueError):
        _parse_datetime("half past six", "x")
