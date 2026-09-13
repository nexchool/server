"""An allocation must land on a real, usable bed in the room and hostel it names.

A room's residents are counted from allocations grouped by room_id, and a
hostel's residents from allocations grouped by hostel_id. Storing whatever
room and hostel the client sent, or accepting a retired or under-maintenance
bed, lets a room carry more residents than it has beds and files residents
under the wrong building. The service therefore checks the bed is active and
that room and hostel are the bed's own, and a bed with a student in it cannot
be taken out of service.
"""

from __future__ import annotations

import pytest

from core.school_time import utc_now
from modules.hostel.models import Hostel, HostelRoom
from modules.hostel.services import AllocationService, FacilityService


def _allocate(service, *, tenant, hostel_id, room_id, bed, student):
    return service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel_id,
        room_id=room_id,
        bed_id=bed.id,
        check_in_at=utc_now(),
    )


def test_a_retired_bed_cannot_be_allocated(db_session, tenant, hostel, room, bed, student):
    FacilityService(db_session).retire_bed(bed=bed)
    db_session.flush()

    with pytest.raises(ValueError, match="not available"):
        _allocate(AllocationService(db_session), tenant=tenant,
                  hostel_id=hostel.id, room_id=room.id, bed=bed, student=student)


def test_a_bed_under_maintenance_cannot_be_allocated(
    db_session, tenant, hostel, room, bed, student
):
    bed.status = "maintenance"
    db_session.flush()

    with pytest.raises(ValueError, match="not available"):
        _allocate(AllocationService(db_session), tenant=tenant,
                  hostel_id=hostel.id, room_id=room.id, bed=bed, student=student)


def test_the_room_named_must_be_the_beds_own(
    db_session, tenant, hostel, room, bed, student
):
    other_room = HostelRoom(
        tenant_id=tenant.id, hostel_id=hostel.id, room_number="102", capacity=2
    )
    db_session.add(other_room)
    db_session.flush()

    with pytest.raises(ValueError, match="not in room"):
        _allocate(AllocationService(db_session), tenant=tenant,
                  hostel_id=hostel.id, room_id=other_room.id, bed=bed, student=student)


def test_the_hostel_named_must_be_the_rooms_own(
    db_session, tenant, hostel, room, bed, student
):
    other_hostel = Hostel(tenant_id=tenant.id, name="Girls Hostel B", capacity=10)
    db_session.add(other_hostel)
    db_session.flush()

    with pytest.raises(ValueError, match="not in hostel"):
        _allocate(AllocationService(db_session), tenant=tenant,
                  hostel_id=other_hostel.id, room_id=room.id, bed=bed, student=student)


def test_an_occupied_bed_cannot_be_taken_out_of_service(
    db_session, tenant, hostel, room, bed, student
):
    _allocate(AllocationService(db_session), tenant=tenant,
              hostel_id=hostel.id, room_id=room.id, bed=bed, student=student)
    db_session.flush()

    with pytest.raises(ValueError, match="checked in"):
        FacilityService(db_session).set_bed_status(bed=bed, status="maintenance")
    assert bed.status == "active"


def test_a_free_bed_can_go_under_maintenance_and_back(db_session, tenant, room, bed):
    service = FacilityService(db_session)
    service.set_bed_status(bed=bed, status="maintenance")
    assert bed.status == "maintenance"
    service.set_bed_status(bed=bed, status="active")
    assert bed.status == "active"


def test_an_unknown_bed_status_is_refused(db_session, tenant, room, bed):
    with pytest.raises(ValueError, match="status"):
        FacilityService(db_session).set_bed_status(bed=bed, status="broken")
