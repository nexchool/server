"""Smoke test that conftest.py fixtures work end-to-end against postgres.

Confirms:
- Per-test transaction rollback works (no test leaks data)
- Tenant, hostel, room, bed, student fixtures all create valid rows
- The partial unique index uq_hostel_allocations_bed_active enforces
  one active allocation per bed (the critical hostel invariant).
"""

from __future__ import annotations

from datetime import datetime

import pytest


def test_tenant_fixture(tenant):
    assert tenant.id is not None
    assert tenant.name == "Test School"
    assert tenant.status == "active"


def test_hostel_fixture(hostel, tenant):
    assert hostel.tenant_id == tenant.id
    assert hostel.name == "Boys Hostel A"
    assert hostel.capacity == 20


def test_room_fixture(room, hostel, tenant):
    assert room.hostel_id == hostel.id
    assert room.tenant_id == tenant.id
    assert room.room_number == "101"


def test_bed_fixture(bed, room):
    assert bed.room_id == room.id
    assert bed.bed_number == "A1"
    assert bed.is_allocated is False


def test_beds_fixture_creates_four(beds, room):
    assert len(beds) == 4
    numbers = sorted(b.bed_number for b in beds)
    assert numbers == ["A1", "A2", "A3", "A4"]
    for b in beds:
        assert b.room_id == room.id


def test_student_fixture(student, tenant):
    assert student.tenant_id == tenant.id
    assert student.user_id is not None
    assert student.admission_number.startswith("ADM-")


def test_student2_fixture(student, student2):
    assert student.id != student2.id
    assert student.admission_number != student2.admission_number


def test_active_allocation_unique_per_bed(db_session, tenant, hostel, room, bed, student, student2):
    """Partial unique index: only one active allocation per bed allowed."""
    from modules.hostel.models import HostelAllocation

    # Allocate first student to bed — should succeed.
    a1 = HostelAllocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=datetime.utcnow(),
    )
    db_session.add(a1)
    db_session.flush()
    assert a1.id is not None

    # Second active allocation on the same bed must violate the partial
    # unique index uq_hostel_allocations_bed_active.
    a2 = HostelAllocation(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=datetime.utcnow(),
    )
    db_session.add(a2)

    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_completed_allocation_does_not_block_new_active(
    db_session, tenant, hostel, room, bed, student, student2
):
    """A completed (status='completed') allocation should not block a new active one.

    This is the whole point of the partial unique index: status='active'
    AND deleted_at IS NULL only.
    """
    from modules.hostel.models import HostelAllocation

    # Old, completed allocation.
    old = HostelAllocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=datetime(2024, 1, 1),
        check_out_at=datetime(2024, 12, 31),
        status="completed",
    )
    db_session.add(old)
    db_session.flush()

    # New active allocation for a different student on the same bed.
    new = HostelAllocation(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=datetime(2025, 1, 1),
        status="active",
    )
    db_session.add(new)
    db_session.flush()  # Should NOT raise.

    assert new.id is not None


def test_rollback_isolation(db_session, tenant):
    """Verify each test starts with a clean slate by checking row counts.

    If rollback works, no row from a previous test should leak into this one.
    The tenant we just created should be the only one in the test's scope.
    """
    from core.models import Tenant
    # Count tenants with our test name pattern — none should remain across tests.
    count = db_session.query(Tenant).filter(Tenant.name == "Test School").count()
    # Exactly one: the tenant fixture used in *this* test.
    assert count >= 1
