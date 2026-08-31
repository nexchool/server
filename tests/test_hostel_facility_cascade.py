"""Retiring a hostel or a room takes what it contains with it.

Hostels and rooms are soft-deleted; beds are retired with status='removed' AND
deleted_at, because get_room filters beds on deleted_at while
ReportService._count_active_beds filters on status. Before this, deleting a
room left its beds untouched, so they stayed countable in a room nobody could
open.
"""

from __future__ import annotations

from modules.hostel.models import HostelBed, HostelRoom
from modules.hostel.services import FacilityService


def _live_beds(session, room_id):
    return (
        session.query(HostelBed)
        .filter(HostelBed.room_id == room_id, HostelBed.deleted_at.is_(None))
        .all()
    )


# ---- Beds ----------------------------------------------------------------


def test_retiring_a_bed_marks_both_columns_readers_check(db_session, tenant, room, bed):
    FacilityService(db_session).retire_bed(bed=bed)
    db_session.flush()

    assert bed.status == "removed"
    assert bed.deleted_at is not None


# ---- Rooms ---------------------------------------------------------------


def test_retiring_a_room_retires_its_beds(db_session, tenant, hostel, room, beds):
    assert len(_live_beds(db_session, room.id)) == 4

    FacilityService(db_session).retire_room(tenant_id=tenant.id, room=room)
    db_session.flush()

    assert room.deleted_at is not None
    assert _live_beds(db_session, room.id) == []
    for b in beds:
        assert b.status == "removed"
        assert b.deleted_at is not None


def test_retiring_a_room_leaves_another_room_alone(
    db_session, tenant, hostel, room, beds
):
    other = HostelRoom(
        id="r-untouched-1",
        tenant_id=tenant.id,
        hostel_id=hostel.id,
        room_number="199",
        capacity=2,
    )
    db_session.add(other)
    db_session.flush()
    keeper = HostelBed(
        id="b-untouched-1", tenant_id=tenant.id, room_id=other.id, bed_number="Z1"
    )
    db_session.add(keeper)
    db_session.flush()

    FacilityService(db_session).retire_room(tenant_id=tenant.id, room=room)
    db_session.flush()

    assert other.deleted_at is None
    assert keeper.deleted_at is None
    assert len(_live_beds(db_session, other.id)) == 1


# ---- Hostels -------------------------------------------------------------


def test_retiring_a_hostel_cascades_through_rooms_to_beds(
    db_session, tenant, hostel, room, beds
):
    FacilityService(db_session).retire_hostel(tenant_id=tenant.id, hostel=hostel)
    db_session.flush()

    assert hostel.deleted_at is not None
    assert room.deleted_at is not None
    assert _live_beds(db_session, room.id) == []


def test_retiring_a_hostel_leaves_another_hostel_alone(
    db_session, tenant, hostel, room, beds
):
    from modules.hostel.models import Hostel

    other_hostel = Hostel(
        id="h-untouched-1", tenant_id=tenant.id, name="Girls Hostel B", capacity=10
    )
    db_session.add(other_hostel)
    db_session.flush()
    other_room = HostelRoom(
        id="r-other-1",
        tenant_id=tenant.id,
        hostel_id=other_hostel.id,
        room_number="201",
        capacity=2,
    )
    db_session.add(other_room)
    db_session.flush()

    FacilityService(db_session).retire_hostel(tenant_id=tenant.id, hostel=hostel)
    db_session.flush()

    assert other_hostel.deleted_at is None
    assert other_room.deleted_at is None


def test_retiring_an_already_empty_hostel_is_fine(db_session, tenant, hostel):
    """A hostel with no rooms yet — the create-then-delete path."""
    FacilityService(db_session).retire_hostel(tenant_id=tenant.id, hostel=hostel)
    db_session.flush()

    assert hostel.deleted_at is not None
