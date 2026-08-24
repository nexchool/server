"""A year is what a school reports under; a cycle is when it actually runs.

`academic_years` carries one pair of dates for the whole tenant, so a trust
running GSEB June-to-April and CBSE April-to-March had to pick one and be wrong
about the other.

Two properties are pinned here above all others:

* **A cycle names no applicability.** There is no programme, grade, stream or
  campus on it. Which classes run in a cycle is answered by the classes, so the
  two can never disagree about the same fact.
* **There is no global "current cycle".** Several run at once; context answers
  the question instead.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import AcademicTerm
from modules.academics.calendar.models import AcademicCalendar
from modules.academics.cycles.models import (
    CYCLE_KIND_MAIN,
    CYCLE_KIND_SHORT_COURSE,
    AcademicCycle,
)
from modules.academics.cycles.services import (
    cycles_for_year,
    default_cycle_for_year,
    ensure_default_cycle,
    resolve_cycle_id,
    year_has_multiple_cycles,
)
from modules.classes.models import Class


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


def _cycle(db_session, tenant, year, name, start, end, kind=CYCLE_KIND_SHORT_COURSE):
    row = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"{name}-{uuid.uuid4().hex[:5]}",
        start_date=start, end_date=end, cycle_kind=kind,
    )
    db_session.add(row)
    db_session.flush()
    return row


# ---------------------------------------------------------------------------
# The default cycle — what makes a simple school unchanged
# ---------------------------------------------------------------------------

def test_a_new_year_comes_with_its_cycle(ctx, db_session, tenant, year):
    """An administrator makes a year; the period it runs in arrives with it."""
    main = default_cycle_for_year(year.id, tenant.id)
    assert main is not None
    assert main.name == year.name
    assert main.start_date == year.start_date
    assert main.end_date == year.end_date
    assert main.cycle_kind == CYCLE_KIND_MAIN


def test_ensuring_the_default_cycle_is_idempotent(ctx, db_session, tenant, year):
    first = ensure_default_cycle(year)
    second = ensure_default_cycle(year)
    assert first.id == second.id
    assert len(cycles_for_year(year.id, tenant.id)) == 1


def test_a_class_takes_the_default_cycle_without_being_told(
    ctx, db_session, tenant, year
):
    """The simple-school rule: the field exists and nobody has to see it."""
    cls = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section="A",
        academic_year_id=year.id,
    )
    db_session.add(cls)
    db_session.flush()

    assert cls.academic_cycle_id == default_cycle_for_year(year.id, tenant.id).id


def test_one_cycle_means_no_choice_is_offered(ctx, db_session, tenant, year):
    assert year_has_multiple_cycles(year.id, tenant.id) is False

    _cycle(db_session, tenant, year, "Vacation", date(2026, 5, 1), date(2026, 6, 10))
    assert year_has_multiple_cycles(year.id, tenant.id) is True


# ---------------------------------------------------------------------------
# Several cycles in one year
# ---------------------------------------------------------------------------

def test_one_year_holds_cycles_with_different_dates(ctx, db_session, tenant, year):
    """The case a single pair of dates on the year could not express."""
    gseb = _cycle(
        db_session, tenant, year, "GSEB Main",
        date(2026, 6, 1), date(2027, 4, 30), CYCLE_KIND_MAIN,
    )
    vacation = _cycle(
        db_session, tenant, year, "Grade 11 Vacation",
        date(2026, 5, 1), date(2026, 6, 10),
    )
    jee = _cycle(
        db_session, tenant, year, "JEE Programme",
        date(2026, 4, 1), date(2027, 3, 31),
    )

    found = cycles_for_year(year.id, tenant.id)
    assert {gseb.id, vacation.id, jee.id} <= {c.id for c in found}
    # Overlapping on purpose: a coaching programme runs alongside the year.
    assert vacation.start_date < jee.end_date


def test_classes_can_sit_in_different_cycles(ctx, db_session, tenant, year):
    vacation = _cycle(
        db_session, tenant, year, "Vacation", date(2026, 5, 1), date(2026, 6, 10)
    )
    main = default_cycle_for_year(year.id, tenant.id)

    regular = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section="A",
        academic_year_id=year.id, academic_cycle_id=main.id,
    )
    batch = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section="VAC",
        academic_year_id=year.id, academic_cycle_id=vacation.id,
    )
    db_session.add_all([regular, batch])
    db_session.flush()

    assert regular.academic_cycle_id != batch.academic_cycle_id


def test_terms_and_calendars_can_sit_in_different_cycles(
    ctx, db_session, tenant, year
):
    main = default_cycle_for_year(year.id, tenant.id)
    other = _cycle(
        db_session, tenant, year, "CBSE Main",
        date(2026, 4, 1), date(2027, 3, 31), CYCLE_KIND_MAIN,
    )

    db_session.add_all([
        AcademicTerm(
            id=_new_id("t-"), tenant_id=tenant.id, academic_year_id=year.id,
            academic_cycle_id=main.id, name="Term 1", sequence=1,
            start_date=date(2026, 6, 1), end_date=date(2026, 10, 31),
        ),
        AcademicTerm(
            id=_new_id("t-"), tenant_id=tenant.id, academic_year_id=year.id,
            academic_cycle_id=other.id, name="Semester 1", sequence=1,
            start_date=date(2026, 4, 1), end_date=date(2026, 9, 30),
        ),
        AcademicCalendar(
            id=_new_id("cal-"), tenant_id=tenant.id, academic_year_id=year.id,
            academic_cycle_id=main.id, status="draft",
        ),
        AcademicCalendar(
            id=_new_id("cal-"), tenant_id=tenant.id, academic_year_id=year.id,
            academic_cycle_id=other.id, status="draft",
        ),
    ])
    db_session.flush()

    cals = AcademicCalendar.query.filter_by(
        tenant_id=tenant.id, academic_year_id=year.id
    ).all()
    assert len({c.academic_cycle_id for c in cals}) == 2


# ---------------------------------------------------------------------------
# The cycle a row names must belong to the year it names
# ---------------------------------------------------------------------------

def test_a_class_cannot_name_a_cycle_from_another_year(ctx, db_session, tenant):
    first = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"Y1-{uuid.uuid4().hex[:5]}",
        start_date=date(2025, 4, 1), end_date=date(2026, 3, 31),
    )
    second = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"Y2-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
    )
    db_session.add_all([first, second])
    db_session.flush()

    other_cycle = default_cycle_for_year(second.id, tenant.id)

    db_session.begin_nested()
    db_session.add(
        Class(
            id=_new_id("cl-"), tenant_id=tenant.id, section="A",
            academic_year_id=first.id, academic_cycle_id=other_cycle.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_resolving_a_cycle_refuses_one_from_another_year(ctx, db_session, tenant):
    first = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"Y1-{uuid.uuid4().hex[:5]}",
        start_date=date(2025, 4, 1), end_date=date(2026, 3, 31),
    )
    second = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"Y2-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
    )
    db_session.add_all([first, second])
    db_session.flush()

    foreign = default_cycle_for_year(second.id, tenant.id)
    with pytest.raises(ValueError):
        resolve_cycle_id(first.id, tenant.id, foreign.id)

    # Naming none resolves to the year's own main cycle.
    assert resolve_cycle_id(first.id, tenant.id) == (
        default_cycle_for_year(first.id, tenant.id).id
    )


# ---------------------------------------------------------------------------
# The shape the model refuses
# ---------------------------------------------------------------------------

def test_a_cycle_carries_no_applicability():
    """Locked: applicability is derived through Classes, never declared here.

    A cycle that could say "CBSE, grades 9-12" while a class in it says
    "GSEB, grade 8" would be a second source of truth for the same fact.
    """
    columns = set(AcademicCycle.__table__.columns.keys())
    for forbidden in (
        "programme_id", "grade_id", "grade_from", "grade_to",
        "stream_id", "campus_id", "school_unit_id", "medium_id",
    ):
        assert forbidden not in columns, (
            f"AcademicCycle.{forbidden} makes the cycle a second owner of "
            "applicability. Which classes run in a cycle is answered by the "
            "classes."
        )


def test_nothing_stores_a_globally_current_cycle():
    """Several cycles run at once, so one global answer would be wrong."""
    from modules.academics.backbone.models import AcademicSettings

    columns = set(AcademicSettings.__table__.columns.keys())
    assert "current_academic_cycle_id" not in columns
    # The reporting year keeps its meaning; that question does have one answer.
    assert "current_academic_year_id" in columns


def test_dates_must_be_ordered(ctx, db_session, tenant, year):
    db_session.begin_nested()
    db_session.add(
        AcademicCycle(
            id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
            name="Backwards", start_date=date(2027, 1, 1), end_date=date(2026, 1, 1),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_two_cycles_in_one_year_cannot_share_a_name(ctx, db_session, tenant, year):
    name = f"Duplicate-{uuid.uuid4().hex[:6]}"
    db_session.add(
        AcademicCycle(
            id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
            name=name, start_date=date(2026, 5, 1), end_date=date(2026, 6, 1),
        )
    )
    db_session.flush()

    db_session.begin_nested()
    db_session.add(
        AcademicCycle(
            id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
            name=name, start_date=date(2026, 7, 1), end_date=date(2026, 8, 1),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------

def test_a_cycle_cannot_reach_another_schools_year(ctx, db_session, tenant, year):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    other = Tenant(
        id=_new_id("t-"), name="Other School",
        subdomain=f"test-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    # Their year is invisible to our resolver.
    assert default_cycle_for_year(year.id, other.id) is None
    assert cycles_for_year(year.id, other.id) == []
