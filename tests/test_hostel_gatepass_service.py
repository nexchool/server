"""Tests for GatepassService — gatepass state machine + audit trail.

Verifies state transitions, audit logging, and queries against real
PostgreSQL (with savepoint rollback).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest


def _future(hours: int) -> datetime:
    """Helper: a datetime `hours` hours in the future (UTC)."""
    return datetime.utcnow() + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

def test_create_gatepass_happy_path(db_session, tenant, hostel, student):
    """Student creates a gatepass request — defaults to status=pending."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )

    assert gp.id is not None
    assert gp.status == "pending"
    assert gp.type == "night_out"
    assert gp.parent_phone == "9876543210"


def test_create_gatepass_writes_audit_log(db_session, tenant, hostel, student):
    """Creating a gatepass appends an audit entry with actor=student."""
    from modules.hostel.services.gatepass_service import GatepassService
    from modules.hostel.models import HostelGatepassAudit

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="day_out",
        departure_datetime=_future(2),
        expected_return_datetime=_future(8),
        reason="Coaching",
        parent_phone="9876543210",
    )

    audits = (
        db_session.query(HostelGatepassAudit)
        .filter(HostelGatepassAudit.gatepass_id == gp.id)
        .all()
    )
    assert len(audits) == 1
    assert audits[0].action == "created"
    assert audits[0].actor_type == "student"
    assert audits[0].actor_id == student.id


def test_create_gatepass_blocks_if_active_one_exists(
    db_session, tenant, hostel, student
):
    """Cannot create a second gatepass while one is pending/approved/active."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )

    with pytest.raises(ValueError, match="active gatepass"):
        service.create_gatepass(
            tenant_id=tenant.id,
            student_id=student.id,
            hostel_id=hostel.id,
            gatepass_type="day_out",
            departure_datetime=_future(2),
            expected_return_datetime=_future(6),
            reason="Other",
            parent_phone="9876543210",
        )


def test_create_gatepass_rejects_invalid_type(db_session, tenant, hostel, student):
    """Only TYPE_VALUES are allowed."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    with pytest.raises(ValueError, match="Invalid gatepass type"):
        service.create_gatepass(
            tenant_id=tenant.id,
            student_id=student.id,
            hostel_id=hostel.id,
            gatepass_type="weekly_out",
            departure_datetime=_future(2),
            expected_return_datetime=_future(8),
            reason="x",
            parent_phone="9876543210",
        )


def test_create_gatepass_rejects_return_before_departure(
    db_session, tenant, hostel, student
):
    """expected_return must be strictly after departure."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    with pytest.raises(ValueError, match="return.*after.*departure"):
        service.create_gatepass(
            tenant_id=tenant.id,
            student_id=student.id,
            hostel_id=hostel.id,
            gatepass_type="day_out",
            departure_datetime=_future(10),
            expected_return_datetime=_future(5),  # before departure
            reason="x",
            parent_phone="9876543210",
        )


# ---------------------------------------------------------------------------
# Approve / reject
# ---------------------------------------------------------------------------

def test_approve_gatepass(db_session, tenant, hostel, student):
    """approve_gatepass moves pending -> approved and records approver."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )

    approved = service.approve_gatepass(gp.id, actor_user_id="warden-1")
    assert approved.status == "approved"
    assert approved.approved_at is not None
    assert approved.approved_by_user_id == "warden-1"


def test_approve_gatepass_blocks_non_pending(db_session, tenant, hostel, student):
    """Cannot approve a gatepass not in pending state."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )
    service.approve_gatepass(gp.id, actor_user_id="warden-1")

    with pytest.raises(ValueError, match="cannot transition"):
        service.approve_gatepass(gp.id, actor_user_id="warden-1")


def test_reject_gatepass(db_session, tenant, hostel, student):
    """reject_gatepass moves pending -> rejected with notes."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )

    rejected = service.reject_gatepass(
        gp.id, actor_user_id="warden-1", reason="Parent not reachable"
    )
    assert rejected.status == "rejected"
    assert "Parent not reachable" in (rejected.notes or "")


# ---------------------------------------------------------------------------
# Checkout / checkin
# ---------------------------------------------------------------------------

def test_mark_checkout_moves_approved_to_active(db_session, tenant, hostel, student):
    """mark_checkout: approved -> active, sets actual_out_at."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )
    service.approve_gatepass(gp.id, actor_user_id="warden-1")

    active = service.mark_checkout(gp.id, actor_user_id="gatekeeper-1")
    assert active.status == "active"
    assert active.actual_out_at is not None


def test_mark_checkout_blocks_pending(db_session, tenant, hostel, student):
    """Cannot checkout a gatepass that hasn't been approved yet."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )

    with pytest.raises(ValueError, match="cannot transition"):
        service.mark_checkout(gp.id, actor_user_id="gatekeeper-1")


def test_mark_checkin_closes_active(db_session, tenant, hostel, student):
    """mark_checkin: active -> closed, sets actual_in_at."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )
    service.approve_gatepass(gp.id, actor_user_id="warden-1")
    service.mark_checkout(gp.id, actor_user_id="gatekeeper-1")

    closed = service.mark_checkin(gp.id, actor_user_id="gatekeeper-1")
    assert closed.status == "closed"
    assert closed.actual_in_at is not None


def test_mark_checkin_closes_overdue(db_session, tenant, hostel, student):
    """A late-returning student can still be checked in (overdue -> closed)."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )
    service.approve_gatepass(gp.id, actor_user_id="warden-1")
    service.mark_checkout(gp.id, actor_user_id="gatekeeper-1")
    service.mark_overdue(gp.id)

    closed = service.mark_checkin(gp.id, actor_user_id="gatekeeper-1")
    assert closed.status == "closed"


# ---------------------------------------------------------------------------
# Overdue
# ---------------------------------------------------------------------------

def test_mark_overdue_only_for_active(db_session, tenant, hostel, student):
    """Only active gatepasses can be marked overdue."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )
    # status=pending, cannot mark overdue.
    with pytest.raises(ValueError, match="cannot transition"):
        service.mark_overdue(gp.id)


def test_find_overdue_returns_active_past_return_plus_grace(
    db_session, tenant, hostel, student
):
    """find_overdue_gatepasses returns active gatepasses past expected return + grace."""
    from modules.hostel.services.gatepass_service import GatepassService
    from modules.hostel.models import HostelGatepass

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(-10),  # already departed
        expected_return_datetime=_future(-2),  # 2 hours overdue
        reason="Home",
        parent_phone="9876543210",
    )
    service.approve_gatepass(gp.id, actor_user_id="warden-1")
    service.mark_checkout(gp.id, actor_user_id="gatekeeper-1")
    # Status is now 'active' with past expected_return_datetime.

    # 30-min grace period: -2 hours past, definitely overdue.
    overdue = service.find_overdue_gatepasses(grace_period_minutes=30)
    overdue_ids = {g.id for g in overdue}
    assert gp.id in overdue_ids


def test_find_overdue_respects_grace_period(db_session, tenant, hostel, student):
    """Within grace period, gatepass is NOT overdue."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    # expected return 10 min ago — within 30 min grace.
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=datetime.utcnow() - timedelta(hours=5),
        expected_return_datetime=datetime.utcnow() - timedelta(minutes=10),
        reason="Home",
        parent_phone="9876543210",
    )
    service.approve_gatepass(gp.id, actor_user_id="warden-1")
    service.mark_checkout(gp.id, actor_user_id="gatekeeper-1")

    overdue = service.find_overdue_gatepasses(grace_period_minutes=30)
    overdue_ids = {g.id for g in overdue}
    assert gp.id not in overdue_ids


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def test_full_lifecycle_writes_complete_audit_trail(
    db_session, tenant, hostel, student
):
    """Every state change appends an audit row in order."""
    from modules.hostel.services.gatepass_service import GatepassService
    from modules.hostel.models import HostelGatepassAudit

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )
    service.approve_gatepass(gp.id, actor_user_id="warden-1")
    service.mark_checkout(gp.id, actor_user_id="gatekeeper-1")
    service.mark_checkin(gp.id, actor_user_id="gatekeeper-1")

    audits = (
        db_session.query(HostelGatepassAudit)
        .filter(HostelGatepassAudit.gatepass_id == gp.id)
        .order_by(HostelGatepassAudit.created_at)
        .all()
    )
    actions = [a.action for a in audits]
    assert actions == ["created", "approved", "checkout", "checkin"]


# ---------------------------------------------------------------------------
# Listing / filtering
# ---------------------------------------------------------------------------

def test_list_gatepasses_filter_by_status(db_session, tenant, hostel, student, student2):
    """Filter by status returns only that status."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    gp1 = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )
    gp2 = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        gatepass_type="day_out",
        departure_datetime=_future(2),
        expected_return_datetime=_future(6),
        reason="Coaching",
        parent_phone="9876543211",
    )
    service.approve_gatepass(gp2.id, actor_user_id="warden-1")

    pending = service.list_gatepasses(tenant_id=tenant.id, status="pending")
    assert {g.id for g in pending} == {gp1.id}
    approved = service.list_gatepasses(tenant_id=tenant.id, status="approved")
    assert {g.id for g in approved} == {gp2.id}


def test_list_gatepasses_filter_by_student(
    db_session, tenant, hostel, student, student2
):
    """Filter by student narrows to their gatepasses only."""
    from modules.hostel.services.gatepass_service import GatepassService

    service = GatepassService(db_session)
    gp1 = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=_future(10),
        expected_return_datetime=_future(20),
        reason="Home",
        parent_phone="9876543210",
    )
    service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        gatepass_type="day_out",
        departure_datetime=_future(2),
        expected_return_datetime=_future(6),
        reason="Coaching",
        parent_phone="9876543211",
    )

    rows = service.list_gatepasses(tenant_id=tenant.id, student_id=student.id)
    assert {g.id for g in rows} == {gp1.id}
