"""Per-room occupancy belongs in the rooms list, not in the browser.

The hostel detail screen fetched every active allocation in the hostel and
counted them by room_id on the client. That was already the wrong shape — a
hostel with 300 boarders sent 300 rows to render a number next to each room —
and it became actively wrong once the allocations endpoint started paging:
the first 25 rows would be counted and every other room would render as empty.

So the count moves to where it can be computed correctly at any size: one
grouped query beside the rooms themselves.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from flask import g


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _student(db_session, tenant):
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:10]
    person = Person(id=f"pe-{suffix}", tenant_id=tenant.id, full_name="Boarder")
    db_session.add(person)
    db_session.flush()
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"{suffix}@test.school", password_hash="x" * 60,
                name="Boarder", person_id=person.id)
    db_session.add(user)
    db_session.flush()
    student = Student(id=f"s-{suffix}", tenant_id=tenant.id, user_id=user.id,
                      person_id=person.id, admission_number=f"ADM-{suffix}")
    db_session.add(student)
    db_session.flush()
    return student


def _occupy(db_session, tenant, hostel, room, *, status="active"):
    from modules.hostel.models import HostelAllocation, HostelBed

    bed = HostelBed(tenant_id=tenant.id, room_id=room.id,
                    bed_number=f"B-{uuid.uuid4().hex[:6]}")
    db_session.add(bed)
    db_session.flush()
    allocation = HostelAllocation(
        tenant_id=tenant.id, hostel_id=hostel.id, room_id=room.id,
        bed_id=bed.id, student_id=_student(db_session, tenant).id,
        check_in_at=datetime(2026, 6, 1), status=status,
    )
    db_session.add(allocation)
    db_session.flush()
    return allocation


def _room(db_session, tenant, hostel, number):
    from modules.hostel.models import HostelRoom

    room = HostelRoom(tenant_id=tenant.id, hostel_id=hostel.id,
                      room_number=number, capacity=4)
    db_session.add(room)
    db_session.flush()
    return room


def test_each_room_reports_how_many_beds_are_taken(ctx, db_session, tenant, hostel):
    from modules.hostel.services.allocation_service import AllocationService

    busy = _room(db_session, tenant, hostel, "101")
    quiet = _room(db_session, tenant, hostel, "102")
    for _ in range(3):
        _occupy(db_session, tenant, hostel, busy)

    counts = AllocationService(db_session).occupied_counts_by_room(
        tenant_id=tenant.id, hostel_id=hostel.id
    )

    assert counts[busy.id] == 3
    assert counts.get(quiet.id, 0) == 0


def test_a_checked_out_boarder_no_longer_occupies_a_bed(
    ctx, db_session, tenant, hostel
):
    from modules.hostel.services.allocation_service import AllocationService

    room = _room(db_session, tenant, hostel, "201")
    _occupy(db_session, tenant, hostel, room)
    _occupy(db_session, tenant, hostel, room, status="completed")

    counts = AllocationService(db_session).occupied_counts_by_room(
        tenant_id=tenant.id, hostel_id=hostel.id
    )

    assert counts[room.id] == 1


def test_the_count_is_not_capped_by_a_page(ctx, db_session, tenant, hostel):
    """The whole point: a big hostel must still report the true number."""
    from modules.hostel.services.allocation_service import AllocationService

    room = _room(db_session, tenant, hostel, "301")
    for _ in range(60):
        _occupy(db_session, tenant, hostel, room)

    counts = AllocationService(db_session).occupied_counts_by_room(
        tenant_id=tenant.id, hostel_id=hostel.id
    )

    assert counts[room.id] == 60


def test_it_is_one_query_regardless_of_how_many_rooms(
    ctx, db_session, tenant, hostel
):
    from core.database import db
    from modules.hostel.services.allocation_service import AllocationService
    from sqlalchemy import event

    for i in range(5):
        room = _room(db_session, tenant, hostel, f"4{i:02d}")
        _occupy(db_session, tenant, hostel, room)

    seen = []
    engine = db.session.get_bind()

    def count(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        AllocationService(db_session).occupied_counts_by_room(
            tenant_id=tenant.id, hostel_id=hostel.id
        )
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert len(seen) == 1, f"expected one grouped query, ran {len(seen)}"


def test_the_rooms_list_carries_the_count(ctx, db_session, tenant, hostel):
    """What the screen actually reads."""
    from modules.hostel.routes import _rooms_with_occupancy

    room = _room(db_session, tenant, hostel, "501")
    empty = _room(db_session, tenant, hostel, "502")
    _occupy(db_session, tenant, hostel, room)
    _occupy(db_session, tenant, hostel, room)

    rows = {r["id"]: r for r in _rooms_with_occupancy(tenant.id, hostel.id)}

    assert rows[room.id]["occupied_count"] == 2
    assert rows[empty.id]["occupied_count"] == 0
