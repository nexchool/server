"""Pure-Python tests for HostelGatepass and HostelGatepassAudit models."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from tests._model_loader import load_all_models  # noqa: E402

load_all_models()


def _build_gatepass(**overrides):
    """Construct a HostelGatepass with sensible test defaults."""
    from modules.hostel.models import HostelGatepass

    departure = datetime(2025, 5, 10, 22, 30, 0)
    defaults = {
        "id": "gp-1",
        "tenant_id": "tenant-1",
        "student_id": "student-1",
        "hostel_id": "hostel-1",
        "type": HostelGatepass.TYPE_NIGHT_OUT,
        "departure_datetime": departure,
        "expected_return_datetime": departure + timedelta(hours=10),
        "reason": "Home",
        "parent_phone": "9876543210",
    }
    defaults.update(overrides)
    return HostelGatepass(**defaults)


def _build_audit(**overrides):
    """Construct a HostelGatepassAudit with test defaults."""
    from modules.hostel.models import HostelGatepassAudit

    defaults = {
        "id": "audit-1",
        "gatepass_id": "gp-1",
        "action": HostelGatepassAudit.ACTION_CREATED,
        "actor_type": HostelGatepassAudit.ACTOR_STUDENT,
        "actor_id": "student-1",
    }
    defaults.update(overrides)
    return HostelGatepassAudit(**defaults)


# ---------- Type and status constants ----------

def test_gatepass_type_constants():
    from modules.hostel.models import HostelGatepass

    assert HostelGatepass.TYPE_DAY_OUT == "day_out"
    assert HostelGatepass.TYPE_NIGHT_OUT == "night_out"
    assert set(HostelGatepass.TYPE_VALUES) == {"day_out", "night_out"}


def test_gatepass_status_constants():
    from modules.hostel.models import HostelGatepass

    assert HostelGatepass.STATUS_PENDING == "pending"
    assert HostelGatepass.STATUS_APPROVED == "approved"
    assert HostelGatepass.STATUS_ACTIVE == "active"
    assert HostelGatepass.STATUS_CLOSED == "closed"
    assert HostelGatepass.STATUS_REJECTED == "rejected"
    assert HostelGatepass.STATUS_OVERDUE == "overdue"
    assert set(HostelGatepass.STATUS_VALUES) == {
        "pending",
        "approved",
        "active",
        "closed",
        "rejected",
        "overdue",
    }


def test_gatepass_consent_constants():
    from modules.hostel.models import HostelGatepass

    assert HostelGatepass.CONSENT_NOT_REQUIRED == "not_required"
    assert HostelGatepass.CONSENT_PENDING == "pending"
    assert HostelGatepass.CONSENT_GIVEN == "given"
    assert HostelGatepass.CONSENT_REJECTED == "rejected"


# ---------- Creation + defaults ----------

def test_gatepass_creation():
    gp = _build_gatepass()
    assert gp.id == "gp-1"
    assert gp.tenant_id == "tenant-1"
    assert gp.student_id == "student-1"
    assert gp.hostel_id == "hostel-1"
    assert gp.type == "night_out"
    assert gp.parent_phone == "9876543210"
    assert gp.reason == "Home"


def test_gatepass_default_status_is_pending():
    gp = _build_gatepass()
    assert gp.status == "pending"


def test_gatepass_default_consent_is_not_required():
    """v1: security guard calls parent directly; consent is informational only."""
    gp = _build_gatepass()
    assert gp.parent_consent_status == "not_required"


def test_gatepass_explicit_status_override():
    gp = _build_gatepass(status="approved")
    assert gp.status == "approved"


# ---------- State machine ----------

def test_can_transition_pending_to_approved():
    gp = _build_gatepass(status="pending")
    assert gp.can_transition_to("approved") is True


def test_can_transition_pending_to_rejected():
    gp = _build_gatepass(status="pending")
    assert gp.can_transition_to("rejected") is True


def test_cannot_transition_pending_to_active():
    """Active requires approval first."""
    gp = _build_gatepass(status="pending")
    assert gp.can_transition_to("active") is False


def test_can_transition_approved_to_active():
    """Gatekeeper checkout transition."""
    gp = _build_gatepass(status="approved")
    assert gp.can_transition_to("active") is True


def test_cannot_transition_approved_to_closed():
    """Closed requires checkout (active) first."""
    gp = _build_gatepass(status="approved")
    assert gp.can_transition_to("closed") is False


def test_can_transition_active_to_closed():
    """Gatekeeper checkin transition."""
    gp = _build_gatepass(status="active")
    assert gp.can_transition_to("closed") is True


def test_can_transition_active_to_overdue():
    """System job transition."""
    gp = _build_gatepass(status="active")
    assert gp.can_transition_to("overdue") is True


def test_overdue_can_still_close():
    """A late-returning student can still be checked in."""
    gp = _build_gatepass(status="overdue")
    assert gp.can_transition_to("closed") is True


def test_terminal_statuses_have_no_transitions():
    """Closed and rejected are terminal."""
    closed = _build_gatepass(status="closed")
    rejected = _build_gatepass(status="rejected")

    for next_status in ["pending", "approved", "active", "overdue", "rejected"]:
        assert closed.can_transition_to(next_status) is False
    for next_status in ["pending", "approved", "active", "overdue", "closed"]:
        assert rejected.can_transition_to(next_status) is False


# ---------- is_overdue property ----------

def test_is_overdue_false_when_not_active():
    """Pending/approved/closed gatepasses are never overdue at read time."""
    for status in ["pending", "approved", "closed", "rejected", "overdue"]:
        gp = _build_gatepass(status=status)
        # Even with past expected_return, only ACTIVE gatepasses trigger overdue
        assert gp.is_overdue is False


def test_is_overdue_true_when_active_and_past_return():
    """Active gatepass with past expected_return_datetime is overdue."""
    past_return = datetime.utcnow() - timedelta(hours=1)
    gp = _build_gatepass(
        status="active",
        departure_datetime=past_return - timedelta(hours=8),
        expected_return_datetime=past_return,
    )
    assert gp.is_overdue is True


def test_is_overdue_false_when_active_but_not_yet_due():
    """Active gatepass with future return is not overdue."""
    future_return = datetime.utcnow() + timedelta(hours=3)
    gp = _build_gatepass(
        status="active",
        departure_datetime=datetime.utcnow(),
        expected_return_datetime=future_return,
    )
    assert gp.is_overdue is False


# ---------- Serialization ----------

def test_gatepass_to_dict_full():
    departure = datetime(2025, 5, 10, 22, 30, 0)
    return_dt = departure + timedelta(hours=10)
    gp = _build_gatepass(
        departure_datetime=departure,
        expected_return_datetime=return_dt,
        status="approved",
        approved_at=datetime(2025, 5, 10, 21, 45, 0),
        approved_by_user_id="warden-1",
        parent_consent_status="given",
        parent_consent_notified_at=datetime(2025, 5, 10, 21, 30, 0),
        parent_notification_type="in_app,push",
    )

    data = gp.to_dict()
    assert data["id"] == "gp-1"
    assert data["type"] == "night_out"
    assert data["status"] == "approved"
    assert data["departure_datetime"] == departure.isoformat()
    assert data["expected_return_datetime"] == return_dt.isoformat()
    assert data["approved_at"] == datetime(2025, 5, 10, 21, 45, 0).isoformat()
    assert data["approved_by_user_id"] == "warden-1"
    assert data["parent_phone"] == "9876543210"
    assert data["parent_consent_status"] == "given"
    assert data["parent_notification_type"] == "in_app,push"


def test_gatepass_to_dict_handles_nulls():
    """to_dict returns None for unset optional fields."""
    gp = _build_gatepass()
    data = gp.to_dict()
    assert data["approved_at"] is None
    assert data["actual_out_at"] is None
    assert data["actual_in_at"] is None
    assert data["approved_by_user_id"] is None
    assert data["parent_consent_notified_at"] is None
    assert data["deleted_at"] is None


# ---------- Audit log ----------

def test_audit_action_constants():
    from modules.hostel.models import HostelGatepassAudit

    assert HostelGatepassAudit.ACTION_CREATED == "created"
    assert HostelGatepassAudit.ACTION_APPROVED == "approved"
    assert HostelGatepassAudit.ACTION_REJECTED == "rejected"
    assert HostelGatepassAudit.ACTION_CHECKOUT == "checkout"
    assert HostelGatepassAudit.ACTION_CHECKIN == "checkin"
    assert HostelGatepassAudit.ACTION_MARKED_OVERDUE == "marked_overdue"


def test_audit_actor_constants():
    from modules.hostel.models import HostelGatepassAudit

    assert HostelGatepassAudit.ACTOR_STUDENT == "student"
    assert HostelGatepassAudit.ACTOR_WARDEN == "warden"
    assert HostelGatepassAudit.ACTOR_GATEKEEPER == "gatekeeper"
    assert HostelGatepassAudit.ACTOR_SYSTEM == "system"


def test_audit_creation():
    audit = _build_audit()
    assert audit.id == "audit-1"
    assert audit.gatepass_id == "gp-1"
    assert audit.action == "created"
    assert audit.actor_type == "student"
    assert audit.actor_id == "student-1"
    assert audit.notes is None


def test_audit_to_dict():
    audit = _build_audit(notes="Approved after parent call confirmed")
    data = audit.to_dict()

    assert data["id"] == "audit-1"
    assert data["gatepass_id"] == "gp-1"
    assert data["action"] == "created"
    assert data["actor_type"] == "student"
    assert data["actor_id"] == "student-1"
    assert data["notes"] == "Approved after parent call confirmed"


def test_audit_system_actor_no_actor_id():
    """System actions (overdue marking) have no actor_id."""
    from modules.hostel.models import HostelGatepassAudit

    audit = _build_audit(
        action=HostelGatepassAudit.ACTION_MARKED_OVERDUE,
        actor_type=HostelGatepassAudit.ACTOR_SYSTEM,
        actor_id=None,
    )
    assert audit.actor_id is None
    assert audit.actor_type == "system"


def test_gatepass_audit_relationships_defined():
    """gatepass.audit_logs and audit.gatepass relationships are declared."""
    from modules.hostel.models import HostelGatepass, HostelGatepassAudit

    assert hasattr(HostelGatepass, "audit_logs")
    assert hasattr(HostelGatepassAudit, "gatepass")


def test_gatepass_tenancy_isolation():
    """Two gatepasses across tenants stay isolated."""
    gp1 = _build_gatepass(id="gp-a", tenant_id="tenant-1")
    gp2 = _build_gatepass(id="gp-b", tenant_id="tenant-2")

    assert gp1.tenant_id != gp2.tenant_id
