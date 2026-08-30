"""Listing student fees must not cost four queries per row.

`_build_student_fees_query` carried no eager loads, and the serialising loop
then touched four lazy relationships on every row — `sf.items`, `sf.student`,
`sf.student.user` and `sf.fee_structure`. With `include_items` defaulting to
true and the endpoint unbounded when no page is asked for, a fee ledger for a
15,000-student tenant was roughly 60,000 queries in one request.

The second finding is a correctness one that the same line hides:
`sf.student.user.name` reads the name off the **login**, and
`students.user_id` has been nullable since migration 094 — so any student
without an account serialises with `student_name: null`. The students module
itself reads `self.person.full_name` (`students/models.py:200`), which is the
owner the person-centric model gives the name to. Same shape as debt 15, where
`TeacherLeave` read a requester's name off `self.teacher.user.name` and left
every account-less teacher nameless in the leave queue.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy import event

from core.database import db
from modules.finance.services import student_fee_service


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

    row = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _structure(db_session, tenant, year):
    """A structure and the one component its items point at."""
    from modules.finance.models import FeeComponent, FeeStructure

    row = FeeStructure(
        id=_new_id("fs-"), tenant_id=tenant.id,
        name=f"Annual {uuid.uuid4().hex[:5]}",
        academic_year_id=year.id, due_date=date(2026, 5, 15),
    )
    db_session.add(row)
    db_session.flush()
    component = FeeComponent(
        id=_new_id("fc-"), tenant_id=tenant.id, fee_structure_id=row.id,
        name="Tuition", amount=25000,
    )
    db_session.add(component)
    db_session.flush()
    return row, component


def _student(db_session, tenant, year, *, with_login: bool):
    """A child, with or without an account — `user_id` is nullable by design."""
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:8]
    person = Person(
        id=_new_id("pe-"), tenant_id=tenant.id, full_name=f"Child {suffix}"
    )
    db_session.add(person)
    db_session.flush()

    user = None
    if with_login:
        user = User(
            id=_new_id("us-"), tenant_id=tenant.id,
            email=f"{suffix}@test.school", password_hash="x" * 60,
            name=f"Child {suffix}", person_id=person.id,
        )
        db_session.add(user)
        db_session.flush()

    student = Student(
        id=_new_id("st-"), tenant_id=tenant.id, person_id=person.id,
        user_id=user.id if user else None,
        admission_number=f"A{suffix}", academic_year_id=year.id,
    )
    db_session.add(student)
    db_session.flush()
    return student


def _fee(db_session, tenant, student, structure, component):
    from modules.finance.models import StudentFee, StudentFeeItem

    fee = StudentFee(
        id=_new_id("sf-"), tenant_id=tenant.id, student_id=student.id,
        fee_structure_id=structure.id, total_amount=25000, paid_amount=0,
        status="pending", due_date=date(2026, 5, 15),
    )
    db_session.add(fee)
    db_session.flush()
    db_session.add(StudentFeeItem(
        id=_new_id("sfi-"), tenant_id=tenant.id, student_fee_id=fee.id,
        fee_component_id=component.id, amount=25000,
    ))
    db_session.flush()
    return fee


def _seed(db_session, tenant, year, *, students: int, with_login: bool = True):
    structure, component = _structure(db_session, tenant, year)
    for _ in range(students):
        _fee(db_session, tenant,
             _student(db_session, tenant, year, with_login=with_login),
             structure, component)


def _queries_to_list(**kwargs) -> int:
    seen: list = []

    def record(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        rows = student_fee_service.list_student_fees(**kwargs)
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    return len(seen), rows


def test_listing_does_not_cost_a_query_per_row(ctx, db_session, tenant, year):
    """Cost must be flat in the number of rows, not proportional to it.

    Not asserted as *equal*: `selectinload` fetches a collection in its own
    SELECT, and SQLAlchemy may split that across a bounded number of statements.
    What matters is the slope — per-row loading would have added eighteen
    queries for the six extra rows below, which it did before this was fixed.
    """
    _seed(db_session, tenant, year, students=2)
    small, small_rows = _queries_to_list()

    _seed(db_session, tenant, year, students=18)
    large, large_rows = _queries_to_list()

    assert len(small_rows) == 2 and len(large_rows) == 20, (small_rows, large_rows)
    extra_rows = 20 - 2
    assert large - small <= 3, (
        f"listing grew by {large - small} queries for {extra_rows} more rows "
        f"({(large - small) / extra_rows:.2f} each) — still loading per row"
    )


def test_a_student_without_a_login_still_has_a_name(ctx, db_session, tenant, year):
    """`user_id` is nullable, and the name belongs to the Person."""
    _seed(db_session, tenant, year, students=1, with_login=False)

    _queries, rows = _queries_to_list()

    assert len(rows) == 1
    assert rows[0]["student_name"], (
        "an account-less student serialised with no name — the name was read "
        "off the login rather than the Person"
    )


def test_the_name_is_the_persons(ctx, db_session, tenant, year):
    _seed(db_session, tenant, year, students=1, with_login=True)

    _queries, rows = _queries_to_list()

    assert rows[0]["student_name"].startswith("Child ")
