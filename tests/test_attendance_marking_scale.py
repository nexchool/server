"""Marking a register cost two queries per child, every morning.

Taking attendance is the most-repeated write in the product: every class,
every day. `upsert_records` walked the submitted rows and, for each one, ran

    Student.query.filter_by(id=student_id, ...).first()
    AttendanceRecord.query.filter_by(session_id=..., student_id=...).first()

so a class of forty cost eighty round trips per submission, and a school with
sixty-five sections spent several thousand queries in the half hour when
registers are taken. Both lookups are over sets small enough to fetch once.

The read side had the same shape: `list_records_for_session` — what the
marking screen loads — ran `Student.query.get()` per row and then touched
`st.user.name`, which is a second lazy load *and* the nameless-child bug: a
student with no login account rendered with no name on the register.

These tests pin the behaviour first, because none of it may change, and then
the cost, which is the actual defect.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy import event

from core.database import db
from modules.attendance import session_services as svc


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id,
        name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(ay)
    db_session.flush()
    return ay


@pytest.fixture
def klass(db_session, tenant, year):
    from modules.classes.models import Class

    cls = Class(id=_new_id("c-"), tenant_id=tenant.id, name="Grade 4",
                section="A", academic_year_id=year.id)
    db_session.add(cls)
    db_session.flush()
    return cls


@pytest.fixture
def marker(db_session, tenant):
    from modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"{suffix}@test.school", password_hash="x" * 60,
                name="Class Teacher")
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def _may_mark(monkeypatch):
    """Permission is not what these tests are about."""
    monkeypatch.setattr(svc, "can_user_mark_session", lambda *a, **k: True)


def _student(db_session, tenant, klass, *, name="A Child", with_login=True):
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:10]
    person = Person(id=f"pe-{suffix}", tenant_id=tenant.id, full_name=name)
    db_session.add(person)
    db_session.flush()

    user_id = None
    if with_login:
        user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                    email=f"{suffix}@test.school", password_hash="x" * 60,
                    name=name, person_id=person.id)
        db_session.add(user)
        db_session.flush()
        user_id = user.id

    student = Student(id=f"s-{suffix}", tenant_id=tenant.id, user_id=user_id,
                      person_id=person.id, admission_number=f"A-{suffix[:8]}",
                      class_id=klass.id, academic_year_id=klass.academic_year_id)
    db_session.add(student)
    db_session.flush()
    return student


@pytest.fixture
def session_row(db_session, tenant, klass):
    from modules.academics.backbone.models import AttendanceSession

    s = AttendanceSession(
        id=_new_id("as-"), tenant_id=tenant.id, class_id=klass.id,
        session_date=date(2026, 9, 1), status="draft",
    )
    db_session.add(s)
    db_session.flush()
    return s


# ---------------------------------------------------------------------------
# Behaviour, which must not change
# ---------------------------------------------------------------------------

def test_marking_creates_a_record_for_each_child(
    ctx, db_session, tenant, klass, marker, session_row, _may_mark
):
    children = [_student(db_session, tenant, klass) for _ in range(3)]

    result = svc.upsert_records(
        tenant.id, session_row.id, marker.id,
        [{"student_id": c.id, "status": "present"} for c in children],
    )

    assert result["success"] is True
    assert result["created"] == 3
    assert result["updated"] == 0


def test_marking_again_updates_rather_than_duplicates(
    ctx, db_session, tenant, klass, marker, session_row, _may_mark
):
    child = _student(db_session, tenant, klass)
    svc.upsert_records(tenant.id, session_row.id, marker.id,
                       [{"student_id": child.id, "status": "absent"}])

    result = svc.upsert_records(tenant.id, session_row.id, marker.id,
                                [{"student_id": child.id, "status": "present"}])

    assert result["created"] == 0
    assert result["updated"] == 1

    from modules.academics.backbone.models import AttendanceRecord
    rows = AttendanceRecord.query.filter_by(
        attendance_session_id=session_row.id, student_id=child.id
    ).all()
    assert len(rows) == 1
    assert rows[0].status == "present"


def test_a_child_from_another_class_is_skipped_not_marked(
    ctx, db_session, tenant, klass, marker, session_row, _may_mark, year
):
    from modules.classes.models import Class

    other = Class(id=_new_id("c-"), tenant_id=tenant.id, name="Grade 5",
                  section="B", academic_year_id=year.id)
    db_session.add(other)
    db_session.flush()
    outsider = _student(db_session, tenant, other)

    result = svc.upsert_records(tenant.id, session_row.id, marker.id,
                                [{"student_id": outsider.id, "status": "present"}])

    assert result["created"] == 0
    assert [s["student_id"] for s in result["skipped"]] == [outsider.id]
    assert "not in this class" in result["skipped"][0]["reason"]


def test_an_unknown_student_is_skipped(
    ctx, db_session, tenant, klass, marker, session_row, _may_mark
):
    result = svc.upsert_records(tenant.id, session_row.id, marker.id,
                                [{"student_id": "s-nobody", "status": "present"}])

    assert result["created"] == 0
    assert result["skipped"][0]["student_id"] == "s-nobody"


def test_an_invalid_status_is_skipped(
    ctx, db_session, tenant, klass, marker, session_row, _may_mark
):
    child = _student(db_session, tenant, klass)

    result = svc.upsert_records(
        tenant.id, session_row.id, marker.id,
        [{"student_id": child.id, "status": "on the moon"}],
    )

    assert result["created"] == 0
    assert "invalid status" in result["skipped"][0]["reason"]


def test_a_mixed_submission_marks_the_good_rows(
    ctx, db_session, tenant, klass, marker, session_row, _may_mark
):
    good = _student(db_session, tenant, klass)

    result = svc.upsert_records(
        tenant.id, session_row.id, marker.id,
        [
            {"student_id": good.id, "status": "present"},
            {"student_id": "s-nobody", "status": "present"},
            {"student_id": good.id, "status": "late"},   # same child again
        ],
    )

    assert result["created"] == 1
    assert result["updated"] == 1, "the repeat must update the row just created"
    assert len(result["skipped"]) == 1


# ---------------------------------------------------------------------------
# The register screen's read
# ---------------------------------------------------------------------------

def test_the_register_names_a_child_without_a_login(
    ctx, db_session, tenant, klass, marker, session_row, _may_mark
):
    """`st.user.name` left account-less children nameless on the register."""
    child = _student(db_session, tenant, klass, name="Aarav Shah",
                     with_login=False)
    svc.upsert_records(tenant.id, session_row.id, marker.id,
                       [{"student_id": child.id, "status": "present"}])

    [row] = svc.list_records_for_session(tenant.id, session_row.id)

    assert row["student_name"] == "Aarav Shah"
    assert row["admission_number"] == child.admission_number


def test_the_register_still_names_a_child_with_a_login(
    ctx, db_session, tenant, klass, marker, session_row, _may_mark
):
    child = _student(db_session, tenant, klass, name="Diya Menon")
    svc.upsert_records(tenant.id, session_row.id, marker.id,
                       [{"student_id": child.id, "status": "present"}])

    [row] = svc.list_records_for_session(tenant.id, session_row.id)

    assert row["student_name"] == "Diya Menon"


# ---------------------------------------------------------------------------
# Cost, which is the defect
# ---------------------------------------------------------------------------

def _count_queries(fn, *, selects_only: bool = False):
    """Statements issued while `fn` runs.

    `selects_only` isolates the lookups from the writes: marking a register
    genuinely has to INSERT a row per child, so counting those would hide the
    thing under test — whether the *lookups* are batched.
    """
    seen: list[str] = []

    def record(conn, cursor, statement, params, context, executemany):
        if selects_only and not statement.lstrip().upper().startswith("SELECT"):
            return
        seen.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        fn()
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    return len(seen)


def test_marking_cost_does_not_grow_with_the_class_size(
    ctx, db_session, tenant, klass, marker, session_row, _may_mark
):
    """Two lookups per child is eighty round trips for one register.

    Only SELECTs are counted: the INSERTs are the work, and they have to
    happen. What must not grow is the number of times the register is
    interrogated before it is written.
    """
    # The ids are read out *before* counting starts: `upsert_records` commits,
    # which expires these objects, so building the payload inside the measured
    # block would re-select them and count the test's own work as the code's.
    few = [_student(db_session, tenant, klass).id for _ in range(3)]
    small_payload = [{"student_id": i, "status": "present"} for i in few]
    small = _count_queries(lambda: svc.upsert_records(
        tenant.id, session_row.id, marker.id, small_payload,
    ), selects_only=True)

    many = [_student(db_session, tenant, klass).id for _ in range(18)]
    large_payload = [
        {"student_id": i, "status": "present"} for i in few + many
    ]
    large = _count_queries(lambda: svc.upsert_records(
        tenant.id, session_row.id, marker.id, large_payload,
    ), selects_only=True)

    # Not asserted as equal: SQLAlchemy re-materialises rows the previous
    # commit expired, and may split an IN clause. What matters is the slope —
    # two lookups per child added thirty-six queries for the eighteen extra
    # children below, which is what this caught.
    assert large - small <= 2, (
        f"{small} lookups for 3 children, {large} for 21 — two per child"
    )



def test_reading_the_register_does_not_cost_a_query_per_child(
    ctx, db_session, tenant, klass, marker, session_row, _may_mark
):
    few = [_student(db_session, tenant, klass) for _ in range(3)]
    svc.upsert_records(tenant.id, session_row.id, marker.id,
                       [{"student_id": c.id, "status": "present"} for c in few])
    db_session.expire_all()
    small = _count_queries(
        lambda: svc.list_records_for_session(tenant.id, session_row.id)
    )

    many = [_student(db_session, tenant, klass) for _ in range(18)]
    svc.upsert_records(tenant.id, session_row.id, marker.id,
                       [{"student_id": c.id, "status": "present"} for c in many])
    db_session.expire_all()
    large = _count_queries(
        lambda: svc.list_records_for_session(tenant.id, session_row.id)
    )

    assert large - small <= 2, (
        f"{small} queries for 3 children, {large} for 21 — one or more per child"
    )
