"""A hostel that still holds students must not be deletable.

DELETE /api/hostel/hostels/:id only stamps deleted_at. Nothing downstream
filters allocations by their hostel's deleted_at, so deleting an occupied
hostel would leave its residents allocated to beds in a hostel that no longer
exists. The route refuses with 409 instead — the same rule delete_bed already
applies to a single bed.

These cover the count the route asks for; the route turns a non-zero count
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
