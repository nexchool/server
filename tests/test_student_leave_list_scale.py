"""The leave queue named children off their login, and cost a query per row.

Three defects in the same list, all of which the approval queue shows to a
teacher:

1. `StudentLeave.to_dict()` reads `self.student.user.name`. `students.user_id`
   has been nullable since migration 094, so a child with no login account
   serialises as `student_name: null` and the teacher approving their leave
   sees a blank where the name goes. The students module itself names a
   student `self.person.full_name` (`students/models.py:200`) — the person is
   the owner of the name. This is the same shape as debt 15, where
   `TeacherLeave` read a requester's name off `self.teacher.user.name`.

2. `to_dict` touches three lazy relationships — `student`, `student.user` and
   `decided_by` — so serialising a queue was several queries per row.

3. `list_visible_for_user` ends in `.all()`. For a student that is their own
   handful of leaves, but an admin holds `student.leave.read.all`, and for
   them it is every leave the school has ever recorded.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy import event

from core.database import db
from modules.student_leaves import services


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _student(db_session, tenant, *, name, with_login=True):
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
                      person_id=person.id, admission_number=f"A-{suffix[:8]}")
    db_session.add(student)
    db_session.flush()
    return student


@pytest.fixture
def klass(db_session, tenant):
    """`student_leaves.class_id` is NOT NULL — a leave is always from a class."""
    from modules.academics.academic_year.models import AcademicYear
    from modules.classes.models import Class

    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id,
        name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(year)
    db_session.flush()

    cls = Class(id=_new_id("c-"), tenant_id=tenant.id, name="Grade 5",
                section="A", academic_year_id=year.id)
    db_session.add(cls)
    db_session.flush()
    return cls


def _leave(db_session, tenant, student, klass, *, status="pending_class_teacher"):
    from modules.student_leaves.models import StudentLeave

    leave = StudentLeave(
        id=_new_id("sl-"), tenant_id=tenant.id, student_id=student.id,
        class_id=klass.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 3),
        reason="Family function", status=status, leave_type="family",
    )
    db_session.add(leave)
    db_session.flush()
    return leave


# ---------------------------------------------------------------------------
# 1. A child without a login still has a name
# ---------------------------------------------------------------------------

def test_a_child_without_a_login_is_still_named(ctx, db_session, tenant, klass):
    """The teacher approving this leave saw a blank where the name belongs."""
    child = _student(db_session, tenant, name="Ishaan Roy", with_login=False)
    leave = _leave(db_session, tenant, child, klass)

    assert leave.to_dict()["student_name"] == "Ishaan Roy"


def test_a_child_with_a_login_is_unaffected(ctx, db_session, tenant, klass):
    child = _student(db_session, tenant, name="Neha Gupta", with_login=True)
    leave = _leave(db_session, tenant, child, klass)

    assert leave.to_dict()["student_name"] == "Neha Gupta"


# ---------------------------------------------------------------------------
# 2. Not a query per row
# ---------------------------------------------------------------------------

def _queries_to_serialise(rows):
    seen: list[str] = []

    def record(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        [r.to_dict() for r in rows]
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    return len(seen)


def test_serialising_a_queue_does_not_cost_a_query_per_leave(
    ctx, db_session, tenant, klass
):
    """Cost must be flat in the number of rows, not proportional to it."""
    for _ in range(3):
        _leave(db_session, tenant, _student(db_session, tenant, name="A Child"), klass)
    db_session.expire_all()
    small = _queries_to_serialise(_rows(tenant))

    for _ in range(15):
        _leave(db_session, tenant, _student(db_session, tenant, name="A Child"), klass)
    db_session.expire_all()
    large = _queries_to_serialise(_rows(tenant))

    assert large - small <= 2, (
        f"{small} queries for 3 leaves, {large} for 18 — cost grows per row"
    )


def _rows(tenant):
    """The queue query, eager loads and all."""
    from modules.student_leaves.models import StudentLeave

    return services.eager_leaves(
        db.session.query(StudentLeave).filter(StudentLeave.tenant_id == tenant.id)
    ).all()


# ---------------------------------------------------------------------------
# 3. Bounded for whoever can see everything
# ---------------------------------------------------------------------------

@pytest.fixture
def admin(db_session, tenant):
    """Someone holding student.leave.read.all — every leave in the school."""
    from modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"admin-{suffix}@test.school", password_hash="x" * 60,
                name="Head")
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def _sees_everything(monkeypatch):
    from modules.rbac import services as rbac

    monkeypatch.setattr(
        rbac, "has_permission",
        lambda user_id, perm: perm == "student.leave.read.all",
    )


def test_the_list_comes_back_a_page_at_a_time(
    ctx, db_session, tenant, admin, _sees_everything, klass
):
    for _ in range(60):
        _leave(db_session, tenant, _student(db_session, tenant, name="A Child"), klass)

    result = services.list_visible_for_user(admin)

    assert len(result["items"]) <= services.LEAVE_PAGE_SIZE
    assert len(result["items"]) < 60
    assert result["total"] == 60


def test_paging_sees_each_leave_exactly_once(
    ctx, db_session, tenant, admin, _sees_everything, klass
):
    made = {
        _leave(db_session, tenant, _student(db_session, tenant, name="A Child"), klass).id
        for _ in range(55)
    }

    seen: list[str] = []
    page = 1
    while True:
        result = services.list_visible_for_user(admin, page=page)
        seen.extend(r.id for r in result["items"])
        if page >= result["total_pages"]:
            break
        page += 1

    assert len(seen) == len(set(seen)), "a leave was served on two pages"
    assert set(seen) == made, "a leave was never served at all"


def test_an_enormous_page_size_is_capped(
    ctx, db_session, tenant, admin, _sees_everything, klass
):
    for _ in range(60):
        _leave(db_session, tenant, _student(db_session, tenant, name="A Child"), klass)

    result = services.list_visible_for_user(admin, per_page=100_000)

    assert len(result["items"]) <= services.LEAVE_MAX_PAGE_SIZE


@pytest.mark.parametrize("bad", [0, -1, "abc", None])
def test_a_nonsense_page_is_treated_as_the_first(
    ctx, db_session, tenant, admin, _sees_everything, klass, bad
):
    _leave(db_session, tenant, _student(db_session, tenant, name="A Child"), klass)

    result = services.list_visible_for_user(admin, page=bad)

    assert result["page"] == 1
    assert result["total"] == 1


def test_someone_with_no_read_permission_still_gets_the_empty_envelope(
    ctx, db_session, tenant, admin, monkeypatch
):
    """The shape must not change with the caller's permissions."""
    from modules.rbac import services as rbac

    monkeypatch.setattr(rbac, "has_permission", lambda user_id, perm: False)

    result = services.list_visible_for_user(admin)

    assert result["items"] == []
    assert result["total"] == 0
    assert result["total_pages"] == 1
