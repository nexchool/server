"""A hostel or room that still holds students must not be deletable.

DELETE on a hostel or a room only stamps deleted_at. Nothing downstream filters
allocations by their hostel's or room's deleted_at, so deleting an occupied one
would leave its residents allocated to beds in a place that no longer exists.
Both routes refuse with 409 instead — the same rule delete_bed already applies
to a single bed.

These cover the counts the routes ask for; each route turns a non-zero count
into the 409.
"""

from __future__ import annotations

from core.school_time import utc_now
from modules.hostel.services import AllocationService


def _allocate(service, *, tenant, hostel, room, bed, student):
    """Check a student into a bed, the way the API route does."""
    return service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=utc_now(),
    )


def test_an_empty_hostel_has_no_residents(db_session, tenant, hostel):
    service = AllocationService(db_session)
    assert (
        service.count_active_residents(tenant_id=tenant.id, hostel_id=hostel.id) == 0
    )


def test_an_allocated_student_counts_as_a_resident(
    db_session, tenant, hostel, room, beds, student
):
    service = AllocationService(db_session)
    _allocate(service, tenant=tenant, hostel=hostel, room=room, bed=beds[0], student=student)
    db_session.flush()

    assert (
        service.count_active_residents(tenant_id=tenant.id, hostel_id=hostel.id) == 1
    )


def test_counts_every_resident_not_just_the_first(
    db_session, tenant, hostel, room, beds, student, student2
):
    service = AllocationService(db_session)
    for resident, bed in ((student, beds[0]), (student2, beds[1])):
        _allocate(service, tenant=tenant, hostel=hostel, room=room, bed=bed, student=resident)
    db_session.flush()

    assert (
        service.count_active_residents(tenant_id=tenant.id, hostel_id=hostel.id) == 2
    )


def test_a_checked_out_student_no_longer_blocks_deletion(
    db_session, tenant, hostel, room, beds, student
):
    """Checkout is the documented way to free a hostel for deletion."""
    service = AllocationService(db_session)
    allocation = _allocate(
        service, tenant=tenant, hostel=hostel, room=room, bed=beds[0], student=student
    )
    db_session.flush()
    service.checkout_allocation(allocation.id)
    db_session.flush()

    assert (
        service.count_active_residents(tenant_id=tenant.id, hostel_id=hostel.id) == 0
    )


def test_residents_of_another_hostel_do_not_block_this_one(
    db_session, tenant, hostel, room, beds, student
):
    """The count is per hostel, so a full hostel never locks an empty one."""
    from modules.hostel.models import Hostel

    other = Hostel(
        id="h-other-1", tenant_id=tenant.id, name="Girls Hostel B", capacity=10
    )
    db_session.add(other)
    db_session.flush()

    service = AllocationService(db_session)
    _allocate(service, tenant=tenant, hostel=hostel, room=room, bed=beds[0], student=student)
    db_session.flush()

    assert service.count_active_residents(tenant_id=tenant.id, hostel_id=hostel.id) == 1
    assert service.count_active_residents(tenant_id=tenant.id, hostel_id=other.id) == 0


# ---- Rooms ---------------------------------------------------------------


def test_an_empty_room_has_no_residents(db_session, tenant, hostel, room, beds):
    service = AllocationService(db_session)
    assert service.count_active_room_residents(tenant_id=tenant.id, room_id=room.id) == 0


def test_an_allocated_student_counts_as_a_room_resident(
    db_session, tenant, hostel, room, beds, student
):
    service = AllocationService(db_session)
    _allocate(service, tenant=tenant, hostel=hostel, room=room, bed=beds[0], student=student)
    db_session.flush()

    assert service.count_active_room_residents(tenant_id=tenant.id, room_id=room.id) == 1


def test_a_checked_out_student_no_longer_blocks_room_deletion(
    db_session, tenant, hostel, room, beds, student
):
    service = AllocationService(db_session)
    allocation = _allocate(
        service, tenant=tenant, hostel=hostel, room=room, bed=beds[0], student=student
    )
    db_session.flush()
    service.checkout_allocation(allocation.id)
    db_session.flush()

    assert service.count_active_room_residents(tenant_id=tenant.id, room_id=room.id) == 0


def test_residents_of_another_room_do_not_block_this_one(
    db_session, tenant, hostel, room, beds, student
):
    """An occupied room must not lock an empty one in the same hostel."""
    from modules.hostel.models import HostelRoom

    empty = HostelRoom(
        id="r-empty-1",
        tenant_id=tenant.id,
        hostel_id=hostel.id,
        room_number="102",
        capacity=4,
    )
    db_session.add(empty)
    db_session.flush()

    service = AllocationService(db_session)
    _allocate(service, tenant=tenant, hostel=hostel, room=room, bed=beds[0], student=student)
    db_session.flush()

    assert service.count_active_room_residents(tenant_id=tenant.id, room_id=room.id) == 1
    assert service.count_active_room_residents(tenant_id=tenant.id, room_id=empty.id) == 0
    # The hostel-level count still sees the resident either way.
    assert service.count_active_residents(tenant_id=tenant.id, hostel_id=hostel.id) == 1
