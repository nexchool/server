"""
Transport rollover: clone TransportFeePlan rows and active TransportEnrollment
rows from one academic year to another.

Rules:
  - Fee plans are unique on (tenant_id, route_id, academic_year_id) so we
    upsert per route — existing target rows are reused, not modified.
  - An enrollment is only carried over if the student has an `is_current=true`
    StudentClassEnrollment in to_year (i.e. they were promoted, not graduated)
    AND they do not already have a transport enrollment in to_year.
  - The new transport enrollment copies bus / route / stops / monthly_fee /
    fee_cycle from the source. `student_fee_id` is left null — admin generates
    fees via the existing finance flow.
  - The whole batch runs in a single transaction.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from core.database import db
from core.tenant import get_tenant_id
from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import StudentClassEnrollment

from .models import TransportEnrollment, TransportFeePlan

logger = logging.getLogger(__name__)


def _today() -> date:
    return date.today()


def rollover_transport(
    from_year_id: str,
    to_year_id: str,
    *,
    copy_fee_plans: bool = True,
    copy_enrollments: bool = True,
) -> Dict[str, Any]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}
    if not from_year_id or not to_year_id:
        return {"success": False, "error": "from_year_id and to_year_id are required"}
    if from_year_id == to_year_id:
        return {"success": False, "error": "from_year_id and to_year_id must differ"}

    from_year = AcademicYear.query.filter_by(id=from_year_id, tenant_id=tenant_id).first()
    to_year = AcademicYear.query.filter_by(id=to_year_id, tenant_id=tenant_id).first()
    if not from_year:
        return {"success": False, "error": "from_year_id not found"}
    if not to_year:
        return {"success": False, "error": "to_year_id not found"}

    fee_plans_created = 0
    fee_plans_reused = 0
    enrollments_created = 0
    enrollments_skipped_graduated = 0
    enrollments_skipped_existing = 0

    new_enrollment_start = to_year.start_date or _today()

    try:
        if copy_fee_plans:
            src_plans: List[TransportFeePlan] = (
                TransportFeePlan.query.filter_by(
                    tenant_id=tenant_id, academic_year_id=from_year_id
                ).all()
            )
            existing_plan_routes = {
                p.route_id
                for p in TransportFeePlan.query.filter_by(
                    tenant_id=tenant_id, academic_year_id=to_year_id
                ).all()
            }
            for plan in src_plans:
                if plan.route_id in existing_plan_routes:
                    fee_plans_reused += 1
                    continue
                db.session.add(
                    TransportFeePlan(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        route_id=plan.route_id,
                        academic_year_id=to_year_id,
                        amount=plan.amount,
                        fee_cycle=plan.fee_cycle,
                    )
                )
                existing_plan_routes.add(plan.route_id)
                fee_plans_created += 1

        if copy_enrollments:
            src_enrollments: List[TransportEnrollment] = (
                TransportEnrollment.query.filter_by(
                    tenant_id=tenant_id, academic_year_id=from_year_id, status="active"
                ).all()
            )
            student_ids = list({e.student_id for e in src_enrollments})

            promoted_student_ids = set()
            if student_ids:
                rows = StudentClassEnrollment.query.filter(
                    StudentClassEnrollment.tenant_id == tenant_id,
                    StudentClassEnrollment.academic_year_id == to_year_id,
                    StudentClassEnrollment.is_current.is_(True),
                    StudentClassEnrollment.student_id.in_(student_ids),
                ).all()
                promoted_student_ids = {r.student_id for r in rows}

            existing_target_student_ids = set()
            if student_ids:
                rows = TransportEnrollment.query.filter(
                    TransportEnrollment.tenant_id == tenant_id,
                    TransportEnrollment.academic_year_id == to_year_id,
                    TransportEnrollment.student_id.in_(student_ids),
                ).all()
                existing_target_student_ids = {r.student_id for r in rows}

            for src in src_enrollments:
                if src.student_id not in promoted_student_ids:
                    enrollments_skipped_graduated += 1
                    continue
                if src.student_id in existing_target_student_ids:
                    enrollments_skipped_existing += 1
                    continue

                db.session.add(
                    TransportEnrollment(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        student_id=src.student_id,
                        academic_year_id=to_year_id,
                        bus_id=src.bus_id,
                        route_id=src.route_id,
                        pickup_point=src.pickup_point,
                        drop_point=src.drop_point,
                        pickup_stop_id=src.pickup_stop_id,
                        drop_stop_id=src.drop_stop_id,
                        monthly_fee=src.monthly_fee,
                        fee_cycle=src.fee_cycle,
                        status="active",
                        start_date=new_enrollment_start,
                        end_date=None,
                        student_fee_id=None,
                    )
                )
                existing_target_student_ids.add(src.student_id)
                enrollments_created += 1

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception("transport rollover failed: %s", e)
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "fee_plans_created": fee_plans_created,
        "fee_plans_reused": fee_plans_reused,
        "enrollments_created": enrollments_created,
        "enrollments_skipped_graduated": enrollments_skipped_graduated,
        "enrollments_skipped_existing": enrollments_skipped_existing,
    }
