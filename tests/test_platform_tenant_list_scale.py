"""The control plane counted every tenant's students one tenant at a time.

`list_tenants` pages the tenants correctly and then, for each one on the page,
runs

    Student.query.filter_by(tenant_id=t.id).count()
    Teacher.query.filter_by(tenant_id=t.id).count()

so a page of twenty schools costs forty extra round trips. It is the screen the
company looks at to see its own customers, and it gets slower with every school
signed up — which is the wrong direction for that particular page.

Both counts are one grouped query over the tenants on the page.

Note this runs without `g.tenant_id`: the scope listener in `core/database.py`
returns early when there is no tenant on the request, which is what lets the
control plane read across all of them.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event

from core.database import db
from modules.platform import services


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, db_session):
    """A platform request: authenticated to no particular school."""
    with flask_app.test_request_context("/"):
        yield


def _tenant(db_session, name):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    suffix = uuid.uuid4().hex[:8]
    t = Tenant(
        id=_new_id("t-"), name=name, subdomain=f"sub-{suffix}",
        contact_email=f"{suffix}@school.test",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(t)
    db_session.flush()
    return t


def _student(db_session, tenant):
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
                      person_id=person.id, admission_number=f"A-{suffix[:8]}")
    db_session.add(student)
    db_session.flush()
    return student


def _teacher(db_session, tenant):
    from tests.conftest import employ_for
    from modules.auth.models import User
    from modules.teachers.models import Teacher

    suffix = uuid.uuid4().hex[:10]
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"t-{suffix}@t.test", password_hash="x" * 60,
                name="Teacher")
    db_session.add(user)
    db_session.flush()
    teacher = Teacher(
        id=_new_id("tc-"), tenant_id=tenant.id, user_id=user.id,
        staff_id=employ_for(user, employee_number=f"E-{suffix[:8]}").id,
    )
    db_session.add(teacher)
    db_session.flush()
    return teacher


def _row_for(result, tenant_id):
    return next(r for r in result["data"] if r["id"] == tenant_id)


# ---------------------------------------------------------------------------
# The counts must not change
# ---------------------------------------------------------------------------

def test_each_school_reports_its_own_headcount(ctx, db_session):
    busy = _tenant(db_session, "Busy School")
    quiet = _tenant(db_session, "Quiet School")
    for _ in range(3):
        _student(db_session, busy)
    _student(db_session, quiet)
    _teacher(db_session, busy)
    _teacher(db_session, busy)

    result = services.list_tenants(page=1, per_page=100)

    assert _row_for(result, busy.id)["student_count"] == 3
    assert _row_for(result, busy.id)["teacher_count"] == 2
    assert _row_for(result, quiet.id)["student_count"] == 1
    assert _row_for(result, quiet.id)["teacher_count"] == 0


def test_a_school_with_nobody_in_it_reports_zero(ctx, db_session):
    """Absent from a grouped count is zero, not missing."""
    empty = _tenant(db_session, "Brand New School")

    result = services.list_tenants(page=1, per_page=100)

    row = _row_for(result, empty.id)
    assert row["student_count"] == 0
    assert row["teacher_count"] == 0


def test_the_search_and_paging_still_work(ctx, db_session):
    wanted = _tenant(db_session, "Findable Academy")
    _student(db_session, wanted)
    _tenant(db_session, "Somewhere Else")

    result = services.list_tenants(page=1, per_page=100, search="Findable")

    ids = [r["id"] for r in result["data"]]
    assert ids == [wanted.id]
    assert _row_for(result, wanted.id)["student_count"] == 1


# ---------------------------------------------------------------------------
# The cost must not grow with the customer list
# ---------------------------------------------------------------------------

def test_the_cost_does_not_grow_with_the_number_of_schools(ctx, db_session):
    seen: list[str] = []

    def record(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    def measure():
        seen.clear()
        event.listen(db.engine, "before_cursor_execute", record)
        try:
            services.list_tenants(page=1, per_page=100)
        finally:
            event.remove(db.engine, "before_cursor_execute", record)
        return len(seen)

    for i in range(2):
        _student(db_session, _tenant(db_session, f"School {i}"))
    small = measure()

    for i in range(18):
        _student(db_session, _tenant(db_session, f"School 1{i}"))
    large = measure()

    assert large == small, (
        f"{small} queries for 2 schools, {large} for 20 — two per school"
    )
