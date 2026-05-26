"""Pure-Python tests for HostelVisitor and HostelVisitorLog models."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from tests._model_loader import load_all_models  # noqa: E402

load_all_models()


def _build_visitor(**overrides):
    """Construct a HostelVisitor with sensible test defaults."""
    from modules.hostel.models import HostelVisitor

    defaults = {
        "id": "visitor-1",
        "tenant_id": "tenant-1",
        "phone": "9876543210",
        "name": "Mr. Rajendra Kumar",
        "relation_type": "father",
    }
    defaults.update(overrides)
    return HostelVisitor(**defaults)


def _build_visitor_log(**overrides):
    """Construct a HostelVisitorLog with sensible test defaults."""
    from modules.hostel.models import HostelVisitorLog

    defaults = {
        "id": "log-1",
        "tenant_id": "tenant-1",
        "visitor_id": "visitor-1",
        "student_id": "student-1",
        "hostel_id": "hostel-1",
        "room_id": "room-1",
        "check_in_at": datetime(2025, 5, 10, 14, 30, 0),
        "purpose": "General Visit",
    }
    defaults.update(overrides)
    return HostelVisitorLog(**defaults)


# ---------- HostelVisitor tests ----------

def test_visitor_creation():
    """Test creating a HostelVisitor."""
    visitor = _build_visitor()
    assert visitor.id == "visitor-1"
    assert visitor.tenant_id == "tenant-1"
    assert visitor.phone == "9876543210"
    assert visitor.name == "Mr. Rajendra Kumar"
    assert visitor.relation_type == "father"


def test_visitor_to_dict():
    """Test HostelVisitor.to_dict() serialization."""
    visitor = _build_visitor()
    data = visitor.to_dict()

    assert data["id"] == "visitor-1"
    assert data["tenant_id"] == "tenant-1"
    assert data["phone"] == "9876543210"
    assert data["name"] == "Mr. Rajendra Kumar"
    assert data["relation_type"] == "father"


def test_visitor_relation_type_optional():
    """relation_type may be None for unknown relations."""
    visitor = _build_visitor(relation_type=None)
    assert visitor.relation_type is None


def test_visitor_relation_constants():
    """RELATION_* class constants expose the supported values."""
    from modules.hostel.models import HostelVisitor

    assert HostelVisitor.RELATION_FATHER == "father"
    assert HostelVisitor.RELATION_MOTHER == "mother"
    assert HostelVisitor.RELATION_SIBLING == "sibling"
    assert HostelVisitor.RELATION_GUARDIAN == "guardian"
    assert HostelVisitor.RELATION_OTHER == "other"
    assert set(HostelVisitor.RELATION_VALUES) == {
        "father",
        "mother",
        "sibling",
        "guardian",
        "other",
    }


def test_visitor_tenancy_isolation():
    """Same phone across different tenants creates separate visitor records."""
    v1 = _build_visitor(id="v-a", tenant_id="tenant-1")
    v2 = _build_visitor(id="v-b", tenant_id="tenant-2")

    assert v1.tenant_id != v2.tenant_id
    assert v1.phone == v2.phone  # Same phone, different tenants is allowed


# ---------- HostelVisitorLog tests ----------

def test_visitor_log_creation():
    """Test creating a HostelVisitorLog."""
    log = _build_visitor_log()
    assert log.id == "log-1"
    assert log.tenant_id == "tenant-1"
    assert log.visitor_id == "visitor-1"
    assert log.student_id == "student-1"
    assert log.hostel_id == "hostel-1"
    assert log.room_id == "room-1"
    assert log.check_in_at == datetime(2025, 5, 10, 14, 30, 0)
    assert log.check_out_at is None
    assert log.purpose == "General Visit"
    assert log.deleted_at is None


def test_visitor_log_is_currently_inside():
    """is_currently_inside is True when check_out_at is None."""
    log = _build_visitor_log()
    assert log.is_currently_inside is True


def test_visitor_log_is_currently_inside_false_after_checkout():
    """is_currently_inside is False after check_out_at is set."""
    log = _build_visitor_log(check_out_at=datetime(2025, 5, 10, 16, 0, 0))
    assert log.is_currently_inside is False


def test_visitor_log_is_currently_inside_false_when_soft_deleted():
    """is_currently_inside is False for soft-deleted logs (audit safety)."""
    log = _build_visitor_log()
    log.deleted_at = datetime.utcnow()
    assert log.is_currently_inside is False


def test_visitor_log_to_dict():
    """Test HostelVisitorLog.to_dict() with all fields populated."""
    check_in = datetime(2025, 5, 10, 14, 30, 0)
    check_out = datetime(2025, 5, 10, 16, 0, 0)
    log = _build_visitor_log(check_in_at=check_in, check_out_at=check_out)

    data = log.to_dict()
    assert data["id"] == "log-1"
    assert data["visitor_id"] == "visitor-1"
    assert data["student_id"] == "student-1"
    assert data["hostel_id"] == "hostel-1"
    assert data["room_id"] == "room-1"
    assert data["check_in_at"] == check_in.isoformat()
    assert data["check_out_at"] == check_out.isoformat()
    assert data["purpose"] == "General Visit"
    assert data["deleted_at"] is None


def test_visitor_log_to_dict_handles_open_log():
    """to_dict() returns None for unset check_out_at (open log)."""
    log = _build_visitor_log()
    data = log.to_dict()
    assert data["check_out_at"] is None
    assert data["deleted_at"] is None


def test_visitor_log_room_id_optional():
    """room_id may be None if visitor isn't tied to a specific room."""
    log = _build_visitor_log(room_id=None)
    assert log.room_id is None
    data = log.to_dict()
    assert data["room_id"] is None


def test_visitor_log_relationships_defined():
    """visitor, student, hostel, room relationships are declared."""
    from modules.hostel.models import HostelVisitorLog

    assert hasattr(HostelVisitorLog, "visitor")
    assert hasattr(HostelVisitorLog, "student")
    assert hasattr(HostelVisitorLog, "hostel")
    assert hasattr(HostelVisitorLog, "room")
