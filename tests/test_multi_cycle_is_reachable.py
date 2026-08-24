"""Two cycles under one year, and nothing silently guessing between them.

Migration 112 made cycles storable; this pins the two things that make them
*usable*:

* **A term is named within its cycle** (migration 113). CBSE's "Term 1" and
  GSEB's "Term 1" are different terms, and the year-wide index refused the
  second one.
* **Nothing picks a cycle for you once there are several.** Falling back to
  the main cycle would put a new CBSE section on GSEB's calendar, and nothing
  downstream would look wrong.

A school with one cycle must behave exactly as it did, and that is tested
first — the whole design is worthless if it makes the ordinary case harder.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy.exc import IntegrityError

from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import AcademicTerm
from modules.academics.calendar.models import AcademicCalendar
from modules.academics.cycles.models import (
    CYCLE_KIND_MAIN,
    CYCLE_KIND_SHORT_COURSE,
    AcademicCycle,
)
from modules.academics.cycles.services import (
    archive_cycle,
    create_cycle,
    cycles_for_year,
    default_cycle_for_year,
    resolve_cycle_id,
    update_cycle,
)
from modules.classes.models import Class
from modules.classes.services import create_class


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


@pytest.fixture
def trust(db_session, tenant, year):
    """The realistic shape: two boards on different calendars, plus a batch."""
    main = default_cycle_for_year(year.id, tenant.id)
    main.name = f"GSEB-{uuid.uuid4().hex[:5]}"
    main.start_date, main.end_date = date(2026, 6, 1), date(2027, 4, 30)

    cbse = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"CBSE-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
        cycle_kind=CYCLE_KIND_MAIN,
    )
    vacation = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"Grade 11 Vacation-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 5, 1), end_date=date(2026, 6, 10),
        cycle_kind=CYCLE_KIND_SHORT_COURSE,
    )
    db_session.add_all([cbse, vacation])
    db_session.flush()
    return {"gseb": main, "cbse": cbse, "vacation": vacation}


def _term(tenant, year, cycle, name, start, end):
    return AcademicTerm(
        id=_new_id("t-"), tenant_id=tenant.id, academic_year_id=year.id,
        academic_cycle_id=cycle.id, name=name, sequence=1,
        start_date=start, end_date=end,
    )


# ---------------------------------------------------------------------------
# Finding 1 — a term is named within its cycle
# ---------------------------------------------------------------------------

def test_each_cycle_may_have_its_own_term_1(ctx, db_session, tenant, year, trust):
    """The case the year-wide index refused."""
    db_session.add_all([
        _term(tenant, year, trust["gseb"], "Term 1", date(2026, 6, 1), date(2026, 10, 31)),
        _term(tenant, year, trust["gseb"], "Term 2", date(2026, 11, 1), date(2027, 4, 30)),
        _term(tenant, year, trust["cbse"], "Term 1", date(2026, 4, 1), date(2026, 9, 30)),
        _term(tenant, year, trust["cbse"], "Term 2", date(2026, 10, 1), date(2027, 3, 31)),
    ])
    db_session.flush()

    rows = AcademicTerm.query.filter_by(
        tenant_id=tenant.id, academic_year_id=year.id
    ).all()
    assert len([r for r in rows if r.name == "Term 1"]) == 2
    assert len({r.academic_cycle_id for r in rows}) == 2


def test_one_cycle_still_cannot_hold_two_terms_of_a_name(
    ctx, db_session, tenant, year, trust
):
    """Loosened across cycles, unchanged within one — a picker with two
    identical entries is still a defect."""
    db_session.add(
        _term(tenant, year, trust["gseb"], "Term 1", date(2026, 6, 1), date(2026, 10, 31))
    )
    db_session.flush()

    db_session.begin_nested()
    db_session.add(
        _term(tenant, year, trust["gseb"], "Term 1", date(2026, 11, 1), date(2027, 1, 31))
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_terms_in_different_cycles_may_overlap_in_date(
    ctx, db_session, tenant, year, trust
):
    """GSEB's Term 1 (Jun-Oct) and CBSE's (Apr-Sep) share months by design.

    The overlap check had to become cycle-scoped for the same reason the index
    did: two cycles under one year overlap on purpose.
    """
    from modules.academics.term_routes import _validate_term_dates

    db_session.add(
        _term(tenant, year, trust["gseb"], "Term 1", date(2026, 6, 1), date(2026, 10, 31))
    )
    db_session.flush()

    # Same dates, other cycle → allowed.
    assert _validate_term_dates(
        tenant.id, year.id, date(2026, 6, 1), date(2026, 9, 30),
        academic_cycle_id=trust["cbse"].id,
    ) is None

    # Same dates, same cycle → refused.
    clash = _validate_term_dates(
        tenant.id, year.id, date(2026, 7, 1), date(2026, 9, 30),
        academic_cycle_id=trust["gseb"].id,
    )
    assert clash and "overlap" in clash.lower()


def test_a_terms_dates_are_checked_against_its_own_cycle(
    ctx, db_session, tenant, year, trust
):
    """A vacation term sits outside the main year and inside its own batch."""
    from modules.academics.term_routes import _validate_term_dates

    assert _validate_term_dates(
        tenant.id, year.id, date(2026, 5, 5), date(2026, 6, 5),
        academic_cycle_id=trust["vacation"].id,
    ) is None

    outside = _validate_term_dates(
        tenant.id, year.id, date(2026, 8, 1), date(2026, 9, 1),
        academic_cycle_id=trust["vacation"].id,
    )
    assert outside and "must fall within" in outside


# ---------------------------------------------------------------------------
# Finding 2 — nothing guesses between cycles
# ---------------------------------------------------------------------------

def test_a_simple_school_never_names_a_cycle(ctx, db_session, tenant, year):
    """One year, one cycle, class created with no cycle at all."""
    result = create_class(
        name="Grade 4", section="A", academic_year_id=year.id
    )
    assert result["success"] is True, result

    created = Class.query.filter_by(id=result["class"]["id"]).first()
    assert created.academic_cycle_id == default_cycle_for_year(year.id, tenant.id).id


def test_with_several_cycles_a_class_must_say_which(
    ctx, db_session, tenant, year, trust
):
    """The rule that stops a CBSE section landing on GSEB's calendar."""
    result = create_class(
        name="Grade 10", section="A", academic_year_id=year.id
    )
    assert result["success"] is False
    assert "several cycles" in result["error"]


def test_naming_the_cycle_places_the_class_in_it(ctx, db_session, tenant, year, trust):
    result = create_class(
        name="Grade 10", section="A", academic_year_id=year.id,
        academic_cycle_id=trust["cbse"].id,
    )
    assert result["success"] is True, result

    created = Class.query.filter_by(id=result["class"]["id"]).first()
    assert created.academic_cycle_id == trust["cbse"].id


def test_direct_construction_also_refuses_to_guess(ctx, db_session, tenant, year, trust):
    """The listener fills the cycle for fixtures and seeds. Once a year has
    several it must refuse too, or a seed quietly picks the wrong one."""
    db_session.begin_nested()
    db_session.add(
        Class(
            id=_new_id("cl-"), tenant_id=tenant.id, section="Z",
            academic_year_id=year.id,
        )
    )
    with pytest.raises(ValueError, match="cycles"):
        db_session.flush()
    db_session.rollback()


# ---------------------------------------------------------------------------
# The realistic trust
# ---------------------------------------------------------------------------

def test_a_trust_runs_three_cycles_under_one_reporting_year(
    ctx, db_session, tenant, year, trust
):
    gseb_class = create_class(
        name="Grade 10", section="A", academic_year_id=year.id,
        academic_cycle_id=trust["gseb"].id,
    )
    cbse_class = create_class(
        name="Grade 10", section="B", academic_year_id=year.id,
        academic_cycle_id=trust["cbse"].id,
    )
    batch = create_class(
        name="Grade 11 Vacation", section="V", academic_year_id=year.id,
        academic_cycle_id=trust["vacation"].id,
    )
    assert all(r["success"] for r in (gseb_class, cbse_class, batch))

    rows = {
        r["class"]["id"]: Class.query.filter_by(id=r["class"]["id"]).first()
        for r in (gseb_class, cbse_class, batch)
    }
    cycles = {c.academic_cycle_id for c in rows.values()}
    assert len(cycles) == 3

    # One reporting year for all of them — that is the whole point.
    assert {c.academic_year_id for c in rows.values()} == {year.id}


def test_calendars_resolve_per_cycle(ctx, db_session, tenant, year, trust):
    from modules.academics.calendar import services as calendar_services

    for cycle in (trust["gseb"], trust["cbse"]):
        db_session.add(
            AcademicCalendar(
                id=_new_id("cal-"), tenant_id=tenant.id, academic_year_id=year.id,
                academic_cycle_id=cycle.id, status="draft",
            )
        )
    db_session.flush()

    gseb_cal = calendar_services.get_calendar_for_cycle(trust["gseb"].id)
    cbse_cal = calendar_services.get_calendar_for_cycle(trust["cbse"].id)
    assert gseb_cal.id != cbse_cal.id


def test_creating_a_calendar_refuses_to_guess_between_cycles(
    ctx, db_session, tenant, year, trust
):
    from modules.academics.calendar import services as calendar_services

    with pytest.raises(calendar_services.CalendarValidationError):
        calendar_services.get_or_create_calendar(year.id)


# ---------------------------------------------------------------------------
# Cycle CRUD
# ---------------------------------------------------------------------------

def test_a_school_can_open_correct_and_retire_a_cycle(ctx, db_session, tenant, year):
    made = create_cycle(
        tenant.id, year.id, "JEE Programme",
        date(2026, 4, 1), date(2027, 3, 31), CYCLE_KIND_SHORT_COURSE,
    )
    assert made["success"] is True
    cycle = made["academic_cycle"]

    changed = update_cycle(
        cycle.id, tenant.id, {"name": "JEE 2026", "end_date": date(2027, 2, 28)}
    )
    assert changed["success"] is True
    assert changed["academic_cycle"].name == "JEE 2026"

    retired = archive_cycle(cycle.id, tenant.id)
    assert retired["success"] is True
    assert cycle.id not in {c.id for c in cycles_for_year(year.id, tenant.id)}


def test_a_cycle_in_use_cannot_be_retired(ctx, db_session, tenant, year, trust):
    create_class(
        name="Grade 10", section="A", academic_year_id=year.id,
        academic_cycle_id=trust["cbse"].id,
    )
    result = archive_cycle(trust["cbse"].id, tenant.id)
    assert result["success"] is False
    assert "class" in result["error"]


def test_two_cycles_in_a_year_cannot_share_a_name(ctx, db_session, tenant, year):
    first = create_cycle(
        tenant.id, year.id, "Vacation", date(2026, 5, 1), date(2026, 6, 1),
        CYCLE_KIND_SHORT_COURSE,
    )
    assert first["success"] is True

    second = create_cycle(
        tenant.id, year.id, "Vacation", date(2026, 7, 1), date(2026, 8, 1),
        CYCLE_KIND_SHORT_COURSE,
    )
    assert second["success"] is False
    assert "already has a cycle" in second["error"]


def test_backwards_dates_are_refused(ctx, db_session, tenant, year):
    result = create_cycle(
        tenant.id, year.id, "Backwards", date(2027, 1, 1), date(2026, 1, 1),
        CYCLE_KIND_SHORT_COURSE,
    )
    assert result["success"] is False


def test_a_cycle_cannot_be_opened_on_another_schools_year(ctx, db_session, tenant, year):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    other = Tenant(
        id=_new_id("t-"), name="Other School",
        subdomain=f"test-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    result = create_cycle(
        other.id, year.id, "Theirs", date(2026, 5, 1), date(2026, 6, 1),
        CYCLE_KIND_SHORT_COURSE,
    )
    assert result["success"] is False
    assert "not found" in result["error"]


def test_resolving_still_refuses_a_cycle_from_another_year(
    ctx, db_session, tenant, year, trust
):
    other_year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"2027-28-{uuid.uuid4().hex[:5]}",
        start_date=date(2027, 4, 1), end_date=date(2028, 3, 31),
    )
    db_session.add(other_year)
    db_session.flush()

    with pytest.raises(ValueError, match="different academic year"):
        resolve_cycle_id(other_year.id, tenant.id, trust["cbse"].id)
