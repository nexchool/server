"""Tests for AllocationService — business logic for student → bed assignments.

Uses the postgres-backed fixtures from conftest.py so we exercise the real
unique-index behavior, FK relationships, and bed.is_allocated side effects.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from core.school_time import utc_now


def test_create_allocation_happy_path(db_session, tenant, hostel, room, bed, student):
    """Allocating an unoccupied bed to a student without an active allocation succeeds."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    allocation = service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=datetime(2025, 1, 15, 9, 0, 0),
    )

    assert allocation.id is not None
    assert allocation.status == "active"
    assert allocation.check_in_at == datetime(2025, 1, 15, 9, 0, 0)
    assert allocation.check_out_at is None


def test_create_allocation_flips_bed_is_allocated(
    db_session, tenant, hostel, room, bed, student
):
    """Creating an allocation should mark bed.is_allocated=True and link student."""
    from modules.hostel.services.allocation_service import AllocationService

    assert bed.is_allocated is False
    service = AllocationService(db_session)
    service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=utc_now(),
    )
    db_session.refresh(bed)
    assert bed.is_allocated is True
    assert bed.allocated_to_student_id == student.id


def test_create_allocation_fails_when_bed_occupied(
    db_session, tenant, hostel, room, bed, student, student2
):
    """Allocating an already-occupied bed raises ValueError."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=utc_now(),
    )

    with pytest.raises(ValueError, match="Bed already occupied"):
        service.create_allocation(
            tenant_id=tenant.id,
            student_id=student2.id,
            hostel_id=hostel.id,
            room_id=room.id,
            bed_id=bed.id,
            check_in_at=utc_now(),
        )


def test_create_allocation_fails_when_student_already_allocated(
    db_session, tenant, hostel, room, beds, student
):
    """A student cannot have two active allocations simultaneously."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[0].id,
        check_in_at=utc_now(),
    )

    # Same student, different bed → still rejected.
    with pytest.raises(ValueError, match="Student already has active allocation"):
        service.create_allocation(
            tenant_id=tenant.id,
            student_id=student.id,
            hostel_id=hostel.id,
            room_id=room.id,
            bed_id=beds[1].id,
            check_in_at=utc_now(),
        )


def test_create_allocation_fails_when_bed_missing(
    db_session, tenant, hostel, room, student
):
    """Allocating a non-existent bed raises ValueError."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    with pytest.raises(ValueError, match="Bed .* not found"):
        service.create_allocation(
            tenant_id=tenant.id,
            student_id=student.id,
            hostel_id=hostel.id,
            room_id=room.id,
            bed_id="nonexistent-bed-id",
            check_in_at=utc_now(),
        )


def test_checkout_allocation_sets_check_out_and_status(
    db_session, tenant, hostel, room, bed, student
):
    """Checkout sets check_out_at, status='completed', and clears bed allocation."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    allocation = service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=datetime(2025, 1, 15),
    )

    closed = service.checkout_allocation(allocation.id)

    assert closed.status == "completed"
    assert closed.check_out_at is not None

    db_session.refresh(bed)
    assert bed.is_allocated is False
    assert bed.allocated_to_student_id is None


def test_checkout_allocation_unknown_id_raises(db_session):
    """Checking out a non-existent allocation raises ValueError."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    with pytest.raises(ValueError, match="Allocation .* not found"):
        service.checkout_allocation("does-not-exist")


def test_checkout_allocation_already_completed_raises(
    db_session, tenant, hostel, room, bed, student
):
    """Cannot checkout an already-completed allocation."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    a = service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=utc_now(),
    )
    service.checkout_allocation(a.id)

    with pytest.raises(ValueError, match="not active"):
        service.checkout_allocation(a.id)


def test_get_allocation_by_student_returns_active(
    db_session, tenant, hostel, room, bed, student
):
    """get_allocation_by_student returns the current active allocation."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    created = service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=utc_now(),
    )

    found = service.get_allocation_by_student(tenant_id=tenant.id, student_id=student.id)
    assert found is not None
    assert found.id == created.id


def test_get_allocation_by_student_returns_none_when_none(
    db_session, tenant, student
):
    """Returns None for a student with no allocations."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    assert service.get_allocation_by_student(tenant_id=tenant.id, student_id=student.id) is None


def test_get_allocation_by_student_ignores_completed(
    db_session, tenant, hostel, room, beds, student
):
    """A completed allocation should not be returned as 'current'."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    a = service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[0].id,
        check_in_at=utc_now(),
    )
    service.checkout_allocation(a.id)

    assert service.get_allocation_by_student(tenant_id=tenant.id, student_id=student.id) is None


def test_list_allocations_no_filters(db_session, tenant, hostel, room, beds, student, student2):
    """list_allocations returns every allocation for the tenant."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[0].id,
        check_in_at=utc_now(),
    )
    service.create_allocation(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[1].id,
        check_in_at=utc_now(),
    )

    rows = service.list_allocations(tenant_id=tenant.id)["items"]
    assert len(rows) == 2


def test_list_allocations_filter_by_student(
    db_session, tenant, hostel, room, beds, student, student2
):
    """Filter narrows to a single student."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    a1 = service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[0].id,
        check_in_at=utc_now(),
    )
    service.create_allocation(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[1].id,
        check_in_at=utc_now(),
    )

    rows = service.list_allocations(tenant_id=tenant.id, student_id=student.id)["items"]
    assert len(rows) == 1
    assert rows[0].id == a1.id


def test_list_allocations_filter_by_status_active(
    db_session, tenant, hostel, room, beds, student, student2
):
    """status='active' filter excludes completed allocations."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    a1 = service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[0].id,
        check_in_at=utc_now(),
    )
    a2 = service.create_allocation(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[1].id,
        check_in_at=utc_now(),
    )
    service.checkout_allocation(a2.id)

    active = service.list_allocations(tenant_id=tenant.id, status="active")["items"]
    assert len(active) == 1
    assert active[0].id == a1.id


def test_list_allocations_filter_by_hostel(
    db_session, tenant, hostel, room, beds, student
):
    """hostel_id filter narrows to a specific hostel."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[0].id,
        check_in_at=utc_now(),
    )

    rows = service.list_allocations(tenant_id=tenant.id, hostel_id=hostel.id)["items"]
    assert len(rows) == 1
    rows = service.list_allocations(tenant_id=tenant.id, hostel_id="other-hostel-id")["items"]
    assert rows == []


# ---------------------------------------------------------------------------
# Move — one event, recorded as one
# ---------------------------------------------------------------------------

def _second_hostel(db_session, tenant, *, capacity: int):
    """A second hostel with one room of one bed, for moves between hostels."""
    import uuid
    from modules.hostel.models import Hostel, HostelBed, HostelRoom

    suffix = uuid.uuid4().hex[:10]
    other = Hostel(id=f"h-{suffix}", tenant_id=tenant.id, name="Girls Hostel B", capacity=capacity)
    db_session.add(other); db_session.flush()
    other_room = HostelRoom(id=f"r-{suffix}", tenant_id=tenant.id, hostel_id=other.id,
                            room_number="B101", floor="1st Floor", capacity=capacity)
    db_session.add(other_room); db_session.flush()
    other_beds = [HostelBed(tenant_id=tenant.id, room_id=other_room.id, bed_number=str(i + 1))
                  for i in range(capacity)]
    db_session.add_all(other_beds); db_session.flush()
    return other, other_room, other_beds


def _active_count(db_session, tenant, student) -> int:
    from modules.hostel.models import HostelAllocation
    return (
        db_session.query(HostelAllocation)
        .filter(HostelAllocation.tenant_id == tenant.id, HostelAllocation.student_id == student.id,
                HostelAllocation.status == HostelAllocation.STATUS_ACTIVE)
        .count()
    )


def test_a_move_closes_the_old_stay_as_moved_and_opens_the_new_one(
    db_session, tenant, hostel, room, beds, student
):
    from datetime import datetime, timezone
    from modules.hostel.models import HostelAllocation
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    first = service.create_allocation(tenant_id=tenant.id, student_id=student.id, hostel_id=hostel.id,
                                      room_id=room.id, bed_id=beds[0].id, check_in_at=utc_now())
    when = datetime(2026, 9, 13, 4, 30, tzinfo=timezone.utc)

    closed, opened = service.move_allocation(first.id, tenant_id=tenant.id, room_id=room.id,
                                             bed_id=beds[1].id, moved_at=when)

    assert closed is first
    assert closed.status == HostelAllocation.STATUS_MOVED
    assert closed.check_out_at == when
    assert opened.status == HostelAllocation.STATUS_ACTIVE
    assert opened.check_in_at == when
    assert (opened.student_id, opened.hostel_id, opened.room_id, opened.bed_id) == (
        student.id, hostel.id, room.id, beds[1].id)
    # The beds' denormalised flags followed the student.
    assert beds[0].is_allocated is False and beds[0].allocated_to_student_id is None
    assert beds[1].is_allocated is True and beds[1].allocated_to_student_id == student.id
    # Exactly one active stay, and it is the new one.
    assert _active_count(db_session, tenant, student) == 1
    assert service.get_allocation_by_student(tenant_id=tenant.id, student_id=student.id).id == opened.id


def test_a_move_to_an_occupied_bed_is_refused(db_session, tenant, hostel, room, beds, student, student2):
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    mine = service.create_allocation(tenant_id=tenant.id, student_id=student.id, hostel_id=hostel.id,
                                     room_id=room.id, bed_id=beds[0].id, check_in_at=utc_now())
    service.create_allocation(tenant_id=tenant.id, student_id=student2.id, hostel_id=hostel.id,
                              room_id=room.id, bed_id=beds[1].id, check_in_at=utc_now())
    with pytest.raises(ValueError, match="occupied"):
        service.move_allocation(mine.id, tenant_id=tenant.id, room_id=room.id, bed_id=beds[1].id)
    assert mine.status == "active" and mine.bed_id == beds[0].id


def test_moving_to_the_bed_already_held_is_refused(db_session, tenant, hostel, room, beds, student):
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    mine = service.create_allocation(tenant_id=tenant.id, student_id=student.id, hostel_id=hostel.id,
                                     room_id=room.id, bed_id=beds[0].id, check_in_at=utc_now())
    with pytest.raises(ValueError, match="already in that bed"):
        service.move_allocation(mine.id, tenant_id=tenant.id, room_id=room.id, bed_id=beds[0].id)


def test_only_an_active_stay_can_be_moved(db_session, tenant, hostel, room, beds, student):
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    mine = service.create_allocation(tenant_id=tenant.id, student_id=student.id, hostel_id=hostel.id,
                                     room_id=room.id, bed_id=beds[0].id, check_in_at=utc_now())
    service.checkout_allocation(mine.id)
    with pytest.raises(ValueError, match="not active"):
        service.move_allocation(mine.id, tenant_id=tenant.id, room_id=room.id, bed_id=beds[1].id)


def test_a_move_into_a_full_hostel_is_refused(db_session, tenant, hostel, room, beds, student, student2):
    """Between hostels the student does not yet hold a place, so a full
    destination refuses them — as a fresh allocation would."""
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    other, other_room, other_beds = _second_hostel(db_session, tenant, capacity=1)
    service.create_allocation(tenant_id=tenant.id, student_id=student2.id, hostel_id=other.id,
                              room_id=other_room.id, bed_id=other_beds[0].id, check_in_at=utc_now())
    mine = service.create_allocation(tenant_id=tenant.id, student_id=student.id, hostel_id=hostel.id,
                                     room_id=room.id, bed_id=beds[0].id, check_in_at=utc_now())
    # The only bed there is taken; the capacity guard fires before the bed check.
    with pytest.raises(ValueError, match="is full"):
        service.move_allocation(mine.id, tenant_id=tenant.id, room_id=other_room.id, bed_id=other_beds[0].id)


def test_a_move_between_hostels_takes_a_place_there_and_frees_one_here(
    db_session, tenant, hostel, room, beds, student
):
    from modules.hostel.services.allocation_service import AllocationService

    service = AllocationService(db_session)
    other, other_room, other_beds = _second_hostel(db_session, tenant, capacity=2)
    mine = service.create_allocation(tenant_id=tenant.id, student_id=student.id, hostel_id=hostel.id,
                                     room_id=room.id, bed_id=beds[0].id, check_in_at=utc_now())
    assert service.count_active_residents(tenant_id=tenant.id, hostel_id=hostel.id) == 1

    closed, opened = service.move_allocation(mine.id, tenant_id=tenant.id,
                                             room_id=other_room.id, bed_id=other_beds[1].id)

    assert opened.hostel_id == other.id and closed.status == "moved"
    assert service.count_active_residents(tenant_id=tenant.id, hostel_id=hostel.id) == 0
    assert service.count_active_residents(tenant_id=tenant.id, hostel_id=other.id) == 1
