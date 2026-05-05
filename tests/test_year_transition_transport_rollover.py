"""
Unit tests for ``modules.transport.services_rollover``.

Covers:
  - happy path: clones fee plans + active enrollments for promoted students
  - graduated student (no is_current row in to_year) is skipped
  - student already has a transport enrollment in to_year (any status) is
    skipped to avoid duplicates
  - existing fee plan for the same route in to_year is reused
  - copy_fee_plans=False / copy_enrollments=False respect the flag
  - missing tenant
  - same from/to year rejected
  - unknown from_year / to_year
  - DB exception rolls back
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import modules.transport.services_rollover as tr  # noqa: E402

from tests._rollover_helpers import (  # noqa: E402
    install_fake_model,
    install_fake_session,
    row,
)


def _patch_tenant(monkeypatch, tenant="tenant-1"):
    monkeypatch.setattr(tr, "get_tenant_id", lambda: tenant)


def _enrollment(student_id, route_id="R1", bus_id="B1"):
    return row(
        id=f"ENR-{student_id}",
        student_id=student_id,
        route_id=route_id,
        bus_id=bus_id,
        pickup_point="Stop A",
        drop_point="Stop B",
        pickup_stop_id="S1",
        drop_stop_id="S2",
        monthly_fee=Decimal("500"),
        fee_cycle="monthly",
    )


def test_transport_happy_path(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, tr)

    fy = row(id="Y-2025", start_date=date(2025, 6, 1))
    ty = row(id="Y-2026", start_date=date(2026, 6, 1))
    install_fake_model(monkeypatch, tr, "AcademicYear", queue=[fy, ty])

    src_plans = [row(route_id="R1", amount=Decimal("500"), fee_cycle="monthly")]
    src_enrolls = [
        _enrollment("STU-PROMOTED"),
        _enrollment("STU-GRADUATED"),
    ]
    install_fake_model(
        monkeypatch, tr, "TransportFeePlan",
        queue=[
            src_plans,   # source plans
            [],          # existing target plans
        ],
    )
    install_fake_model(
        monkeypatch, tr, "TransportEnrollment",
        queue=[
            src_enrolls,        # active source enrollments
            [],                 # existing target enrollments
        ],
    )
    # Only STU-PROMOTED has an is_current row in to_year — STU-GRADUATED does not.
    install_fake_model(
        monkeypatch, tr, "StudentClassEnrollment",
        queue=[[row(student_id="STU-PROMOTED")]],
    )

    result = tr.rollover_transport("Y-2025", "Y-2026")

    assert result["success"] is True
    assert result["fee_plans_created"] == 1
    assert result["fee_plans_reused"] == 0
    assert result["enrollments_created"] == 1
    assert result["enrollments_skipped_graduated"] == 1
    assert result["enrollments_skipped_existing"] == 0
    # 1 fee plan + 1 enrollment.
    assert len(sess.added) == 2
    assert sess.commits == 1 and sess.rollbacks == 0

    new_plan, new_enroll = sess.added
    assert new_plan.route_id == "R1"
    assert new_plan.academic_year_id == "Y-2026"
    assert new_enroll.student_id == "STU-PROMOTED"
    assert new_enroll.academic_year_id == "Y-2026"
    assert new_enroll.start_date == date(2026, 6, 1)
    assert new_enroll.end_date is None
    assert new_enroll.student_fee_id is None  # not auto-linked


def test_existing_target_enrollment_blocks_clone(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, tr)

    fy = row(id="Y-2025", start_date=date(2025, 6, 1))
    ty = row(id="Y-2026", start_date=date(2026, 6, 1))
    install_fake_model(monkeypatch, tr, "AcademicYear", queue=[fy, ty])

    install_fake_model(monkeypatch, tr, "TransportFeePlan", queue=[[], []])
    install_fake_model(
        monkeypatch, tr, "TransportEnrollment",
        queue=[
            [_enrollment("STU-1")],
            [row(student_id="STU-1")],   # already has a row in to_year
        ],
    )
    install_fake_model(
        monkeypatch, tr, "StudentClassEnrollment",
        queue=[[row(student_id="STU-1")]],
    )

    result = tr.rollover_transport("Y-2025", "Y-2026")
    assert result["enrollments_created"] == 0
    assert result["enrollments_skipped_existing"] == 1
    assert sess.added == []


def test_existing_fee_plan_for_route_reused(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, tr)

    fy = row(id="Y-1", start_date=date(2025, 6, 1))
    ty = row(id="Y-2", start_date=date(2026, 6, 1))
    install_fake_model(monkeypatch, tr, "AcademicYear", queue=[fy, ty])

    install_fake_model(
        monkeypatch, tr, "TransportFeePlan",
        queue=[
            [row(route_id="R1", amount=Decimal("500"), fee_cycle="monthly")],
            [row(route_id="R1", amount=Decimal("700"), fee_cycle="monthly")],
        ],
    )
    install_fake_model(monkeypatch, tr, "TransportEnrollment", queue=[[], []])
    install_fake_model(monkeypatch, tr, "StudentClassEnrollment", queue=[[]])

    result = tr.rollover_transport("Y-1", "Y-2")
    assert result["fee_plans_created"] == 0
    assert result["fee_plans_reused"] == 1
    assert sess.added == []


def test_copy_fee_plans_disabled_skips_plans(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, tr)

    fy = row(id="Y-1", start_date=date(2025, 6, 1))
    ty = row(id="Y-2", start_date=date(2026, 6, 1))
    install_fake_model(monkeypatch, tr, "AcademicYear", queue=[fy, ty])

    # Plans queue is unused — pass empty.
    install_fake_model(monkeypatch, tr, "TransportFeePlan", queue=[])
    install_fake_model(
        monkeypatch, tr, "TransportEnrollment",
        queue=[[_enrollment("STU-1")], []],
    )
    install_fake_model(
        monkeypatch, tr, "StudentClassEnrollment",
        queue=[[row(student_id="STU-1")]],
    )

    result = tr.rollover_transport("Y-1", "Y-2", copy_fee_plans=False)
    assert result["fee_plans_created"] == 0
    assert result["enrollments_created"] == 1
    # Only the enrollment, no fee plan.
    assert len(sess.added) == 1


def test_copy_enrollments_disabled_skips_enrollments(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, tr)

    fy = row(id="Y-1", start_date=date(2025, 6, 1))
    ty = row(id="Y-2", start_date=date(2026, 6, 1))
    install_fake_model(monkeypatch, tr, "AcademicYear", queue=[fy, ty])

    install_fake_model(
        monkeypatch, tr, "TransportFeePlan",
        queue=[
            [row(route_id="R1", amount=Decimal("100"), fee_cycle="monthly")],
            [],
        ],
    )
    # Enrollments queue unused.
    install_fake_model(monkeypatch, tr, "TransportEnrollment", queue=[])
    install_fake_model(monkeypatch, tr, "StudentClassEnrollment", queue=[])

    result = tr.rollover_transport("Y-1", "Y-2", copy_enrollments=False)
    assert result["fee_plans_created"] == 1
    assert result["enrollments_created"] == 0
    assert len(sess.added) == 1


def test_transport_same_year_rejected(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, tr)
    result = tr.rollover_transport("Y", "Y")
    assert result["success"] is False


def test_transport_unknown_from_year(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, tr)

    install_fake_model(monkeypatch, tr, "AcademicYear", queue=[None, row(id="Y-2")])
    result = tr.rollover_transport("Y-1", "Y-2")
    assert result["success"] is False
    assert "from_year_id" in result["error"]


def test_transport_unknown_to_year(monkeypatch):
    _patch_tenant(monkeypatch)
    install_fake_session(monkeypatch, tr)

    install_fake_model(monkeypatch, tr, "AcademicYear", queue=[row(id="Y-1"), None])
    result = tr.rollover_transport("Y-1", "Y-2")
    assert result["success"] is False
    assert "to_year_id" in result["error"]


def test_transport_requires_tenant(monkeypatch):
    monkeypatch.setattr(tr, "get_tenant_id", lambda: None)
    install_fake_session(monkeypatch, tr)
    result = tr.rollover_transport("Y-1", "Y-2")
    assert result == {"success": False, "error": "Tenant context is required"}


def test_transport_db_exception_rolls_back(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, tr, raise_on_commit=True)

    fy = row(id="Y-1", start_date=date(2025, 6, 1))
    ty = row(id="Y-2", start_date=date(2026, 6, 1))
    install_fake_model(monkeypatch, tr, "AcademicYear", queue=[fy, ty])

    install_fake_model(
        monkeypatch, tr, "TransportFeePlan",
        queue=[[row(route_id="R", amount=Decimal("100"), fee_cycle="monthly")], []],
    )
    install_fake_model(monkeypatch, tr, "TransportEnrollment", queue=[[], []])
    install_fake_model(monkeypatch, tr, "StudentClassEnrollment", queue=[[]])

    result = tr.rollover_transport("Y-1", "Y-2")
    assert result["success"] is False
    assert sess.rollbacks == 1


def test_to_year_with_no_start_date_falls_back_to_today(monkeypatch):
    _patch_tenant(monkeypatch)
    sess = install_fake_session(monkeypatch, tr)

    fy = row(id="Y-1", start_date=date(2025, 6, 1))
    ty = row(id="Y-2", start_date=None)   # no start date
    install_fake_model(monkeypatch, tr, "AcademicYear", queue=[fy, ty])

    install_fake_model(monkeypatch, tr, "TransportFeePlan", queue=[[], []])
    install_fake_model(
        monkeypatch, tr, "TransportEnrollment",
        queue=[[_enrollment("STU-1")], []],
    )
    install_fake_model(
        monkeypatch, tr, "StudentClassEnrollment",
        queue=[[row(student_id="STU-1")]],
    )
    fixed_today = date(2099, 1, 1)
    monkeypatch.setattr(tr, "_today", lambda: fixed_today)

    result = tr.rollover_transport("Y-1", "Y-2")
    assert result["enrollments_created"] == 1
    assert sess.added[0].start_date == fixed_today
