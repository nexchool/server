"""Tests for AllocationService — business logic for student → bed assignments.

Uses the postgres-backed fixtures from conftest.py so we exercise the real
unique-index behavior, FK relationships, and bed.is_allocated side effects.
"""

from __future__ import annotations

from datetime import datetime

import pytest


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
        check_in_at=datetime.utcnow(),
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
        check_in_at=datetime.utcnow(),
    )

    with pytest.raises(ValueError, match="Bed already occupied"):
        service.create_allocation(
            tenant_id=tenant.id,
            student_id=student2.id,
            hostel_id=hostel.id,
            room_id=room.id,
            bed_id=bed.id,
            check_in_at=datetime.utcnow(),
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
        check_in_at=datetime.utcnow(),
    )

    # Same student, different bed → still rejected.
    with pytest.raises(ValueError, match="Student already has active allocation"):
        service.create_allocation(
            tenant_id=tenant.id,
            student_id=student.id,
            hostel_id=hostel.id,
            room_id=room.id,
            bed_id=beds[1].id,
            check_in_at=datetime.utcnow(),
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
            check_in_at=datetime.utcnow(),
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
        check_in_at=datetime.utcnow(),
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
        check_in_at=datetime.utcnow(),
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
        check_in_at=datetime.utcnow(),
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
        check_in_at=datetime.utcnow(),
    )
    service.create_allocation(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[1].id,
        check_in_at=datetime.utcnow(),
    )

    rows = service.list_allocations(tenant_id=tenant.id)
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
        check_in_at=datetime.utcnow(),
    )
    service.create_allocation(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[1].id,
        check_in_at=datetime.utcnow(),
    )

    rows = service.list_allocations(tenant_id=tenant.id, student_id=student.id)
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
        check_in_at=datetime.utcnow(),
    )
    a2 = service.create_allocation(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[1].id,
        check_in_at=datetime.utcnow(),
    )
    service.checkout_allocation(a2.id)

    active = service.list_allocations(tenant_id=tenant.id, status="active")
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
        check_in_at=datetime.utcnow(),
    )

    rows = service.list_allocations(tenant_id=tenant.id, hostel_id=hostel.id)
    assert len(rows) == 1
    rows = service.list_allocations(tenant_id=tenant.id, hostel_id="other-hostel-id")
    assert rows == []
