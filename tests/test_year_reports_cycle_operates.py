"""Which dates mean what, now that there are two pairs of them.

    AcademicYear.start/end  — the span the organization REPORTS under.
    AcademicCycle.start/end — the span the school is OPEN for.

For an ordinary school these are the same dates and the distinction never
surfaces. It surfaces the moment a trust runs GSEB June-to-April and CBSE
April-to-March under one 2026-27, and it decides two things that were
previously wrong:

* a calendar materialised working days across the **year**, so a 40-day
  vacation batch counted twelve months of them;
* correcting a year's dates left the main cycle pointing at the old ones.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from modules.academics.academic_year.models import AcademicYear
from modules.academics.academic_year import services as year_services
from modules.academics.calendar import services as calendar_services
from modules.academics.calendar.models import AcademicCalendar
from modules.academics.cycles.models import CYCLE_KIND_SHORT_COURSE, AcademicCycle
from modules.academics.cycles.services import default_cycle_for_year


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def year(db_session, tenant):
    row = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"2026-27-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _calendar(db_session, tenant, year, cycle):
    cal = AcademicCalendar(
        id=_new_id("cal-"), tenant_id=tenant.id, academic_year_id=year.id,
        academic_cycle_id=cycle.id, status="draft",
        weekly_holidays_config={"days": [6], "second_saturday": False,
                                "fourth_saturday": False},
    )
    db_session.add(cal)
    db_session.flush()
    return cal


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

def test_a_cycle_may_run_outside_the_year_it_reports_under(ctx, db_session, tenant, year):
    """GSEB runs Jun-Apr and reports under 2026-27, which runs Apr-Mar.

    Deliberately permitted: the year is a reporting container, so a cycle is
    not required to sit inside its dates.
    """
    cycle = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"GSEB-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 4, 30),
    )
    db_session.add(cycle)
    db_session.flush()

    assert cycle.end_date > year.end_date
    assert cycle.academic_year_id == year.id


def test_a_calendar_counts_its_cycles_days_not_its_years(
    ctx, db_session, tenant, year
):
    """The defect this closes: a 40-day batch counted a whole year of days."""
    batch = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"Vacation-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 5, 1), end_date=date(2026, 6, 9),
        cycle_kind=CYCLE_KIND_SHORT_COURSE,
    )
    db_session.add(batch)
    db_session.flush()

    cal = _calendar(db_session, tenant, year, batch)
    summary = calendar_services.compute_summary(cal)

    assert summary["total_days"] == 40, (
        "the batch runs 1 May - 9 June; the calendar must not count the year"
    )


def test_the_main_calendar_is_unchanged_for_a_simple_school(
    ctx, db_session, tenant, year
):
    """One cycle carries the year's own span, so nothing moves."""
    main = default_cycle_for_year(year.id, tenant.id)
    cal = _calendar(db_session, tenant, year, main)

    summary = calendar_services.compute_summary(cal)
    expected = (year.end_date - year.start_date).days + 1
    assert summary["total_days"] == expected


def test_the_span_a_calendar_covers_comes_from_its_cycle(ctx, db_session, tenant, year):
    batch = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"JEE-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 7, 1), end_date=date(2026, 12, 31),
        cycle_kind=CYCLE_KIND_SHORT_COURSE,
    )
    db_session.add(batch)
    db_session.flush()

    cal = _calendar(db_session, tenant, year, batch)
    assert calendar_services.calendar_span(cal) == (
        date(2026, 7, 1), date(2026, 12, 31)
    )


# ---------------------------------------------------------------------------
# Correcting a year must not strand its cycle
# ---------------------------------------------------------------------------

def test_correcting_a_years_dates_moves_its_main_cycle(ctx, db_session, tenant, year):
    main = default_cycle_for_year(year.id, tenant.id)
    assert (main.start_date, main.end_date) == (year.start_date, year.end_date)

    result = year_services.update_academic_year(
        year.id, tenant.id,
        start_date=date(2026, 6, 1), end_date=date(2027, 4, 30),
    )
    assert result["success"] is True, result

    db_session.refresh(main)
    assert (main.start_date, main.end_date) == (date(2026, 6, 1), date(2027, 4, 30))


def test_a_cycle_the_school_has_edited_is_left_alone(ctx, db_session, tenant, year):
    """Once a school says something more specific than the year, that wins."""
    main = default_cycle_for_year(year.id, tenant.id)
    main.start_date, main.end_date = date(2026, 5, 1), date(2027, 2, 28)
    db_session.flush()

    year_services.update_academic_year(
        year.id, tenant.id,
        start_date=date(2026, 4, 15), end_date=date(2027, 3, 15),
    )

    db_session.refresh(main)
    assert (main.start_date, main.end_date) == (date(2026, 5, 1), date(2027, 2, 28))


# ---------------------------------------------------------------------------
# Reporting-year semantics stay where they belong
# ---------------------------------------------------------------------------

def test_years_still_may_not_overlap_each_other(ctx, db_session, tenant, year):
    """A reporting-year rule, unaffected by cycles: two 2026-27s cannot exist."""
    result = year_services.create_academic_year(
        f"Overlapping-{uuid.uuid4().hex[:5]}",
        date(2026, 10, 1), date(2027, 9, 30),
    )
    assert result["success"] is False
    assert "overlap" in result["error"].lower()


def test_cycles_under_one_year_may_overlap_each_other(ctx, db_session, tenant, year):
    """The opposite rule, and deliberately so — a batch runs inside the year."""
    first = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"A-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
        cycle_kind=CYCLE_KIND_SHORT_COURSE,
    )
    second = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"B-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 5, 1), end_date=date(2026, 6, 10),
        cycle_kind=CYCLE_KIND_SHORT_COURSE,
    )
    db_session.add_all([first, second])
    db_session.flush()

    assert first.start_date < second.end_date and second.start_date < first.end_date
