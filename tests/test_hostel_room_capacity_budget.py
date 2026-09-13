"""Rooms cannot promise more beds than the hostel holds.

A hostel's capacity is the number of boarders it can house. Every room carved
out of it takes a share of that number, so the active rooms of a hostel may
never add up to more than the hostel's own capacity — whether a room is being
added, a room is being enlarged, or the hostel itself is being shrunk under
rooms that already exist. Retired (soft-deleted) rooms have handed their share
back and do not count.
"""

from __future__ import annotations

import pytest

from core.school_time import utc_now
from modules.hostel.models import Hostel, HostelRoom
from modules.hostel.services import FacilityService


def _room(db_session, tenant, hostel, *, number: str, capacity: int) -> HostelRoom:
    room = HostelRoom(
        tenant_id=tenant.id,
        hostel_id=hostel.id,
        room_number=number,
        capacity=capacity,
    )
    db_session.add(room)
    db_session.flush()
    return room


def test_a_room_that_fits_in_the_remaining_capacity_is_accepted(
    db_session, tenant, hostel, room
):
    # hostel holds 20, room 101 takes 4 → 16 left
    service = FacilityService(db_session)
    service.assert_room_capacity_fits(
        tenant_id=tenant.id, hostel=hostel, room_capacity=16
    )


def test_a_room_that_overshoots_the_hostel_capacity_is_refused(
    db_session, tenant, hostel, room
):
    service = FacilityService(db_session)
    with pytest.raises(ValueError, match="at most 16"):
        service.assert_room_capacity_fits(
            tenant_id=tenant.id, hostel=hostel, room_capacity=17
        )


def test_retired_rooms_hand_their_share_back(db_session, tenant, hostel, room):
    room.deleted_at = utc_now()
    db_session.flush()

    service = FacilityService(db_session)
    service.assert_room_capacity_fits(
        tenant_id=tenant.id, hostel=hostel, room_capacity=20
    )


def test_rooms_of_another_hostel_do_not_count(db_session, tenant, hostel, room):
    other = Hostel(tenant_id=tenant.id, name="Girls Hostel B", capacity=10)
    db_session.add(other)
    db_session.flush()
    _room(db_session, tenant, other, number="201", capacity=10)

    service = FacilityService(db_session)
    service.assert_room_capacity_fits(
        tenant_id=tenant.id, hostel=hostel, room_capacity=16
    )


def test_enlarging_a_room_counts_the_other_rooms_but_not_its_old_self(
    db_session, tenant, hostel, room
):
    _room(db_session, tenant, hostel, number="102", capacity=10)
    # 20 total, 102 takes 10 → room 101 may grow from 4 up to 10, not 11
    service = FacilityService(db_session)
    service.assert_room_capacity_fits(
        tenant_id=tenant.id, hostel=hostel, room_capacity=10, exclude_room_id=room.id
    )
    with pytest.raises(ValueError, match="at most 10"):
        service.assert_room_capacity_fits(
            tenant_id=tenant.id, hostel=hostel, room_capacity=11, exclude_room_id=room.id
        )


def test_a_hostel_cannot_shrink_below_the_beds_its_rooms_already_hold(
    db_session, tenant, hostel, room
):
    _room(db_session, tenant, hostel, number="102", capacity=6)
    # rooms add up to 10
    service = FacilityService(db_session)
    service.assert_hostel_capacity_fits(
        tenant_id=tenant.id, hostel=hostel, new_capacity=10
    )
    with pytest.raises(ValueError, match="10 beds"):
        service.assert_hostel_capacity_fits(
            tenant_id=tenant.id, hostel=hostel, new_capacity=9
        )
