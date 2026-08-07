"""The school's clock, and the two ways the server's clock used to answer for it.

An instant is stored in UTC and says so. A school day is decided where the
school is. Those are different questions, and answering both with the server's
clock produced two separate bugs that only appeared at the edges of the day —
which is how they lasted so long.

These tests pin both, and the guards at the bottom stop the old habits coming
back one file at a time.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from core.school_time import (
    DEFAULT_SCHOOL_TIMEZONE,
    school_timezone,
    school_today,
    to_school_time,
    utc_now,
)

SERVER = pathlib.Path(__file__).resolve().parents[1]
IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# An instant knows what it is
# ---------------------------------------------------------------------------

def test_now_carries_its_offset():
    """The bug this ends: a naive UTC value read as local time.

    `.isoformat()` on a naive datetime emits no offset, and JavaScript reads an
    offsetless datetime as local. An announcement written at 04:32 IST was
    being shown to every user as 23:02 the previous evening — wrong time, wrong
    day, on every naive column that reached a screen.
    """
    assert utc_now().tzinfo is not None
    assert "+00:00" in utc_now().isoformat()


def test_an_instant_survives_the_round_trip_through_a_client():
    """What the fix is actually worth, in the terms the bug appeared in."""
    written_at = datetime(2026, 8, 3, 4, 32, tzinfo=IST)

    # What the API sends, and what a client parsing it recovers.
    on_the_wire = written_at.astimezone(timezone.utc).isoformat()
    recovered = datetime.fromisoformat(on_the_wire).astimezone(IST)

    assert recovered == written_at
    assert recovered.hour == 4 and recovered.day == 3


# ---------------------------------------------------------------------------
# A school day is decided where the school is
# ---------------------------------------------------------------------------

def test_the_school_day_is_the_schools_day_not_the_servers(flask_app, db_session, tenant):
    """The window this closes is 00:00–05:29 IST, every day.

    Our servers run UTC. In that window `date.today()` is still on yesterday —
    and hostel gate passes and the morning bus run both fall inside it.
    """
    with flask_app.test_request_context("/"):
        from flask import g

        g.tenant_id = tenant.id
        g.tenant = tenant

        assert school_today() == datetime.now(IST).date()


def test_a_tenant_east_of_utc_can_be_on_tomorrow(flask_app, db_session, tenant):
    """The property that makes this more than a constant: it follows the tenant.

    A school in Auckland is a day ahead of UTC for most of its working hours.
    Nothing about that is special-cased — it falls out of asking the tenant.
    """
    tenant.timezone = "Pacific/Auckland"
    db_session.flush()

    with flask_app.test_request_context("/"):
        from flask import g

        g.tenant_id = tenant.id
        g.tenant = tenant

        assert school_today() == datetime.now(ZoneInfo("Pacific/Auckland")).date()


def test_an_unusable_timezone_falls_back_rather_than_breaking(
    flask_app, db_session, tenant
):
    """A bad zone name must not take the attendance page down with it."""
    tenant.timezone = "Mars/Olympus_Mons"
    db_session.flush()

    with flask_app.test_request_context("/"):
        from flask import g

        g.tenant_id = tenant.id
        g.tenant = tenant

        assert school_timezone() == ZoneInfo(DEFAULT_SCHOOL_TIMEZONE)


def test_work_outside_a_request_still_gets_an_answer():
    """Celery jobs and scripts have no tenant to ask; they get the default."""
    assert school_today() == datetime.now(ZoneInfo(DEFAULT_SCHOOL_TIMEZONE)).date()


def test_an_old_naive_value_is_read_as_utc():
    """Rows written before the columns carried an offset were UTC.

    Anything that has to interpret one has to make the same assumption the
    migration made, or the two disagree.
    """
    naive = datetime(2026, 8, 2, 23, 2, 13)
    assert to_school_time(naive).astimezone(IST).hour == 4  # 23:02 UTC -> 04:32 IST
    assert to_school_time(None) is None


# ---------------------------------------------------------------------------
# Guards — the old habits must not come back one file at a time
# ---------------------------------------------------------------------------

def _python_files():
    for root in ("modules", "core"):
        for path in (SERVER / root).rglob("*.py"):
            if "test" in str(path):
                continue
            yield path


def _code_lines(path: pathlib.Path):
    """Lines that are code — docstrings and comments do not count."""
    source = path.read_text()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    docstring_lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
           and isinstance(node.value.value, str):
            docstring_lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    for number, line in enumerate(source.split("\n"), start=1):
        if number in docstring_lines or line.lstrip().startswith("#"):
            continue
        yield number, line


def test_nothing_writes_a_naive_timestamp():
    """`datetime.utcnow()` is deprecated, and worse, it is naive.

    One of these anywhere puts a timestamp into the database with nothing
    recording which zone it is in, and the client renders it wrong.
    """
    offenders = [
        f"{path.relative_to(SERVER)}:{number}"
        for path in _python_files()
        for number, line in _code_lines(path)
        if "datetime.utcnow" in line
    ]
    assert not offenders, (
        "Use `utc_now()` from core.school_time — it carries the offset:\n  "
        + "\n  ".join(offenders)
    )


def test_nothing_asks_the_server_what_day_it_is():
    """`date.today()` is the server's date, and the server is in UTC."""
    offenders = [
        f"{path.relative_to(SERVER)}:{number}"
        for path in _python_files()
        for number, line in _code_lines(path)
        if "date.today()" in line
    ]
    assert not offenders, (
        "Use `school_today()` from core.school_time — the school's date, not "
        "the server's:\n  " + "\n  ".join(offenders)
    )


def test_no_model_declares_a_timestamp_without_a_timezone():
    """The column type is where this is won or lost.

    An aware value written to a naive column has its offset stripped on the way
    in, so the code being correct is not enough on its own.
    """
    offenders = []
    for path in _python_files():
        for number, line in _code_lines(path):
            stripped = line.strip()
            if "db.Column(db.DateTime," in line or "db.Column(db.DateTime)" in line:
                offenders.append(f"{path.relative_to(SERVER)}:{number}")
            elif stripped in ("db.DateTime,", "db.DateTime"):
                offenders.append(f"{path.relative_to(SERVER)}:{number}")

    assert not offenders, (
        "Declare timestamps as `db.DateTime(timezone=True)`:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("table_and_column", [("tenants", "timezone")])
def test_the_schema_agrees(db_session, table_and_column):
    """The models say aware; this asks the database whether it agrees."""
    from sqlalchemy import text

    table, column = table_and_column
    exists = db_session.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).first()
    assert exists, f"{table}.{column} is missing"

    naive = db_session.execute(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND data_type = 'timestamp without time zone'"
        )
    ).scalar()
    assert naive == 0, f"{naive} column(s) still store a timestamp with no timezone"
