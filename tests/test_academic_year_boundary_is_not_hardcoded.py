"""April to March was a Python constant, and not every school runs on it.

`get_current_academic_year()` decides which label a teacher's leave balance is
filed under. It assumed April-to-March with no way to configure it, so a
June-to-April school filed April's balances under a year that had not started.

The **boundary** now comes from the tenant's own academic year. The **format**
does not change: `leave_balances.academic_year` is a string inside a unique key,
so returning `AcademicYear.name` instead would orphan every balance a school
already holds.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from modules.academics.academic_year.models import AcademicYear
from modules.teachers import constraint_services


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _year(db_session, tenant, start, end):
    row = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=start, end_date=end,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_a_june_to_april_school_gets_its_own_boundary(
    ctx, db_session, tenant, monkeypatch
):
    """April 2026 is the tail of 2025-26 here, not the start of 2026-27.

    The old rule said 2026-27 because the month was >= 4. That is the defect.
    """
    _year(db_session, tenant, date(2025, 6, 1), date(2026, 4, 30))
    monkeypatch.setattr(constraint_services, "school_today", lambda: date(2026, 4, 15))

    assert constraint_services.get_current_academic_year() == "2025-26"


def test_an_april_to_march_school_is_unchanged(ctx, db_session, tenant, monkeypatch):
    """The common case must produce exactly the label it always did, or every
    balance a school already holds is orphaned."""
    _year(db_session, tenant, date(2026, 4, 1), date(2027, 3, 31))
    monkeypatch.setattr(constraint_services, "school_today", lambda: date(2026, 7, 1))

    assert constraint_services.get_current_academic_year() == "2026-27"


def test_the_format_never_becomes_the_year_name(ctx, db_session, tenant, monkeypatch):
    """Named "2026-2027", filed as "2026-27" — the label is derived, not copied."""
    year = _year(db_session, tenant, date(2026, 6, 1), date(2027, 4, 30))
    year.name = "2026-2027 Session"
    db_session.flush()
    monkeypatch.setattr(constraint_services, "school_today", lambda: date(2026, 9, 1))

    assert constraint_services.get_current_academic_year() == "2026-27"


def test_with_no_configured_year_the_old_rule_still_answers(
    ctx, db_session, tenant, monkeypatch
):
    """A tenant with nothing configured gets what it has always got."""
    monkeypatch.setattr(constraint_services, "school_today", lambda: date(2026, 2, 10))
    assert constraint_services.get_current_academic_year() == "2025-26"

    monkeypatch.setattr(constraint_services, "school_today", lambda: date(2026, 5, 10))
    assert constraint_services.get_current_academic_year() == "2026-27"


def test_another_schools_year_does_not_decide_ours(
    ctx, db_session, tenant, monkeypatch
):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    other = Tenant(
        id=_new_id("t-"), name="Other School",
        subdomain=f"test-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()
    # Their year runs June-April; ours is not configured at all.
    _year(db_session, other, date(2025, 6, 1), date(2026, 4, 30))

    monkeypatch.setattr(constraint_services, "school_today", lambda: date(2026, 4, 15))
    # Falls back to April-March for us, rather than borrowing their boundary.
    assert constraint_services.get_current_academic_year() == "2026-27"
