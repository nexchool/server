"""Tests for hostel Celery tasks.

The task body is exercised directly (calling .run() bypasses Celery
broker / serialization) against the real postgres test fixtures.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def test_mark_overdue_task_flips_active_to_overdue(
    db_session, tenant, hostel, student, student2
):
    """An active gatepass past expected return + grace becomes overdue."""
    from modules.hostel.services import GatepassService
    from tasks.hostel import mark_overdue_gatepasses_task

    service = GatepassService(db_session)
    # 1 hour past expected return, well beyond a 30 min grace window.
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=datetime.utcnow() - timedelta(hours=10),
        expected_return_datetime=datetime.utcnow() - timedelta(hours=1),
        reason="Home",
        parent_phone="9876543210",
    )
    service.approve_gatepass(gp.id, actor_user_id="warden-1")
    service.mark_checkout(gp.id, actor_user_id="gatekeeper-1")
    db_session.flush()
    assert gp.status == "active"

    # A second gatepass that is not yet overdue — must NOT be flipped.
    gp_fresh = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=datetime.utcnow() - timedelta(hours=1),
        expected_return_datetime=datetime.utcnow() + timedelta(hours=5),
        reason="Home",
        parent_phone="9876543211",
    )
    service.approve_gatepass(gp_fresh.id, actor_user_id="warden-1")
    service.mark_checkout(gp_fresh.id, actor_user_id="gatekeeper-1")

    result = mark_overdue_gatepasses_task.run(grace_period_minutes=30)
    db_session.refresh(gp)
    db_session.refresh(gp_fresh)

    assert gp.status == "overdue"
    assert gp_fresh.status == "active"
    assert result["marked_overdue"] >= 1


def test_mark_overdue_task_idempotent(db_session, tenant, hostel, student):
    """Running the task twice on the same gatepass produces no duplicate effect."""
    from modules.hostel.services import GatepassService
    from tasks.hostel import mark_overdue_gatepasses_task

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=datetime.utcnow() - timedelta(hours=10),
        expected_return_datetime=datetime.utcnow() - timedelta(hours=1),
        reason="Home",
        parent_phone="9876543210",
    )
    service.approve_gatepass(gp.id, actor_user_id="warden-1")
    service.mark_checkout(gp.id, actor_user_id="gatekeeper-1")

    first = mark_overdue_gatepasses_task.run(grace_period_minutes=30)
    second = mark_overdue_gatepasses_task.run(grace_period_minutes=30)

    db_session.refresh(gp)
    assert gp.status == "overdue"
    # First run flips; second run finds nothing because find_overdue
    # only returns active rows.
    assert first["marked_overdue"] >= 1
    assert second["marked_overdue"] == 0


def test_mark_overdue_writes_audit_row(db_session, tenant, hostel, student):
    """Marking overdue appends a system-actor audit row."""
    from modules.hostel.models import HostelGatepassAudit
    from modules.hostel.services import GatepassService
    from tasks.hostel import mark_overdue_gatepasses_task

    service = GatepassService(db_session)
    gp = service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=datetime.utcnow() - timedelta(hours=10),
        expected_return_datetime=datetime.utcnow() - timedelta(hours=1),
        reason="Home",
        parent_phone="9876543210",
    )
    service.approve_gatepass(gp.id, actor_user_id="warden-1")
    service.mark_checkout(gp.id, actor_user_id="gatekeeper-1")

    mark_overdue_gatepasses_task.run(grace_period_minutes=30)

    audits = (
        db_session.query(HostelGatepassAudit)
        .filter(HostelGatepassAudit.gatepass_id == gp.id)
        .all()
    )
    actions = [a.action for a in audits]
    assert "marked_overdue" in actions
    overdue_audit = next(a for a in audits if a.action == "marked_overdue")
    assert overdue_audit.actor_type == "system"
    assert overdue_audit.actor_id is None


def _create_academic_year(db_session, tenant, name="2026-2027"):
    """Create an AcademicYear row needed by the rollover FK constraint."""
    from datetime import date
    from modules.academics.academic_year.models import AcademicYear
    import uuid

    ay = AcademicYear(
        id=f"ay-{uuid.uuid4().hex[:8]}",
        tenant_id=tenant.id,
        name=name,
        start_date=date(2026, 6, 1),
        end_date=date(2027, 3, 31),
    )
    db_session.add(ay)
    db_session.flush()
    return ay


def test_rollover_academic_year_closes_active_allocations(
    db_session, tenant, hostel, room, beds, student, student2
):
    """rollover_academic_year_task closes every active allocation for the tenant."""
    from modules.hostel.models import HostelAllocation
    from modules.hostel.services import AllocationService
    from tasks.hostel import rollover_academic_year_task

    new_year = _create_academic_year(db_session, tenant)

    alloc_service = AllocationService(db_session)
    a1 = alloc_service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[0].id,
        check_in_at=datetime(2025, 1, 1),
    )
    a2 = alloc_service.create_allocation(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[1].id,
        check_in_at=datetime(2025, 1, 2),
    )
    a1_id, a2_id = a1.id, a2.id

    result = rollover_academic_year_task.run(
        new_academic_year_id=new_year.id,
        tenant_id=tenant.id,
    )

    # Re-fetch since the task commits and expires objects in the session.
    fresh_a1 = db_session.query(HostelAllocation).filter_by(id=a1_id).one()
    fresh_a2 = db_session.query(HostelAllocation).filter_by(id=a2_id).one()
    assert fresh_a1.status == "completed"
    assert fresh_a2.status == "completed"
    assert fresh_a1.academic_year_id == new_year.id
    assert fresh_a2.academic_year_id == new_year.id
    assert result["closed_allocations"] == 2


def test_rollover_skips_already_completed(
    db_session, tenant, hostel, room, beds, student
):
    """Already-completed allocations are skipped, not double-checked-out."""
    from modules.hostel.models import HostelAllocation
    from modules.hostel.services import AllocationService
    from tasks.hostel import rollover_academic_year_task

    new_year = _create_academic_year(db_session, tenant)

    alloc_service = AllocationService(db_session)
    a = alloc_service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[0].id,
        check_in_at=datetime(2025, 1, 1),
    )
    alloc_service.checkout_allocation(a.id)
    a_id = a.id
    original_check_out_at = a.check_out_at

    # Task should not touch this completed row.
    result = rollover_academic_year_task.run(
        new_academic_year_id=new_year.id,
        tenant_id=tenant.id,
    )

    fresh_a = db_session.query(HostelAllocation).filter_by(id=a_id).one()
    assert fresh_a.check_out_at == original_check_out_at
    assert result["closed_allocations"] == 0
