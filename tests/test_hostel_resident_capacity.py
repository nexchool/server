"""A hostel cannot house more students than its capacity.

Residents ≤ beds ≤ room capacity ≤ hostel capacity already follows from the
other guards when every row was written under them. This is the direct check
on the number that matters to the warden — students actually living there —
so a hostel built before those guards, or one edited around them, still
cannot take one student more than it holds, and cannot be shrunk under the
students already in it.
"""

from __future__ import annotations

import pytest

from core.school_time import utc_now
from modules.hostel.services import AllocationService, FacilityService


def _allocate(service, *, tenant, hostel, room, bed, student):
    return service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=utc_now(),
    )


def test_a_full_hostel_takes_no_more_students(
    db_session, tenant, hostel, room, beds, student, student2
):
    hostel.capacity = 1
    db_session.flush()
    service = AllocationService(db_session)
    _allocate(service, tenant=tenant, hostel=hostel, room=room, bed=beds[0], student=student)
    db_session.flush()

    with pytest.raises(ValueError, match="full"):
        _allocate(service, tenant=tenant, hostel=hostel, room=room, bed=beds[1], student=student2)


def test_a_checked_out_student_frees_their_place(
    db_session, tenant, hostel, room, beds, student, student2
):
    hostel.capacity = 1
    db_session.flush()
    service = AllocationService(db_session)
    first = _allocate(service, tenant=tenant, hostel=hostel, room=room, bed=beds[0], student=student)
    db_session.flush()
    service.checkout_allocation(first.id)
    db_session.flush()

    _allocate(service, tenant=tenant, hostel=hostel, room=room, bed=beds[1], student=student2)


def test_a_hostel_cannot_shrink_below_its_residents(
    db_session, tenant, hostel, room, beds, student, student2
):
    service = AllocationService(db_session)
    for resident, bed in ((student, beds[0]), (student2, beds[1])):
        _allocate(service, tenant=tenant, hostel=hostel, room=room, bed=bed, student=resident)
    db_session.flush()

    facilities = FacilityService(db_session)
    with pytest.raises(ValueError, match="2 students"):
        facilities.assert_hostel_capacity_holds_residents(
            tenant_id=tenant.id, hostel=hostel, new_capacity=1
        )
    facilities.assert_hostel_capacity_holds_residents(
        tenant_id=tenant.id, hostel=hostel, new_capacity=2
    )
