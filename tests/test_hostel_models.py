"""Pure-Python tests for hostel models."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from tests._model_loader import load_all_models  # noqa: E402

load_all_models()


def test_hostel_creation():
    """Test creating a Hostel instance."""
    from modules.hostel.models import Hostel

    hostel = Hostel(
        id="hostel-1",
        tenant_id="tenant-1",
        name="Boys Hostel A",
        warden_name="John Doe",
        warden_phone="9876543210",
        address="123 Campus Road",
        capacity=50,
        status="active",
    )

    assert hostel.id == "hostel-1"
    assert hostel.tenant_id == "tenant-1"
    assert hostel.name == "Boys Hostel A"
    assert hostel.warden_name == "John Doe"
    assert hostel.warden_phone == "9876543210"
    assert hostel.address == "123 Campus Road"
    assert hostel.capacity == 50
    assert hostel.status == "active"
    assert hostel.deleted_at is None


def test_hostel_to_dict():
    """Test Hostel.to_dict() serialization."""
    from modules.hostel.models import Hostel

    hostel = Hostel(
        id="hostel-1",
        tenant_id="tenant-1",
        name="Girls Hostel B",
        warden_name="Jane Smith",
        warden_phone="9876543211",
        address="456 Campus Road",
        capacity=75,
        status="active",
    )

    data = hostel.to_dict()

    assert data["id"] == "hostel-1"
    assert data["name"] == "Girls Hostel B"
    assert data["warden_name"] == "Jane Smith"
    assert data["warden_phone"] == "9876543211"
    assert data["capacity"] == 75
    assert data["status"] == "active"
    assert data["deleted_at"] is None
    assert "created_at" in data
    assert "updated_at" in data


def test_hostel_soft_delete():
    """Test soft delete support on Hostel."""
    from modules.hostel.models import Hostel

    hostel = Hostel(
        id="hostel-1",
        tenant_id="tenant-1",
        name="Test Hostel",
        capacity=50,
        status="active",
    )

    assert hostel.deleted_at is None

    # Simulate soft delete
    hostel.deleted_at = datetime.utcnow()
    assert hostel.deleted_at is not None


def test_hostel_room_creation():
    """Test creating a HostelRoom instance."""
    from modules.hostel.models import HostelRoom

    room = HostelRoom(
        id="room-1",
        tenant_id="tenant-1",
        hostel_id="hostel-1",
        room_number="101",
        capacity=4,
        status="active",
    )

    assert room.id == "room-1"
    assert room.tenant_id == "tenant-1"
    assert room.hostel_id == "hostel-1"
    assert room.room_number == "101"
    assert room.capacity == 4
    assert room.status == "active"
    assert room.deleted_at is None


def test_hostel_room_to_dict():
    """Test HostelRoom.to_dict() serialization."""
    from modules.hostel.models import HostelRoom

    room = HostelRoom(
        id="room-1",
        tenant_id="tenant-1",
        hostel_id="hostel-1",
        room_number="202",
        capacity=3,
        status="active",
    )

    data = room.to_dict()

    assert data["id"] == "room-1"
    assert data["hostel_id"] == "hostel-1"
    assert data["room_number"] == "202"
    assert data["capacity"] == 3
    assert data["status"] == "active"
    assert data["deleted_at"] is None
    assert "created_at" in data
    assert "updated_at" in data


def test_hostel_room_soft_delete():
    """Test soft delete support on HostelRoom."""
    from modules.hostel.models import HostelRoom

    room = HostelRoom(
        id="room-1",
        tenant_id="tenant-1",
        hostel_id="hostel-1",
        room_number="101",
        capacity=4,
        status="active",
    )

    assert room.deleted_at is None

    # Simulate soft delete
    room.deleted_at = datetime.utcnow()
    assert room.deleted_at is not None


def test_hostel_bed_creation():
    """Test creating a HostelBed instance."""
    from modules.hostel.models import HostelBed

    bed = HostelBed(
        id="bed-1",
        tenant_id="tenant-1",
        room_id="room-1",
        bed_number="A1",
        is_allocated=False,
        status="active",
    )

    assert bed.id == "bed-1"
    assert bed.tenant_id == "tenant-1"
    assert bed.room_id == "room-1"
    assert bed.bed_number == "A1"
    assert bed.is_allocated is False
    assert bed.allocated_to_student_id is None
    assert bed.status == "active"
    assert bed.deleted_at is None


def test_hostel_bed_allocated():
    """Test allocating a bed to a student."""
    from modules.hostel.models import HostelBed

    bed = HostelBed(
        id="bed-1",
        tenant_id="tenant-1",
        room_id="room-1",
        bed_number="B2",
        is_allocated=True,
        allocated_to_student_id="student-123",
        status="active",
    )

    assert bed.is_allocated is True
    assert bed.allocated_to_student_id == "student-123"


def test_hostel_bed_to_dict():
    """Test HostelBed.to_dict() serialization."""
    from modules.hostel.models import HostelBed

    bed = HostelBed(
        id="bed-1",
        tenant_id="tenant-1",
        room_id="room-1",
        bed_number="C3",
        is_allocated=True,
        allocated_to_student_id="student-456",
        status="active",
    )

    data = bed.to_dict()

    assert data["id"] == "bed-1"
    assert data["room_id"] == "room-1"
    assert data["bed_number"] == "C3"
    assert data["is_allocated"] is True
    assert data["allocated_to_student_id"] == "student-456"
    assert data["status"] == "active"
    assert data["deleted_at"] is None
    assert "created_at" in data
    assert "updated_at" in data


def test_hostel_bed_soft_delete():
    """Test soft delete support on HostelBed."""
    from modules.hostel.models import HostelBed

    bed = HostelBed(
        id="bed-1",
        tenant_id="tenant-1",
        room_id="room-1",
        bed_number="D4",
        is_allocated=False,
        status="active",
    )

    assert bed.deleted_at is None

    # Simulate soft delete
    bed.deleted_at = datetime.utcnow()
    assert bed.deleted_at is not None


def test_hostel_room_relationship():
    """Test relationship between Hostel and HostelRoom."""
    from modules.hostel.models import Hostel, HostelRoom

    hostel = Hostel(
        id="hostel-1",
        tenant_id="tenant-1",
        name="Test Hostel",
        capacity=50,
        status="active",
    )

    room = HostelRoom(
        id="room-1",
        tenant_id="tenant-1",
        hostel_id="hostel-1",
        room_number="101",
        capacity=4,
        status="active",
    )

    # Manually set relationship for testing
    room.hostel = hostel

    assert room.hostel.name == "Test Hostel"
    assert room.hostel.id == "hostel-1"


def test_hostel_room_bed_relationship():
    """Test relationship between HostelRoom and HostelBed."""
    from modules.hostel.models import HostelRoom, HostelBed

    room = HostelRoom(
        id="room-1",
        tenant_id="tenant-1",
        hostel_id="hostel-1",
        room_number="101",
        capacity=4,
        status="active",
    )

    bed = HostelBed(
        id="bed-1",
        tenant_id="tenant-1",
        room_id="room-1",
        bed_number="A1",
        is_allocated=False,
        status="active",
    )

    # Manually set relationship for testing
    bed.room = room

    assert bed.room.room_number == "101"
    assert bed.room.id == "room-1"


def test_hostel_bed_student_relationship():
    """Test relationship between HostelBed and Student."""
    from modules.hostel.models import HostelBed

    bed = HostelBed(
        id="bed-1",
        tenant_id="tenant-1",
        room_id="room-1",
        bed_number="B2",
        is_allocated=True,
        allocated_to_student_id="student-789",
        status="active",
    )

    assert bed.allocated_to_student_id == "student-789"


def test_hostel_default_status():
    """Test default status value for Hostel."""
    from modules.hostel.models import Hostel

    hostel = Hostel(
        id="hostel-1",
        tenant_id="tenant-1",
        name="Test Hostel",
        capacity=50,
    )

    assert hostel.status == "active"


def test_hostel_room_default_status():
    """Test default status value for HostelRoom."""
    from modules.hostel.models import HostelRoom

    room = HostelRoom(
        id="room-1",
        tenant_id="tenant-1",
        hostel_id="hostel-1",
        room_number="101",
        capacity=4,
    )

    assert room.status == "active"


def test_hostel_bed_default_values():
    """Test default values for HostelBed."""
    from modules.hostel.models import HostelBed

    bed = HostelBed(
        id="bed-1",
        tenant_id="tenant-1",
        room_id="room-1",
        bed_number="A1",
    )

    assert bed.is_allocated is False
    assert bed.allocated_to_student_id is None
    assert bed.status == "active"


def test_hostel_tenancy_isolation():
    """Test that models properly support tenant isolation."""
    from modules.hostel.models import Hostel, HostelRoom, HostelBed

    # Tenant 1
    hostel_t1 = Hostel(
        id="hostel-t1",
        tenant_id="tenant-1",
        name="Hostel T1",
        capacity=50,
        status="active",
    )

    # Tenant 2
    hostel_t2 = Hostel(
        id="hostel-t2",
        tenant_id="tenant-2",
        name="Hostel T2",
        capacity=50,
        status="active",
    )

    assert hostel_t1.tenant_id == "tenant-1"
    assert hostel_t2.tenant_id == "tenant-2"
    assert hostel_t1.tenant_id != hostel_t2.tenant_id

    # Verify rooms maintain tenancy
    room_t1 = HostelRoom(
        id="room-t1",
        tenant_id="tenant-1",
        hostel_id="hostel-t1",
        room_number="101",
        capacity=4,
        status="active",
    )

    room_t2 = HostelRoom(
        id="room-t2",
        tenant_id="tenant-2",
        hostel_id="hostel-t2",
        room_number="101",
        capacity=4,
        status="active",
    )

    assert room_t1.tenant_id == "tenant-1"
    assert room_t2.tenant_id == "tenant-2"

    # Verify beds maintain tenancy
    bed_t1 = HostelBed(
        id="bed-t1",
        tenant_id="tenant-1",
        room_id="room-t1",
        bed_number="A1",
        is_allocated=False,
        status="active",
    )

    bed_t2 = HostelBed(
        id="bed-t2",
        tenant_id="tenant-2",
        room_id="room-t2",
        bed_number="A1",
        is_allocated=False,
        status="active",
    )

    assert bed_t1.tenant_id == "tenant-1"
    assert bed_t2.tenant_id == "tenant-2"
