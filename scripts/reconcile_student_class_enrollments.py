"""
Reconcile student_class_enrollments with students.class_id / academic_year_id.

For each student:
  - Resolves target placement from students + Class (class.academic_year_id is canonical
    when class_id is set; fixes student.academic_year_id in commit mode if it drifted).
  - Ensures at most one is_current enrollment globally; keeps latest by created_at if many.
  - Creates missing current enrollment, or replaces mismatching current row(s).

Modes:
  --dry-run   Print planned actions; rollback (no DB changes).
  (default)   Commit one transaction per tenant.

Usage (from repo ``server/``):
    PYTHONPATH=. python scripts/reconcile_student_class_enrollments.py --dry-run
    PYTHONPATH=. python scripts/reconcile_student_class_enrollments.py
    PYTHONPATH=. python scripts/reconcile_student_class_enrollments.py --tenant-id <uuid>

Idempotent: safe to run repeatedly.
"""

from __future__ import annotations

import argparse
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from app import create_app
from core.database import db
from core.models import Tenant, TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED
from modules.academics.backbone.models import StudentClassEnrollment
from modules.classes.models import Class
from modules.students.models import Student

logger = logging.getLogger(__name__)

CLOSED_STATUS = "reconciled"


def _target_for_student(student: Student) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    Returns (class_id, academic_year_id, warnings).
    No class_id => no target enrollment (close all current).
    """
    warnings: List[str] = []
    cid = student.class_id
    if not cid:
        return None, None, warnings

    cl = Class.query.filter_by(id=cid, tenant_id=student.tenant_id).first()
    if not cl:
        warnings.append(f"orphan class_id {cid} on student {student.id}")
        return None, None, warnings

    ay = cl.academic_year_id
    if student.academic_year_id and student.academic_year_id != ay:
        warnings.append(
            f"student {student.id} academic_year_id {student.academic_year_id} "
            f"!= class year {ay}; will align to class year"
        )
    return cid, ay, warnings


def _close_row(enr: StudentClassEnrollment, today) -> None:
    enr.is_current = False
    enr.ended_on = today
    enr.enrollment_status = CLOSED_STATUS


def _create_row(
    tenant_id: str,
    student_id: str,
    class_id: str,
    academic_year_id: str,
) -> StudentClassEnrollment:
    row = StudentClassEnrollment(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        student_id=student_id,
        class_id=class_id,
        academic_year_id=academic_year_id,
        enrollment_status="active",
        is_current=True,
        started_on=None,
        ended_on=None,
        promoted_from_enrollment_id=None,
    )
    db.session.add(row)
    return row


def reconcile_student(
    student: Student,
    today,
    dry_run: bool,
    stats: Dict[str, Any],
    verbose: bool,
) -> None:
    tid = student.tenant_id
    target_cid, target_ay, warns = _target_for_student(student)
    for w in warns:
        stats["warnings"].append(w)
        logger.warning(w)

    all_enr: List[StudentClassEnrollment] = (
        StudentClassEnrollment.query.filter_by(student_id=student.id, tenant_id=tid)
        .order_by(StudentClassEnrollment.created_at.desc())
        .all()
    )
    currents = [e for e in all_enr if e.is_current]

    # --- Case C: multiple is_current — keep latest created_at, close others
    if len(currents) > 1:
        stats["case_c_multi_current"] += 1

        def _sort_key(e: StudentClassEnrollment):
            c = e.created_at
            if c is None:
                return (0.0, e.id)
            if c.tzinfo is None:
                c = c.replace(tzinfo=timezone.utc)
            return (c.timestamp(), e.id)

        ordered = sorted(currents, key=_sort_key, reverse=True)
        keeper = ordered[0]
        for e in ordered[1:]:
            if verbose:
                stats["actions"].append(
                    f"close extra current enr {e.id} student={student.id} "
                    f"(keep {keeper.id})"
                )
            if not dry_run:
                _close_row(e, today)
        if not dry_run:
            db.session.flush()
        currents = [keeper]

    # --- No target class: close any current enrollment
    if not target_cid or not target_ay:
        if currents:
            stats["case_close_orphan_current"] += 1
            for e in currents:
                if verbose:
                    stats["actions"].append(
                        f"close current enr {e.id} student={student.id} (no class on student)"
                    )
                if not dry_run:
                    _close_row(e, today)
            if not dry_run:
                db.session.flush()
        return

    # Align student.academic_year_id to class year (matches enrollment source of truth)
    if student.academic_year_id != target_ay:
        stats["student_year_aligned"] += 1
        if verbose:
            stats["actions"].append(
                f"set student {student.id} academic_year_id -> {target_ay}"
            )
        if not dry_run:
            student.academic_year_id = target_ay

    cur = currents[0] if currents else None

    # --- Case A: no current enrollment
    if cur is None:
        stats["case_a_created"] += 1
        if verbose:
            stats["actions"].append(
                f"create enrollment student={student.id} class={target_cid} ay={target_ay}"
            )
        if not dry_run:
            _create_row(tid, student.id, target_cid, target_ay)
            db.session.flush()
        return

    # --- Already matches
    if cur.class_id == target_cid and cur.academic_year_id == target_ay:
        stats["already_ok"] += 1
        return

    # --- Case B: mismatch — close current, create correct
    stats["case_b_replaced"] += 1
    if verbose:
        stats["actions"].append(
            f"replace enrollment student={student.id}: had enr {cur.id} "
            f"class={cur.class_id} ay={cur.academic_year_id} "
            f"-> class={target_cid} ay={target_ay}"
        )
    if not dry_run:
        _close_row(cur, today)
        db.session.flush()
        _create_row(tid, student.id, target_cid, target_ay)
        db.session.flush()


def reconcile_tenant(tenant_id: str, dry_run: bool, verbose: bool) -> Dict[str, Any]:
    today = datetime.utcnow().date()
    stats: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "students_seen": 0,
        "already_ok": 0,
        "case_a_created": 0,
        "case_b_replaced": 0,
        "case_c_multi_current": 0,
        "case_close_orphan_current": 0,
        "student_year_aligned": 0,
        "warnings": [],
        "actions": [],
    }

    students = Student.query.filter_by(tenant_id=tenant_id).order_by(Student.id).all()
    stats["students_seen"] = len(students)

    try:
        for s in students:
            reconcile_student(s, today, dry_run, stats, verbose)
        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show work but rollback all changes (no commit).",
    )
    p.add_argument(
        "--tenant-id",
        default=None,
        help="Limit to one tenant UUID (default: all active/suspended tenants).",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Record per-row action strings in stats.",
    )
    args = p.parse_args()

    app = create_app()
    with app.app_context():
        if args.tenant_id:
            tenants = Tenant.query.filter_by(id=args.tenant_id).all()
            if not tenants:
                raise SystemExit(f"No tenant with id {args.tenant_id!r}")
        else:
            tenants = Tenant.query.filter(
                Tenant.status.in_([TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED])
            ).all()

        print("=" * 60)
        print(
            "Reconcile student_class_enrollments",
            "(DRY RUN)" if args.dry_run else "(COMMIT)",
        )
        print(f"Tenants: {len(tenants)}")
        print("=" * 60)

        grand = {
            "tenants": 0,
            "students_seen": 0,
            "already_ok": 0,
            "case_a_created": 0,
            "case_b_replaced": 0,
            "case_c_multi_current": 0,
            "case_close_orphan_current": 0,
            "student_year_aligned": 0,
        }

        for t in tenants:
            print(f"\n--- Tenant {t.subdomain} ({t.id}) ---")
            st = reconcile_tenant(t.id, dry_run=args.dry_run, verbose=args.verbose)
            grand["tenants"] += 1
            for k in (
                "students_seen",
                "already_ok",
                "case_a_created",
                "case_b_replaced",
                "case_c_multi_current",
                "case_close_orphan_current",
                "student_year_aligned",
            ):
                grand[k] += st[k]
            print(
                f"  students={st['students_seen']} ok={st['already_ok']} "
                f"created={st['case_a_created']} replaced={st['case_b_replaced']} "
                f"multi_current={st['case_c_multi_current']} "
                f"closed_no_class={st['case_close_orphan_current']} "
                f"year_aligned={st['student_year_aligned']}"
            )
            if st["warnings"]:
                for w in st["warnings"][:20]:
                    print(f"  WARN: {w}")
                if len(st["warnings"]) > 20:
                    print(f"  ... {len(st['warnings']) - 20} more warnings")
            if args.verbose and st["actions"]:
                for a in st["actions"][:50]:
                    print(f"  {a}")
                if len(st["actions"]) > 50:
                    print(f"  ... {len(st['actions']) - 50} more actions")

        print("\n" + "=" * 60)
        print("TOTAL", grand)
        print("=" * 60)
        if args.dry_run:
            print("Dry run complete — no changes committed.\n")
        else:
            print("Committed per-tenant transactions.\n")


if __name__ == "__main__":
    main()
