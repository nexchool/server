"""End-to-end hostel workflow test.

Drives the full lifecycle through the service layer against a real
PostgreSQL database (via the conftest fixtures):

    add room/bed -> allocate student -> create gatepass -> approve
        -> gatekeeper checkout -> gatekeeper checkin -> close

And verifies:
    - Bed.is_allocated flips true on allocate, false on checkout.
    - The partial unique index uq_hostel_allocations_bed_active is
      respected (a second concurrent allocation fails).
    - Gatepass audit trail is complete and in order.
    - One-gatepass-per-student invariant.
    - Overdue detection (Celery job) flips status -> overdue.
    - Visitor lifecycle (in -> out) is tracked alongside the rest.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest


def test_complete_hostel_lifecycle(
    db_session, tenant, hostel, room, beds, student, student2
):
    """Allocate, gatepass, checkout, checkin — full happy path."""
    from modules.hostel.models import HostelAllocation, HostelGatepassAudit
    from modules.hostel.services import (
        AllocationService,
        GatepassService,
        VisitorService,
    )

    alloc_service = AllocationService(db_session)
    gp_service = GatepassService(db_session)
    visitor_service = VisitorService(db_session)

    # ----- 1. Allocate student to bed -----
    bed = beds[0]
    assert bed.is_allocated is False

    allocation = alloc_service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=bed.id,
        check_in_at=datetime(2025, 1, 15, 9, 0, 0),
    )
    db_session.flush()
    db_session.refresh(bed)
    assert allocation.status == "active"
    assert bed.is_allocated is True
    assert bed.allocated_to_student_id == student.id

    # Another student CAN'T take the same bed while the allocation is active.
    with pytest.raises(ValueError, match="Bed already occupied"):
        alloc_service.create_allocation(
            tenant_id=tenant.id,
            student_id=student2.id,
            hostel_id=hostel.id,
            room_id=room.id,
            bed_id=bed.id,
            check_in_at=datetime.utcnow(),
        )

    # ----- 2. Student requests a gatepass -----
    gatepass = gp_service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=datetime.utcnow() + timedelta(hours=2),
        expected_return_datetime=datetime.utcnow() + timedelta(hours=12),
        reason="Visiting parents",
        parent_phone="+91-9876543210",
    )
    assert gatepass.status == "pending"

    # Can't open a second gatepass in parallel.
    with pytest.raises(ValueError, match="active gatepass"):
        gp_service.create_gatepass(
            tenant_id=tenant.id,
            student_id=student.id,
            hostel_id=hostel.id,
            gatepass_type="day_out",
            departure_datetime=datetime.utcnow() + timedelta(hours=1),
            expected_return_datetime=datetime.utcnow() + timedelta(hours=6),
            reason="Coaching",
            parent_phone="+91-9876543210",
        )

    # ----- 3. Warden approves (after parent call) -----
    gp_service.approve_gatepass(gatepass.id, actor_user_id="warden-1")
    db_session.refresh(gatepass)
    assert gatepass.status == "approved"
    assert gatepass.approved_at is not None
    assert gatepass.approved_by_user_id == "warden-1"

    # ----- 4. A visitor checks in for this student -----
    visit = visitor_service.check_in(
        tenant_id=tenant.id,
        phone="+91-9876543210",
        name="Mr. Rajendra Kumar",
        relation_type="father",
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="Pre-trip checkup",
    )
    assert visit.check_out_at is None
    assert visit.is_currently_inside is True

    visitor_service.check_out(visit.id)
    db_session.refresh(visit)
    assert visit.check_out_at is not None

    # ----- 5. Gatekeeper marks departure -----
    gp_service.mark_checkout(gatepass.id, actor_user_id="gatekeeper-1")
    db_session.refresh(gatepass)
    assert gatepass.status == "active"
    assert gatepass.actual_out_at is not None

    # ----- 6. Gatekeeper marks return -----
    gp_service.mark_checkin(gatepass.id, actor_user_id="gatekeeper-1")
    db_session.refresh(gatepass)
    assert gatepass.status == "closed"
    assert gatepass.actual_in_at is not None

    # ----- 7. Allocation continues until manual checkout -----
    db_session.refresh(allocation)
    assert allocation.status == "active"

    alloc_service.checkout_allocation(allocation.id)
    db_session.refresh(allocation)
    db_session.refresh(bed)
    assert allocation.status == "completed"
    assert allocation.check_out_at is not None
    assert bed.is_allocated is False
    assert bed.allocated_to_student_id is None

    # ----- 8. Audit trail completeness -----
    audit_rows = (
        db_session.query(HostelGatepassAudit)
        .filter(HostelGatepassAudit.gatepass_id == gatepass.id)
        .order_by(HostelGatepassAudit.created_at)
        .all()
    )
    assert [a.action for a in audit_rows] == [
        "created",
        "approved",
        "checkout",
        "checkin",
    ]
    assert audit_rows[0].actor_type == "student"
    assert audit_rows[1].actor_type == "warden"
    assert audit_rows[2].actor_type == "gatekeeper"
    assert audit_rows[3].actor_type == "gatekeeper"


def test_workflow_overdue_path(
    db_session, tenant, hostel, room, beds, student
):
    """If the student doesn't return by expected_return + grace, the
    Celery beat task flips the gatepass to overdue; the warden can
    still close it via mark_checkin afterwards."""
    from modules.hostel.services import AllocationService, GatepassService
    from tasks.hostel import mark_overdue_gatepasses_task

    alloc_service = AllocationService(db_session)
    gp_service = GatepassService(db_session)

    alloc_service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[0].id,
        check_in_at=datetime.utcnow(),
    )

    gp = gp_service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        # Departed yesterday, expected back 2 hours ago — way past grace.
        departure_datetime=datetime.utcnow() - timedelta(hours=10),
        expected_return_datetime=datetime.utcnow() - timedelta(hours=2),
        reason="Home",
        parent_phone="+91-9876543210",
    )
    gp_service.approve_gatepass(gp.id, actor_user_id="warden-1")
    gp_service.mark_checkout(gp.id, actor_user_id="gatekeeper-1")
    gp_id = gp.id  # keep id, the row will be re-fetched after task commits

    # Celery task flips the status.
    mark_overdue_gatepasses_task.run(grace_period_minutes=30)

    from modules.hostel.models import HostelGatepass

    fresh = db_session.query(HostelGatepass).filter_by(id=gp_id).one()
    assert fresh.status == "overdue"

    # Late return: gatekeeper can still close it.
    gp_service.mark_checkin(fresh.id, actor_user_id="gatekeeper-1")
    db_session.refresh(fresh)
    assert fresh.status == "closed"
    assert fresh.actual_in_at is not None


def test_workflow_rejection_path(db_session, tenant, hostel, student):
    """Warden rejects a gatepass — student frees up to request another."""
    from modules.hostel.services import GatepassService

    service = GatepassService(db_session)

    first = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=datetime.utcnow() + timedelta(hours=2),
        expected_return_datetime=datetime.utcnow() + timedelta(hours=12),
        reason="Home",
        parent_phone="+91-9876543210",
    )
    service.reject_gatepass(
        first.id,
        actor_user_id="warden-1",
        reason="Pending fees",
    )
    db_session.refresh(first)
    assert first.status == "rejected"

    # Now the student can submit a new request.
    second = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="day_out",
        departure_datetime=datetime.utcnow() + timedelta(hours=1),
        expected_return_datetime=datetime.utcnow() + timedelta(hours=6),
        reason="Coaching",
        parent_phone="+91-9876543210",
    )
    assert second.status == "pending"
    assert second.id != first.id
