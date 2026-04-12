"""
Dashboard Aggregation Service

Single-query-set aggregation for the admin dashboard.
Pulls from existing models to produce one structured response.
All queries use COUNT/GROUP BY to avoid loading full row sets.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import cast, func, Date

from core.database import db
from core.tenant import get_tenant_id
from core.plan_features import is_plan_feature_enabled
from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import (
    AttendanceSession,
    ClassSubjectTeacher,
    TimetableEntry,
    TimetableVersion,
)
from modules.classes.models import Class, ClassSubject
from modules.finance.enums import PaymentStatus, StudentFeeStatus
from modules.finance.models import Payment, StudentFee
from modules.holidays.models import Holiday
from modules.schedule.models import ScheduleOverride
from modules.students.models import Student
from modules.teachers.models import Teacher, TeacherLeave
from modules.transport.models import (
    TransportBus,
    TransportEnrollment,
    TransportRoute,
)


def _today() -> date:
    return date.today()


def _active_academic_year(tenant_id: str) -> Dict[str, Any]:
    ay = (
        AcademicYear.query.filter_by(tenant_id=tenant_id, is_active=True)
        .order_by(AcademicYear.start_date.desc())
        .first()
    )
    if not ay:
        ay = (
            AcademicYear.query.filter_by(tenant_id=tenant_id)
            .order_by(AcademicYear.start_date.desc())
            .first()
        )
    if not ay:
        return {"id": None, "name": "Not set"}
    return {"id": ay.id, "name": ay.name}


def _overview(tenant_id: str) -> Dict[str, Any]:
    total_students = Student.query.filter_by(tenant_id=tenant_id).count()
    total_teachers = Teacher.query.filter_by(tenant_id=tenant_id).count()
    total_classes = Class.query.filter_by(tenant_id=tenant_id).count()
    ay = _active_academic_year(tenant_id)
    return {
        "total_students": total_students,
        "total_teachers": total_teachers,
        "total_classes": total_classes,
        "academic_year": ay["name"],
    }


def _today_ops(tenant_id: str) -> Dict[str, Any]:
    today = _today()
    dow = today.isoweekday()

    lectures_today = (
        db.session.query(func.count(TimetableEntry.id))
        .join(
            TimetableVersion,
            TimetableEntry.timetable_version_id == TimetableVersion.id,
        )
        .filter(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.day_of_week == dow,
            TimetableEntry.entry_status == "active",
            TimetableVersion.status == "active",
        )
        .scalar()
        or 0
    )

    total_classes = Class.query.filter_by(tenant_id=tenant_id).count()

    finalized_today = (
        AttendanceSession.query.filter(
            AttendanceSession.tenant_id == tenant_id,
            AttendanceSession.session_date == today,
            AttendanceSession.status == "finalized",
            AttendanceSession.deleted_at.is_(None),
        ).count()
    )

    pending_attendance_classes = max(0, total_classes - finalized_today)

    attendance_completion_pct = (
        round(100.0 * finalized_today / total_classes, 1) if total_classes > 0 else 0.0
    )

    schedule_overrides_count = ScheduleOverride.query.filter_by(
        tenant_id=tenant_id, override_date=today
    ).count()

    last_session = (
        AttendanceSession.query.filter(
            AttendanceSession.tenant_id == tenant_id,
            AttendanceSession.session_date == today,
            AttendanceSession.status == "finalized",
            AttendanceSession.deleted_at.is_(None),
        )
        .order_by(AttendanceSession.updated_at.desc())
        .first()
    )
    last_attendance_marked_at = (
        last_session.updated_at.isoformat()
        if last_session and last_session.updated_at
        else None
    )

    return {
        "lectures_today": lectures_today,
        "attendance_marked_classes": finalized_today,
        "total_classes": total_classes,
        "attendance_completion_percentage": attendance_completion_pct,
        "pending_attendance_classes": pending_attendance_classes,
        "schedule_overrides_count": schedule_overrides_count,
        "last_attendance_marked_at": last_attendance_marked_at,
    }


def _alerts(tenant_id: str, transport_enabled: bool) -> Dict[str, Any]:
    # Timetable conflicts: same teacher, same dow, same period in two active timetables
    conflict_rows = (
        db.session.query(
            TimetableEntry.teacher_id,
            TimetableEntry.day_of_week,
            TimetableEntry.period_number,
            func.count(TimetableEntry.id).label("cnt"),
        )
        .join(
            TimetableVersion,
            TimetableEntry.timetable_version_id == TimetableVersion.id,
        )
        .filter(
            TimetableEntry.tenant_id == tenant_id,
            TimetableVersion.status == "active",
            TimetableEntry.entry_status == "active",
            TimetableEntry.teacher_id.isnot(None),
        )
        .group_by(
            TimetableEntry.teacher_id,
            TimetableEntry.day_of_week,
            TimetableEntry.period_number,
        )
        .having(func.count(TimetableEntry.id) > 1)
        .all()
    )
    timetable_conflicts = len(conflict_rows)

    # Classes without active timetable
    all_class_ids = [
        c.id for c in Class.query.filter_by(tenant_id=tenant_id).with_entities(Class.id).all()
    ]
    classes_with_timetable = {
        row[0]
        for row in db.session.query(TimetableVersion.class_id)
        .filter(
            TimetableVersion.tenant_id == tenant_id,
            TimetableVersion.status == "active",
        )
        .all()
    }
    classes_without_timetable = sum(
        1 for cid in all_class_ids if cid not in classes_with_timetable
    )

    # Class subjects without primary teacher
    active_subject_ids = [
        cs.id
        for cs in ClassSubject.query.filter(
            ClassSubject.tenant_id == tenant_id,
            ClassSubject.deleted_at.is_(None),
            ClassSubject.status == "active",
        )
        .with_entities(ClassSubject.id)
        .all()
    ]
    assigned_subject_ids = {
        row[0]
        for row in db.session.query(ClassSubjectTeacher.class_subject_id)
        .filter(
            ClassSubjectTeacher.tenant_id == tenant_id,
            ClassSubjectTeacher.role == "primary",
            ClassSubjectTeacher.is_active.is_(True),
            ClassSubjectTeacher.deleted_at.is_(None),
        )
        .all()
    }
    subjects_without_teacher = sum(
        1 for sid in active_subject_ids if sid not in assigned_subject_ids
    )

    # Classes without subjects
    classes_with_subjects = {
        row[0]
        for row in db.session.query(ClassSubject.class_id)
        .filter(
            ClassSubject.tenant_id == tenant_id,
            ClassSubject.deleted_at.is_(None),
            ClassSubject.status == "active",
        )
        .all()
    }
    classes_without_subjects = sum(
        1 for cid in all_class_ids if cid not in classes_with_subjects
    )

    # Students without class
    students_without_class = Student.query.filter(
        Student.tenant_id == tenant_id,
        Student.class_id.is_(None),
    ).count()

    # Overdue fee students
    overdue_fees_students = (
        db.session.query(func.count(StudentFee.id))
        .filter(
            StudentFee.tenant_id == tenant_id,
            StudentFee.status == StudentFeeStatus.overdue.value,
        )
        .scalar()
        or 0
    )

    # Transport issues
    transport_issues = 0
    if transport_enabled:
        today = _today()
        # Students on inactive routes
        active_route_ids = {
            r.id
            for r in TransportRoute.query.filter_by(
                tenant_id=tenant_id, status="active"
            )
            .with_entities(TransportRoute.id)
            .all()
        }
        enrolled_route_ids = [
            row[0]
            for row in db.session.query(TransportEnrollment.route_id)
            .filter(
                TransportEnrollment.tenant_id == tenant_id,
                TransportEnrollment.status == "active",
            )
            .all()
        ]
        students_inactive = sum(
            1 for rid in enrolled_route_ids if rid not in active_route_ids
        )

        # Buses near/at capacity
        buses = TransportBus.query.filter_by(
            tenant_id=tenant_id, status="active"
        ).all()
        buses_near = 0
        for b in buses:
            cap = b.capacity or 0
            if cap <= 0:
                continue
            used = (
                db.session.query(func.count(TransportEnrollment.id))
                .filter(
                    TransportEnrollment.tenant_id == tenant_id,
                    TransportEnrollment.bus_id == b.id,
                    TransportEnrollment.status == "active",
                )
                .scalar()
                or 0
            )
            if used / cap >= 0.85:
                buses_near += 1

        transport_issues = students_inactive + buses_near

    return {
        "timetable_conflicts": timetable_conflicts,
        "classes_without_timetable": classes_without_timetable,
        "subjects_without_teacher": subjects_without_teacher,
        "classes_without_subjects": classes_without_subjects,
        "students_without_class": students_without_class,
        "overdue_fees_students": overdue_fees_students,
        "transport_issues": transport_issues,
        "total_issues": (
            timetable_conflicts
            + classes_without_timetable
            + subjects_without_teacher
            + classes_without_subjects
            + students_without_class
            + overdue_fees_students
            + transport_issues
        ),
    }


def _finance(tenant_id: str) -> Dict[str, Any]:
    agg = (
        db.session.query(
            func.coalesce(func.sum(StudentFee.total_amount), 0).label("total_expected"),
            func.coalesce(func.sum(StudentFee.paid_amount), 0).label("total_collected"),
            func.coalesce(
                func.sum(
                    db.case(
                        (StudentFee.status == StudentFeeStatus.overdue.value, 1),
                        else_=0,
                    )
                ),
                0,
            ).label("overdue_count"),
        )
        .filter(StudentFee.tenant_id == tenant_id)
        .first()
    )

    total_expected = float(agg.total_expected or 0)
    total_collected = float(agg.total_collected or 0)
    overdue_count = int(agg.overdue_count or 0)
    total_outstanding = total_expected - total_collected
    collection_pct = (
        round(100.0 * total_collected / total_expected, 1) if total_expected > 0 else 0.0
    )

    # Last 7 days collection grouped by date
    cutoff = datetime.utcnow() - timedelta(days=6)
    rows = (
        db.session.query(
            cast(Payment.created_at, Date).label("pay_date"),
            func.coalesce(func.sum(Payment.amount), 0).label("total"),
        )
        .filter(
            Payment.tenant_id == tenant_id,
            Payment.status == PaymentStatus.success.value,
            Payment.created_at >= cutoff,
        )
        .group_by(cast(Payment.created_at, Date))
        .order_by(cast(Payment.created_at, Date))
        .all()
    )

    # Build a full 7-day series (fill missing days with 0)
    collected_by_date: Dict[str, float] = {
        str(row.pay_date): float(row.total) for row in rows
    }
    today = _today()
    last_7: List[Dict[str, Any]] = []
    for offset in range(6, -1, -1):
        d = (today - timedelta(days=offset)).isoformat()
        last_7.append({"date": d, "amount": collected_by_date.get(d, 0.0)})

    current_7_total = sum(d["amount"] for d in last_7)

    # Previous week window (days 8–14 ago) for trend comparison
    prev_start = datetime.utcnow() - timedelta(days=14)
    prev_end = datetime.utcnow() - timedelta(days=7)
    prev_total_row = (
        db.session.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(
            Payment.tenant_id == tenant_id,
            Payment.status == PaymentStatus.success.value,
            Payment.created_at >= prev_start,
            Payment.created_at < prev_end,
        )
        .scalar()
    )
    last_week_collection_total = float(prev_total_row or 0)
    if last_week_collection_total > 0:
        trend_percentage = round(
            (current_7_total - last_week_collection_total) / last_week_collection_total * 100,
            1,
        )
    else:
        trend_percentage = 0.0

    return {
        "total_expected": total_expected,
        "total_collected": total_collected,
        "collection_percentage": collection_pct,
        "total_outstanding": total_outstanding,
        "overdue_count": overdue_count,
        "last_7_days_collection": last_7,
        "last_week_collection_total": last_week_collection_total,
        "trend_percentage": trend_percentage,
    }


def _transport(tenant_id: str) -> Dict[str, Any]:
    buses = TransportBus.query.filter_by(tenant_id=tenant_id).all()
    total_buses = len(buses)
    active_buses = sum(1 for b in buses if b.status == "active")

    students_on_transport = (
        db.session.query(func.count(TransportEnrollment.id))
        .filter(
            TransportEnrollment.tenant_id == tenant_id,
            TransportEnrollment.status == "active",
        )
        .scalar()
        or 0
    )

    # Buses with ≥ 85 % occupancy
    buses_near_capacity = 0
    for b in buses:
        if b.status != "active":
            continue
        cap = b.capacity or 0
        if cap <= 0:
            continue
        used = (
            db.session.query(func.count(TransportEnrollment.id))
            .filter(
                TransportEnrollment.tenant_id == tenant_id,
                TransportEnrollment.bus_id == b.id,
                TransportEnrollment.status == "active",
            )
            .scalar()
            or 0
        )
        if used / cap >= 0.85:
            buses_near_capacity += 1

    active_route_ids = {
        r.id
        for r in TransportRoute.query.filter_by(tenant_id=tenant_id, status="active")
        .with_entities(TransportRoute.id)
        .all()
    }
    enrolled_route_ids = [
        row[0]
        for row in db.session.query(TransportEnrollment.route_id)
        .filter(
            TransportEnrollment.tenant_id == tenant_id,
            TransportEnrollment.status == "active",
        )
        .all()
    ]
    students_on_inactive_routes = sum(
        1 for rid in enrolled_route_ids if rid not in active_route_ids
    )

    return {
        "enabled": True,
        "total_buses": total_buses,
        "active_buses": active_buses,
        "students_on_transport": students_on_transport,
        "buses_near_capacity": buses_near_capacity,
        "students_on_inactive_routes": students_on_inactive_routes,
    }


def _actions(tenant_id: str) -> Dict[str, Any]:
    pending_leave_requests = TeacherLeave.query.filter_by(
        tenant_id=tenant_id, status=TeacherLeave.STATUS_PENDING
    ).count()

    today = _today()
    upcoming_holidays_rows = (
        Holiday.query.filter(
            Holiday.tenant_id == tenant_id,
            Holiday.is_recurring == False,  # noqa: E712
            Holiday.start_date >= today,
        )
        .order_by(Holiday.start_date.asc())
        .limit(3)
        .all()
    )
    upcoming_holidays: List[Dict[str, Any]] = [
        {"name": h.name, "date": h.start_date.isoformat()}
        for h in upcoming_holidays_rows
    ]

    return {
        "pending_leave_requests": pending_leave_requests,
        "upcoming_holidays": upcoming_holidays,
    }


def build_dashboard() -> Dict[str, Any]:
    """
    Aggregate all dashboard data for the current tenant.
    Returns the full dashboard payload in one pass.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"error": "Tenant context required"}

    transport_enabled = is_plan_feature_enabled(tenant_id, "transport_management")

    overview = _overview(tenant_id)
    today_ops = _today_ops(tenant_id)
    alerts = _alerts(tenant_id, transport_enabled)
    finance = _finance(tenant_id)
    transport = (
        _transport(tenant_id)
        if transport_enabled
        else {"enabled": False}
    )
    actions = _actions(tenant_id)

    health_score = _health_score(alerts, today_ops)

    return {
        "overview": overview,
        "today": today_ops,
        "alerts": alerts,
        "finance": finance,
        "transport": transport,
        "actions": actions,
        "health_score": health_score,
    }


def _health_score(alerts: Dict[str, Any], today_ops: Dict[str, Any]) -> int:
    score = 100
    total_issues = alerts.get("total_issues", 0)
    score -= min(total_issues * 5, 50)
    if today_ops.get("attendance_completion_percentage", 100) < 50:
        score -= 20
    if alerts.get("overdue_fees_students", 0) > 0:
        score -= 10
    return max(0, min(100, score))
