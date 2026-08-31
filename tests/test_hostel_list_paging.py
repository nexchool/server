"""Allocations and visitor logs grew without bound, but not identically.

Both lists ended in `.all()`. Paging them is not symmetric with the gatepass
board, because one of their callers is not a screen:

`rollover_allocations_task` closes **every** active allocation at year end.
Handing it a page would silently close the first twenty-five boarders and
leave the rest allocated to last year's beds — a data-corruption bug that no
test would notice, because the task would still report success.

So the service offers both shapes, following `get_all_classes`: omit
page/per_page and every matching row comes back. It is the *route* that always
pages, because the HTTP surface is the one that must be bounded.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from flask import g

from modules.hostel.services.allocation_service import AllocationService
from modules.hostel.services.visitor_service import VisitorService


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _student(db_session, tenant, suffix):
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    person = Person(id=f"pe-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id,
                    full_name=f"Child {suffix}")
    db_session.add(person)
    db_session.flush()
    user = User(id=f"u-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id,
                email=f"{suffix}-{uuid.uuid4().hex[:6]}@test.school",
                password_hash="x" * 60, name=f"Child {suffix}",
                person_id=person.id)
    db_session.add(user)
    db_session.flush()
    student = Student(id=f"s-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id,
                      user_id=user.id, person_id=person.id,
                      admission_number=f"ADM-{suffix}-{uuid.uuid4().hex[:6]}")
    db_session.add(student)
    db_session.flush()
    return student


def _allocations(db_session, tenant, hostel, room, count, *, status="active"):
    from modules.hostel.models import HostelAllocation, HostelBed

    made = []
    for i in range(count):
        bed = HostelBed(tenant_id=tenant.id, room_id=room.id,
                        bed_number=f"B{i}-{uuid.uuid4().hex[:6]}")
        db_session.add(bed)
        db_session.flush()
        allocation = HostelAllocation(
            tenant_id=tenant.id, hostel_id=hostel.id, room_id=room.id,
            bed_id=bed.id, student_id=_student(db_session, tenant, f"a{i}").id,
            check_in_at=datetime(2026, 6, 1), status=status,
        )
        db_session.add(allocation)
        db_session.flush()
        made.append(allocation.id)
    return made


def _visitor_logs(db_session, tenant, hostel, count):
    from modules.hostel.models import HostelVisitor, HostelVisitorLog

    made = []
    for i in range(count):
        visitor = HostelVisitor(
            tenant_id=tenant.id, phone=f"9{uuid.uuid4().hex[:9]}",
            name=f"Visitor {i}",
        )
        db_session.add(visitor)
        db_session.flush()
        log = HostelVisitorLog(
            tenant_id=tenant.id, visitor_id=visitor.id,
            student_id=_student(db_session, tenant, f"v{i}").id,
            hostel_id=hostel.id, check_in_at=datetime(2026, 9, 1, 11, 0),
        )
        db_session.add(log)
        db_session.flush()
        made.append(log.id)
    return made


# ---------------------------------------------------------------------------
# The unpaged shape the rollover task depends on
# ---------------------------------------------------------------------------

def test_allocations_unpaged_returns_every_row(
    ctx, db_session, tenant, hostel, room
):
    """`rollover_allocations_task` must see all of them, not the first page."""
    made = _allocations(db_session, tenant, hostel, room, 60)

    result = AllocationService(db_session).list_allocations(
        tenant_id=tenant.id, status="active"
    )

    assert {a.id for a in result["items"]} == set(made)
    assert result["total"] == 60
    assert result["total_pages"] == 1


def test_visitor_logs_unpaged_returns_every_row(
    ctx, db_session, tenant, hostel
):
    made = _visitor_logs(db_session, tenant, hostel, 40)

    result = VisitorService(db_session).list_visitor_logs(tenant_id=tenant.id)

    assert {log.id for log in result["items"]} == set(made)
    assert result["total"] == 40


# ---------------------------------------------------------------------------
# The paged shape the screens ask for
# ---------------------------------------------------------------------------

def test_allocations_page_is_bounded_but_the_total_is_not(
    ctx, db_session, tenant, hostel, room
):
    _allocations(db_session, tenant, hostel, room, 60)

    result = AllocationService(db_session).list_allocations(
        tenant_id=tenant.id, page=1
    )

    assert len(result["items"]) < 60
    assert result["total"] == 60


def test_visitor_logs_page_is_bounded_but_the_total_is_not(
    ctx, db_session, tenant, hostel
):
    _visitor_logs(db_session, tenant, hostel, 40)

    result = VisitorService(db_session).list_visitor_logs(
        tenant_id=tenant.id, page=1
    )

    assert len(result["items"]) < 40
    assert result["total"] == 40


def test_paging_allocations_sees_each_row_exactly_once(
    ctx, db_session, tenant, hostel, room
):
    """Every row shares one check_in_at, so the order must break the tie."""
    made = set(_allocations(db_session, tenant, hostel, room, 55))

    seen: list[str] = []
    page = 1
    while True:
        result = AllocationService(db_session).list_allocations(
            tenant_id=tenant.id, page=page
        )
        seen.extend(a.id for a in result["items"])
        if page >= result["total_pages"]:
            break
        page += 1

    assert len(seen) == len(set(seen)), "a row was served on two pages"
    assert set(seen) == made, "a row was never served at all"


def test_paging_visitor_logs_sees_each_row_exactly_once(
    ctx, db_session, tenant, hostel
):
    made = set(_visitor_logs(db_session, tenant, hostel, 45))

    seen: list[str] = []
    page = 1
    while True:
        result = VisitorService(db_session).list_visitor_logs(
            tenant_id=tenant.id, page=page
        )
        seen.extend(log.id for log in result["items"])
        if page >= result["total_pages"]:
            break
        page += 1

    assert len(seen) == len(set(seen))
    assert set(seen) == made


@pytest.mark.parametrize("bad", [0, -1, "abc"])
def test_a_nonsense_page_is_treated_as_the_first(
    ctx, db_session, tenant, hostel, room, bad
):
    _allocations(db_session, tenant, hostel, room, 3)

    result = AllocationService(db_session).list_allocations(
        tenant_id=tenant.id, page=bad
    )

    assert result["page"] == 1
    assert result["total"] == 3


def test_an_enormous_page_size_is_capped(ctx, db_session, tenant, hostel, room):
    from modules.hostel.services.allocation_service import ALLOCATION_MAX_PAGE_SIZE

    _allocations(db_session, tenant, hostel, room, 60)

    result = AllocationService(db_session).list_allocations(
        tenant_id=tenant.id, page=1, per_page=100_000
    )

    assert len(result["items"]) <= ALLOCATION_MAX_PAGE_SIZE


# ---------------------------------------------------------------------------
# Searching the visit history
# ---------------------------------------------------------------------------

def _visit(db_session, tenant, hostel, *, child_name, visitor_name,
           phone, purpose=None, suffix="x"):
    from modules.hostel.models import HostelVisitor, HostelVisitorLog

    student = _student(db_session, tenant, suffix)
    from modules.people.models import Person
    person = db_session.get(Person, student.person_id)
    person.full_name = child_name
    from modules.auth.models import User
    db_session.get(User, student.user_id).name = child_name

    visitor = HostelVisitor(tenant_id=tenant.id, phone=phone, name=visitor_name)
    db_session.add(visitor)
    db_session.flush()
    log = HostelVisitorLog(
        tenant_id=tenant.id, visitor_id=visitor.id, student_id=student.id,
        hostel_id=hostel.id, check_in_at=datetime(2026, 9, 1, 11, 0),
        purpose=purpose,
    )
    db_session.add(log)
    db_session.flush()
    return log


def test_visitor_history_is_searched_on_the_server(ctx, db_session, tenant, hostel):
    """The page filtered in the browser, so it only searched the loaded page.

    It also matched on `student_id` and `visitor_id` — UUIDs nobody types.
    """
    wanted = _visit(db_session, tenant, hostel, child_name="Meera Iyer",
                    visitor_name="Sunil Iyer", phone="9811111111", suffix="s1")
    _visit(db_session, tenant, hostel, child_name="Other Child",
           visitor_name="Someone Else", phone="9822222222", suffix="s2")

    by_child = VisitorService(db_session).list_visitor_logs(
        tenant_id=tenant.id, search="meera"
    )
    by_visitor = VisitorService(db_session).list_visitor_logs(
        tenant_id=tenant.id, search="Sunil"
    )
    by_phone = VisitorService(db_session).list_visitor_logs(
        tenant_id=tenant.id, search="98111"
    )

    for result in (by_child, by_visitor, by_phone):
        assert {log.id for log in result["items"]} == {wanted.id}
        assert result["total"] == 1


def test_visitor_history_search_matches_the_purpose(ctx, db_session, tenant, hostel):
    wanted = _visit(db_session, tenant, hostel, child_name="Meera Iyer",
                    visitor_name="Sunil Iyer", phone="9833333333",
                    purpose="Collecting for a dental appointment", suffix="s3")
    _visit(db_session, tenant, hostel, child_name="Other Child",
           visitor_name="Someone Else", phone="9844444444",
           purpose="Routine visit", suffix="s4")

    result = VisitorService(db_session).list_visitor_logs(
        tenant_id=tenant.id, search="dental"
    )

    assert {log.id for log in result["items"]} == {wanted.id}


def test_visitor_history_search_survives_a_child_with_no_login(
    ctx, db_session, tenant, hostel
):
    """Same nullable `students.user_id` trap as the gatepass board."""
    from modules.hostel.models import HostelVisitor, HostelVisitorLog
    from modules.people.models import Person
    from modules.students.models import Student

    person = Person(id=f"pe-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id,
                    full_name="Accountless Child")
    db_session.add(person)
    db_session.flush()
    student = Student(id=f"s-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id,
                      user_id=None, person_id=person.id,
                      admission_number="ADM-noacct")
    db_session.add(student)
    db_session.flush()
    visitor = HostelVisitor(tenant_id=tenant.id, phone="9855555555",
                            name="Their Parent")
    db_session.add(visitor)
    db_session.flush()
    log = HostelVisitorLog(
        tenant_id=tenant.id, visitor_id=visitor.id, student_id=student.id,
        hostel_id=hostel.id, check_in_at=datetime(2026, 9, 1, 11, 0),
    )
    db_session.add(log)
    db_session.flush()

    listed = VisitorService(db_session).list_visitor_logs(tenant_id=tenant.id)
    searched = VisitorService(db_session).list_visitor_logs(
        tenant_id=tenant.id, search="ADM-noacct"
    )

    assert log.id in {r.id for r in listed["items"]}
    assert {r.id for r in searched["items"]} == {log.id}


def test_an_empty_visitor_search_is_not_a_filter(ctx, db_session, tenant, hostel):
    log = _visit(db_session, tenant, hostel, child_name="Meera Iyer",
                 visitor_name="Sunil Iyer", phone="9866666666", suffix="s5")

    result = VisitorService(db_session).list_visitor_logs(
        tenant_id=tenant.id, search="  "
    )

    assert {r.id for r in result["items"]} == {log.id}
