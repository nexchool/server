"""A boarder without a login account still has a name.

`_attach_student_info` turns the `student_id` on a gatepass, allocation or
visitor log into something a warden can read. It resolved the name by joining
`students` to `users` — an inner join — so a child with no login account
resolved to nothing and the board rendered a blank where the name goes.

That is not a rare shape: `students.user_id` is nullable and plenty of rows
have none, while `students.person_id` is NOT NULL. A child is always a person
and only sometimes someone who can sign in, so the person is what the label
should come from.
"""

from __future__ import annotations

import uuid

import pytest
from flask import g


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _student(db_session, tenant, *, name, suffix, with_login):
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    person = Person(
        id=f"pe-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id, full_name=name
    )
    db_session.add(person)
    db_session.flush()

    user_id = None
    if with_login:
        user = User(
            id=f"u-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id,
            email=f"{suffix}@test.school", password_hash="x" * 60,
            name=name, person_id=person.id,
        )
        db_session.add(user)
        db_session.flush()
        user_id = user.id

    student = Student(
        id=f"s-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id, user_id=user_id,
        person_id=person.id, admission_number=f"ADM-{suffix}",
    )
    db_session.add(student)
    db_session.flush()
    return student


def test_a_boarder_without_a_login_is_still_named(ctx, db_session, tenant):
    from modules.hostel.routes import _attach_student_info

    child = _student(db_session, tenant, name="Kavya Nair", suffix="nl2",
                     with_login=False)

    [row] = _attach_student_info([{"student_id": child.id}])

    assert row["student_name"] == "Kavya Nair", (
        "the board showed a blank where this child's name belongs"
    )
    assert row["admission_number"] == "ADM-nl2"


def test_a_boarder_with_a_login_is_unaffected(ctx, db_session, tenant):
    from modules.hostel.routes import _attach_student_info

    child = _student(db_session, tenant, name="Rohan Das", suffix="wl1",
                     with_login=True)

    [row] = _attach_student_info([{"student_id": child.id}])

    assert row["student_name"] == "Rohan Das"
    assert row["admission_number"] == "ADM-wl1"


def test_an_unresolvable_student_still_has_a_stable_shape(ctx, db_session, tenant):
    """Callers index these keys unconditionally."""
    from modules.hostel.routes import _attach_student_info

    [row] = _attach_student_info([{"student_id": "s-does-not-exist"}])

    assert row["student_name"] is None
    assert row["admission_number"] is None


def test_the_batch_stays_one_query(ctx, db_session, tenant):
    """The point of this helper is that it is not N+1."""
    from core.database import db
    from modules.hostel.routes import _attach_student_info

    children = [
        _student(db_session, tenant, name=f"Child {i}", suffix=f"b{i}",
                 with_login=i % 2 == 0)
        for i in range(6)
    ]
    rows = [{"student_id": c.id} for c in children]

    seen = []
    from sqlalchemy import event

    engine = db.session.get_bind()

    def count(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        labelled = _attach_student_info(rows)
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert len(seen) == 1, f"expected one batch query, ran {len(seen)}"
    assert all(r["student_name"] for r in labelled)
