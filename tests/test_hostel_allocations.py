"""Pure-Python tests for HostelAllocation model."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from tests._model_loader import load_all_models  # noqa: E402

load_all_models()


def _build_allocation(**overrides):
    """Construct a HostelAllocation with sensible test defaults."""
    from modules.hostel.models import HostelAllocation

    defaults = {
        "id": "alloc-1",
        "tenant_id": "tenant-1",
        "student_id": "student-1",
        "hostel_id": "hostel-1",
        "room_id": "room-1",
        "bed_id": "bed-1",
        "check_in_at": datetime(2025, 1, 15, 9, 0, 0),
    }
    defaults.update(overrides)
    return HostelAllocation(**defaults)


def test_allocation_creation():
    """Test creating a HostelAllocation with all core fields."""
    allocation = _build_allocation(
        academic_year_id="ay-2025",
        notes="Initial allocation",
    )

    assert allocation.id == "alloc-1"
    assert allocation.tenant_id == "tenant-1"
    assert allocation.student_id == "student-1"
    assert allocation.hostel_id == "hostel-1"
    assert allocation.room_id == "room-1"
    assert allocation.bed_id == "bed-1"
    assert allocation.academic_year_id == "ay-2025"
    assert allocation.check_in_at == datetime(2025, 1, 15, 9, 0, 0)
    assert allocation.check_out_at is None
    assert allocation.notes == "Initial allocation"
    assert allocation.deleted_at is None


def test_allocation_default_status():
    """HostelAllocation should default to status='active'."""
    allocation = _build_allocation()
    assert allocation.status == "active"


def test_allocation_explicit_status():
    """HostelAllocation accepts explicit status override."""
    allocation = _build_allocation(status="completed")
    assert allocation.status == "completed"


def test_allocation_is_active_property():
    """is_active is True only when status='active' and check_out_at is None."""
    active = _build_allocation()
    assert active.is_active is True

    checked_out = _build_allocation(
        check_out_at=datetime(2025, 6, 30, 12, 0, 0),
        status="completed",
    )
    assert checked_out.is_active is False


def test_allocation_is_active_false_when_status_completed():
    """Status='completed' makes is_active False even with no checkout time."""
    allocation = _build_allocation(status="completed")
    assert allocation.is_active is False


def test_allocation_is_active_false_when_soft_deleted():
    """Soft-deleted allocations should not be active."""
    allocation = _build_allocation()
    allocation.deleted_at = datetime.utcnow()
    assert allocation.is_active is False


def test_allocation_to_dict_round_trip():
    """to_dict() returns serializable fields with ISO timestamps."""
    check_in = datetime(2025, 1, 15, 9, 0, 0)
    check_out = datetime(2025, 6, 30, 12, 0, 0)
    allocation = _build_allocation(
        check_in_at=check_in,
        check_out_at=check_out,
        status="completed",
        academic_year_id="ay-2025",
        notes="Year-end checkout",
    )

    data = allocation.to_dict()

    assert data["id"] == "alloc-1"
    assert data["tenant_id"] == "tenant-1"
    assert data["student_id"] == "student-1"
    assert data["hostel_id"] == "hostel-1"
    assert data["room_id"] == "room-1"
    assert data["bed_id"] == "bed-1"
    assert data["academic_year_id"] == "ay-2025"
    assert data["check_in_at"] == check_in.isoformat()
    assert data["check_out_at"] == check_out.isoformat()
    assert data["status"] == "completed"
    assert data["notes"] == "Year-end checkout"
    assert data["deleted_at"] is None


def test_allocation_to_dict_handles_nullable_fields():
    """to_dict() returns None for unset optional timestamps and fields."""
    allocation = _build_allocation()
    data = allocation.to_dict()

    assert data["check_out_at"] is None
    assert data["academic_year_id"] is None
    assert data["notes"] is None
    assert data["deleted_at"] is None


def test_allocation_soft_delete():
    """Soft delete by setting deleted_at; record remains, status preserved."""
    allocation = _build_allocation()
    assert allocation.deleted_at is None

    deleted_at = datetime.utcnow()
    allocation.deleted_at = deleted_at

    assert allocation.deleted_at == deleted_at
    # Status remains 'active' even after soft delete; is_active uses deleted_at
    assert allocation.status == "active"
    assert allocation.is_active is False


def test_allocation_checkout_flow():
    """Simulate checkout: set check_out_at + status='completed'."""
    allocation = _build_allocation()
    assert allocation.is_active is True

    allocation.check_out_at = datetime(2025, 6, 30, 12, 0, 0)
    allocation.status = "completed"

    assert allocation.is_active is False
    assert allocation.check_out_at == datetime(2025, 6, 30, 12, 0, 0)


def test_allocation_status_values_constant():
    """STATUS_VALUES constant exposes all valid statuses for callers."""
    from modules.hostel.models import HostelAllocation

    assert HostelAllocation.STATUS_ACTIVE == "active"
    assert HostelAllocation.STATUS_COMPLETED == "completed"
    assert HostelAllocation.STATUS_MOVED == "moved"
    assert set(HostelAllocation.STATUS_VALUES) == {"active", "completed", "moved"}


def test_allocation_tenancy_isolation():
    """Two allocations across tenants stay isolated (TenantBaseModel)."""
    alloc_a = _build_allocation(id="alloc-a", tenant_id="tenant-1")
    alloc_b = _build_allocation(id="alloc-b", tenant_id="tenant-2")

    assert alloc_a.tenant_id != alloc_b.tenant_id
    assert alloc_a.id != alloc_b.id


def test_allocation_relationships_defined():
    """student, hostel, room, bed relationships are declared on the model."""
    from modules.hostel.models import HostelAllocation

    # SQLAlchemy attaches relationships to the mapper; checking the class
    # attribute confirms they're declared.
    assert hasattr(HostelAllocation, "student")
    assert hasattr(HostelAllocation, "hostel")
    assert hasattr(HostelAllocation, "room")
    assert hasattr(HostelAllocation, "bed")
