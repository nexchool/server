"""A stream is data a school owns, and it is part of what identifies a section.

Two things were wrong before migration 107, and both are pinned here.

The vocabulary was a Python frozenset *and* a database CHECK naming four
tracks, so a school offering "Integrated Science" needed a deploy. And `stream`
was absent from the class identity constraint, so Grade 11 Science A and Grade
11 Commerce A — both section "A" — collided on insert. The bulk generator
parsed "Sci-A" into (stream, section) and the constraint underneath refused to
store the result, which is why no live row ever carried a stream.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.academics.academic_year.models import AcademicYear
from modules.classes.models import Class
from modules.academic_programmes.models import AcademicProgramme
from modules.grades.models import Grade
from modules.school_units.models import SchoolUnit
from modules.streams.models import Stream
from modules.streams.services import (
    DEFAULT_STREAMS,
    list_streams,
    resolve_stream_id,
    seed_default_streams,
    stream_by_name,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def academic_year(db_session, tenant):
    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(year)
    db_session.flush()
    return year


@pytest.fixture
def grade(db_session, tenant):
    row = Grade(
        id=_new_id("gr-"), tenant_id=tenant.id,
        name=f"Grade-{uuid.uuid4().hex[:6]}", sequence=11,
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def unit(db_session, tenant):
    row = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id,
        name=f"Campus-{uuid.uuid4().hex[:6]}",
        code=f"C{uuid.uuid4().hex[:6]}",
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def programme(db_session, tenant):
    row = AcademicProgramme(
        id=_new_id("pr-"), tenant_id=tenant.id,
        name=f"Board-{uuid.uuid4().hex[:6]}",
        code=f"B{uuid.uuid4().hex[:6]}",
        board="GSEB",
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def streams(db_session, tenant):
    made = {}
    for index, name in enumerate(("Science", "Commerce")):
        row = Stream(
            id=_new_id("st-"), tenant_id=tenant.id,
            name=f"{name}-{uuid.uuid4().hex[:6]}", sequence=index,
        )
        db_session.add(row)
        made[name] = row
    db_session.flush()
    return made


def _section(tenant, year, grade, letter, stream=None, unit=None, programme=None):
    return Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section=letter,
        academic_year_id=year.id, grade_id=grade.id,
        school_unit_id=unit.id if unit else None,
        programme_id=programme.id if programme else None,
        stream_id=stream.id if stream else None,
    )


# ---------------------------------------------------------------------------
# Identity — the case that could not be stored before
# ---------------------------------------------------------------------------

def test_science_a_and_commerce_a_can_both_exist(
    db_session, tenant, academic_year, grade, streams, unit, programme
):
    db_session.add(_section(tenant, academic_year, grade, "A", streams["Science"], unit, programme))
    db_session.add(_section(tenant, academic_year, grade, "A", streams["Commerce"], unit, programme))
    db_session.flush()

    rows = (
        Class.query.filter_by(
            tenant_id=tenant.id, academic_year_id=academic_year.id, section="A"
        ).all()
    )
    assert len(rows) == 2
    assert {r.stream_id for r in rows} == {
        streams["Science"].id, streams["Commerce"].id
    }


def test_the_same_stream_cannot_take_the_same_section_twice(
    db_session, tenant, academic_year, grade, streams, unit, programme
):
    db_session.add(_section(tenant, academic_year, grade, "A", streams["Science"], unit, programme))
    db_session.flush()

    db_session.begin_nested()
    db_session.add(_section(tenant, academic_year, grade, "A", streams["Science"], unit, programme))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_streamless_sections_keep_the_old_rule(
    db_session, tenant, academic_year, grade, unit, programme
):
    """Grades 1-10 have no stream, and must still not duplicate a section.

    Postgres treats NULLs as distinct, so a single index over a nullable
    stream_id would have quietly stopped protecting almost every class.
    """
    db_session.add(_section(tenant, academic_year, grade, "A", None, unit, programme))
    db_session.flush()

    db_session.begin_nested()
    db_session.add(_section(tenant, academic_year, grade, "A", None, unit, programme))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# ---------------------------------------------------------------------------
# The vocabulary is data
# ---------------------------------------------------------------------------

def test_a_school_can_define_a_stream_nobody_shipped(db_session, tenant):
    """The CHECK constraint refused anything but the four tracks we chose."""
    row = Stream(
        id=_new_id("st-"), tenant_id=tenant.id,
        name=f"Integrated Science {uuid.uuid4().hex[:6]}", code=None, sequence=50,
    )
    db_session.add(row)
    db_session.flush()
    assert row.id is not None


def test_seeding_is_idempotent_and_matches_the_migration(db_session, tenant):
    first = seed_default_streams(tenant.id)
    db_session.flush()
    second = seed_default_streams(tenant.id)
    db_session.flush()

    assert second == 0, "re-seeding must not duplicate the catalogue"
    names = {s.name for s in list_streams(tenant.id)}
    for name, _code, _sequence in DEFAULT_STREAMS:
        assert name in names
    assert first >= 0


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def test_a_name_or_an_id_both_resolve(ctx, db_session, tenant, streams):
    science = streams["Science"]
    assert resolve_stream_id(science.id) == science.id
    assert resolve_stream_id(science.name) == science.id
    assert resolve_stream_id(science.name.upper()) == science.id
    assert resolve_stream_id(None) is None
    assert resolve_stream_id("  ") is None


def test_an_unknown_stream_is_refused_not_invented(ctx, db_session, tenant):
    """Minting a row from a typo is how "Sci" and "Science" both come to exist."""
    with pytest.raises(ValueError):
        resolve_stream_id("Definitely Not A Stream")


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------

def test_one_school_cannot_see_or_use_anothers_stream(ctx, db_session, tenant, streams):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    other = Tenant(
        id=_new_id("t-"), name="Other School",
        subdomain=f"test-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()
    theirs = Stream(
        id=_new_id("st-"), tenant_id=other.id,
        name=f"Theirs-{uuid.uuid4().hex[:6]}", sequence=1,
    )
    db_session.add(theirs)
    db_session.flush()

    assert stream_by_name(theirs.name, tenant.id) is None
    with pytest.raises(ValueError):
        resolve_stream_id(theirs.name)

    mine = {s.id for s in list_streams(tenant.id)}
    assert theirs.id not in mine
