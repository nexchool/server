"""The teacher's class list counted its children one class at a time.

`get_my_classes` is what a teacher opens to take a register — the entry point
to the most-repeated flow in the product. It listed their classes and then ran

    Student.query.filter_by(class_id=cls.id).count()

once per class, so a teacher with eight classes paid eight extra round trips
before seeing anything.

One grouped query over the classes they actually teach.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy import event

from core.database import db
from modules.attendance import services


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


def _class(db_session, tenant, year, section="A"):
    from modules.classes.models import Class

    cls = Class(id=_new_id("c-"), tenant_id=tenant.id,
                name=f"Grade {uuid.uuid4().hex[:3]}", section=section,
                academic_year_id=year.id)
    db_session.add(cls)
    db_session.flush()
    return cls


def _student_in(db_session, tenant, cls):
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:10]
    person = Person(id=f"pe-{suffix}", tenant_id=tenant.id, full_name="Child")
    db_session.add(person)
    db_session.flush()
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"{suffix}@t.test", password_hash="x" * 60,
                name="Child", person_id=person.id)
    db_session.add(user)
    db_session.flush()
    student = Student(id=f"s-{suffix}", tenant_id=tenant.id, user_id=user.id,
                      person_id=person.id, admission_number=f"A-{suffix[:8]}",
                      class_id=cls.id, academic_year_id=cls.academic_year_id)
    db_session.add(student)
    db_session.flush()
    return student


@pytest.fixture
def teaches(monkeypatch):
    """Which classes the teacher has is not what these tests are about."""
    def _set(class_ids):
        monkeypatch.setattr(services, "get_teacher_class_ids",
                            lambda user_id: list(class_ids))
    return _set


def test_each_class_reports_its_own_roll(ctx, db_session, tenant, year, teaches):
    busy = _class(db_session, tenant, year, "A")
    small = _class(db_session, tenant, year, "B")
    for _ in range(3):
        _student_in(db_session, tenant, busy)
    _student_in(db_session, tenant, small)
    teaches([busy.id, small.id])

    rows = {r["id"]: r for r in services.get_my_classes("u-anyone")}

    assert rows[busy.id]["student_count"] == 3
    assert rows[small.id]["student_count"] == 1


def test_an_empty_class_reports_zero(ctx, db_session, tenant, year, teaches):
    """Absent from a grouped count is zero, not missing."""
    empty = _class(db_session, tenant, year)
    teaches([empty.id])

    [row] = services.get_my_classes("u-anyone")

    assert row["student_count"] == 0


def test_a_teacher_with_no_classes_gets_nothing(ctx, db_session, teaches):
    teaches([])

    assert services.get_my_classes("u-anyone") == []


def test_the_cost_does_not_grow_with_the_number_of_classes(
    ctx, db_session, tenant, year, teaches
):
    seen: list[str] = []

    def record(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    def measure(class_ids):
        teaches(class_ids)
        seen.clear()
        event.listen(db.engine, "before_cursor_execute", record)
        try:
            services.get_my_classes("u-anyone")
        finally:
            event.remove(db.engine, "before_cursor_execute", record)
        return len(seen)

    few = [_class(db_session, tenant, year) for _ in range(2)]
    for c in few:
        _student_in(db_session, tenant, c)
    small = measure([c.id for c in few])

    many = [_class(db_session, tenant, year) for _ in range(18)]
    for c in many:
        _student_in(db_session, tenant, c)
    large = measure([c.id for c in few + many])

    assert large == small, (
        f"{small} queries for 2 classes, {large} for 20 — one per class"
    )
