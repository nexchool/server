"""Tests for VisitorService and ReportService (postgres-backed)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest


# ===========================================================================
# VisitorService
# ===========================================================================

def test_check_in_creates_visitor_and_log(db_session, tenant, hostel, room, student):
    """First-time visitor: creates HostelVisitor + HostelVisitorLog."""
    from modules.hostel.services.visitor_service import VisitorService

    service = VisitorService(db_session)
    log = service.check_in(
        tenant_id=tenant.id,
        phone="9876543210",
        name="Mr. Rajendra Kumar",
        relation_type="father",
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="General Visit",
    )

    assert log.id is not None
    assert log.check_in_at is not None
    assert log.check_out_at is None
    assert log.purpose == "General Visit"

    # Visitor record was created.
    from modules.hostel.models import HostelVisitor
    visitor = db_session.get(HostelVisitor, log.visitor_id)
    assert visitor is not None
    assert visitor.phone == "9876543210"
    assert visitor.name == "Mr. Rajendra Kumar"


def test_check_in_reuses_existing_visitor(db_session, tenant, hostel, room, student):
    """Repeat phone: reuses existing HostelVisitor row, creates new log."""
    from modules.hostel.services.visitor_service import VisitorService
    from modules.hostel.models import HostelVisitor

    service = VisitorService(db_session)
    log1 = service.check_in(
        tenant_id=tenant.id,
        phone="9876543210",
        name="Mr. Rajendra Kumar",
        relation_type="father",
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="Visit 1",
    )
    service.check_out(log1.id)

    log2 = service.check_in(
        tenant_id=tenant.id,
        phone="9876543210",
        name="Mr. Rajendra Kumar",
        relation_type="father",
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="Visit 2",
    )

    assert log1.visitor_id == log2.visitor_id
    assert log1.id != log2.id

    count = (
        db_session.query(HostelVisitor)
        .filter(HostelVisitor.tenant_id == tenant.id, HostelVisitor.phone == "9876543210")
        .count()
    )
    assert count == 1


def test_check_in_updates_visitor_name_relation(db_session, tenant, hostel, room, student):
    """If a repeat visitor checks in with updated info, the visitor row reflects it."""
    from modules.hostel.services.visitor_service import VisitorService
    from modules.hostel.models import HostelVisitor

    service = VisitorService(db_session)
    log = service.check_in(
        tenant_id=tenant.id,
        phone="9876543210",
        name="Rajendra",
        relation_type="father",
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="Visit",
    )
    visitor_id = log.visitor_id
    service.check_out(log.id)

    service.check_in(
        tenant_id=tenant.id,
        phone="9876543210",
        name="Mr. Rajendra Kumar",
        relation_type="guardian",
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="Visit 2",
    )

    visitor = db_session.get(HostelVisitor, visitor_id)
    assert visitor.name == "Mr. Rajendra Kumar"
    assert visitor.relation_type == "guardian"


def test_check_out_sets_timestamp(db_session, tenant, hostel, room, student):
    """check_out sets check_out_at on the log."""
    from modules.hostel.services.visitor_service import VisitorService

    service = VisitorService(db_session)
    log = service.check_in(
        tenant_id=tenant.id,
        phone="9876543210",
        name="A",
        relation_type="father",
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="x",
    )
    closed = service.check_out(log.id)
    assert closed.check_out_at is not None


def test_check_out_idempotent_raises(db_session, tenant, hostel, room, student):
    """Cannot check out twice — second call raises."""
    from modules.hostel.services.visitor_service import VisitorService

    service = VisitorService(db_session)
    log = service.check_in(
        tenant_id=tenant.id,
        phone="9876543210",
        name="A",
        relation_type="father",
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="x",
    )
    service.check_out(log.id)
    with pytest.raises(ValueError, match="already checked out"):
        service.check_out(log.id)


def test_check_out_unknown_log_raises(db_session):
    from modules.hostel.services.visitor_service import VisitorService

    service = VisitorService(db_session)
    with pytest.raises(ValueError, match="not found"):
        service.check_out("nonexistent-log")


def test_get_currently_inside(db_session, tenant, hostel, room, student, student2):
    """currently_inside returns only open logs for the tenant."""
    from modules.hostel.services.visitor_service import VisitorService

    service = VisitorService(db_session)
    open_log = service.check_in(
        tenant_id=tenant.id,
        phone="9876543210",
        name="A",
        relation_type="father",
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="x",
    )
    closed = service.check_in(
        tenant_id=tenant.id,
        phone="9876543211",
        name="B",
        relation_type="mother",
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="x",
    )
    service.check_out(closed.id)

    inside = service.get_currently_inside(tenant_id=tenant.id)
    inside_ids = {l.id for l in inside}
    assert open_log.id in inside_ids
    assert closed.id not in inside_ids


def test_get_currently_inside_filter_by_hostel(
    db_session, tenant, hostel, room, student
):
    """Filter to a specific hostel."""
    from modules.hostel.services.visitor_service import VisitorService

    service = VisitorService(db_session)
    service.check_in(
        tenant_id=tenant.id,
        phone="9876543210",
        name="A",
        relation_type="father",
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="x",
    )

    assert len(service.get_currently_inside(tenant_id=tenant.id, hostel_id=hostel.id)) == 1
    assert service.get_currently_inside(tenant_id=tenant.id, hostel_id="other") == []


def test_search_repeat_visitor_by_phone_prefix(db_session, tenant, hostel, room, student):
    """search_visitors finds known repeat-visitor profiles by phone prefix."""
    from modules.hostel.services.visitor_service import VisitorService

    service = VisitorService(db_session)
    service.check_in(
        tenant_id=tenant.id,
        phone="9876543210",
        name="Rajendra",
        relation_type="father",
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="x",
    )

    matches = service.search_visitors(tenant_id=tenant.id, phone_prefix="987654")
    assert len(matches) == 1
    assert matches[0].phone == "9876543210"

    none = service.search_visitors(tenant_id=tenant.id, phone_prefix="0000")
    assert none == []


def test_list_visitor_logs_filter_by_student(
    db_session, tenant, hostel, room, student, student2
):
    """Filter visitor logs to a specific student."""
    from modules.hostel.services.visitor_service import VisitorService

    service = VisitorService(db_session)
    log1 = service.check_in(
        tenant_id=tenant.id,
        phone="9876543210",
        name="A",
        relation_type="father",
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="x",
    )
    service.check_in(
        tenant_id=tenant.id,
        phone="9876543211",
        name="B",
        relation_type="mother",
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        purpose="x",
    )

    rows = service.list_visitor_logs(tenant_id=tenant.id, student_id=student.id)
    assert {l.id for l in rows} == {log1.id}


# ===========================================================================
# ReportService
# ===========================================================================

def test_occupancy_stats_per_hostel(
    db_session, tenant, hostel, room, beds, student, student2
):
    """occupancy_stats reports per-hostel occupancy with vacant counts."""
    from modules.hostel.services.allocation_service import AllocationService
    from modules.hostel.services.report_service import ReportService

    alloc_service = AllocationService(db_session)
    alloc_service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[0].id,
        check_in_at=datetime.utcnow(),
    )
    alloc_service.create_allocation(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[1].id,
        check_in_at=datetime.utcnow(),
    )

    report = ReportService(db_session)
    stats = report.occupancy_stats(tenant_id=tenant.id)

    by_id = {h["hostel_id"]: h for h in stats}
    assert hostel.id in by_id
    row = by_id[hostel.id]
    assert row["hostel_name"] == "Boys Hostel A"
    assert row["active_allocations"] == 2
    # 4 beds in the room (from `beds` fixture); 2 occupied.
    assert row["total_beds"] == 4
    assert row["vacant_beds"] == 2
    assert row["occupancy_pct"] == 50.0


def test_occupancy_stats_handles_zero_beds(db_session, tenant, hostel):
    """If a hostel has 0 beds, occupancy_pct should be 0, not raise."""
    from modules.hostel.services.report_service import ReportService

    report = ReportService(db_session)
    stats = report.occupancy_stats(tenant_id=tenant.id)
    by_id = {h["hostel_id"]: h for h in stats}
    row = by_id[hostel.id]
    assert row["total_beds"] == 0
    assert row["active_allocations"] == 0
    assert row["occupancy_pct"] == 0.0


def test_overdue_alerts_lists_overdue_gatepasses(
    db_session, tenant, hostel, student
):
    """overdue_alerts returns gatepasses whose status='overdue'."""
    from modules.hostel.services.gatepass_service import GatepassService
    from modules.hostel.services.report_service import ReportService

    gp_service = GatepassService(db_session)
    gp = gp_service.create_gatepass(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        gatepass_type="night_out",
        departure_datetime=datetime.utcnow() - timedelta(hours=10),
        expected_return_datetime=datetime.utcnow() - timedelta(hours=2),
        reason="Home",
        parent_phone="9876543210",
    )
    gp_service.approve_gatepass(gp.id, actor_user_id="warden-1")
    gp_service.mark_checkout(gp.id, actor_user_id="gatekeeper-1")
    gp_service.mark_overdue(gp.id)

    report = ReportService(db_session)
    overdue = report.overdue_alerts(tenant_id=tenant.id)
    assert {g.id for g in overdue} == {gp.id}


def test_residents_csv_rows(
    db_session, tenant, hostel, room, beds, student, student2
):
    """residents_csv_rows yields one row per active allocation."""
    from modules.hostel.services.allocation_service import AllocationService
    from modules.hostel.services.report_service import ReportService

    alloc_service = AllocationService(db_session)
    alloc_service.create_allocation(
        tenant_id=tenant.id,
        student_id=student.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[0].id,
        check_in_at=datetime(2025, 1, 15),
    )
    alloc_service.create_allocation(
        tenant_id=tenant.id,
        student_id=student2.id,
        hostel_id=hostel.id,
        room_id=room.id,
        bed_id=beds[1].id,
        check_in_at=datetime(2025, 1, 16),
    )

    report = ReportService(db_session)
    rows = report.residents_csv_rows(tenant_id=tenant.id)

    assert len(rows) == 2
    headers = {"hostel_name", "room_number", "bed_number", "student_id", "check_in_date"}
    assert headers.issubset(rows[0].keys())
    assert rows[0]["hostel_name"] == "Boys Hostel A"
    assert rows[0]["room_number"] == "101"
