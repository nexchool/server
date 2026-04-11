"""
Bulk teacher import: parse Excel, validate, batch insert, optional notify.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.exc import IntegrityError

from core.database import db
from core.tenant import get_tenant_id
from core.models import Tenant
from modules.auth.models import User
from modules.rbac.models import Role, UserRole
from modules.rbac.role_seeder import seed_roles_for_tenant
from modules.students.utils.bulk_validation import is_blank, validate_email_format
from modules.students.utils.excel_parser import parse_xlsx_to_rows
from modules.teachers.models import Teacher
from modules.teachers.services import (
    _check_teacher_plan_limit,
    generate_teacher_password,
)
from modules.teachers.utils.bulk_validation import (
    REQUIRED_TEACHER_FIELDS,
    coerce_teacher_row,
    filter_known_teacher_columns,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


def _tenant_emails_lower(tenant_id: str) -> Set[str]:
    rows = db.session.query(User.email).filter(User.tenant_id == tenant_id).all()
    return {r[0].strip().lower() for r in rows if r[0]}


def _tenant_employee_ids(tenant_id: str) -> Set[str]:
    rows = (
        db.session.query(Teacher.employee_id)
        .filter(Teacher.tenant_id == tenant_id)
        .all()
    )
    return {r[0] for r in rows if r[0]}


def _validate_and_coerce_row(
    raw: Dict[str, Any],
    row_number: int,
    *,
    db_emails_lower: Set[str],
    db_employee_ids: Set[str],
    file_emails: Set[str],
    file_employee_ids: Set[str],
) -> Tuple[bool, Dict[str, Any], List[str], List[str], Optional[Dict[str, Any]]]:
    errors: List[str] = []
    warnings: List[str] = []
    row = filter_known_teacher_columns(raw)

    for req in REQUIRED_TEACHER_FIELDS:
        if is_blank(row.get(req)):
            errors.append(f"Missing {req}")

    name = str(row["name"]).strip() if not is_blank(row.get("name")) else ""
    if name and len(name) > 120:
        errors.append("name: max 120 characters")

    email_raw = str(row.get("email")).strip() if not is_blank(row.get("email")) else None
    emp_raw = str(row.get("employee_id")).strip() if not is_blank(row.get("employee_id")) else None
    if emp_raw and len(emp_raw) > 20:
        errors.append("employee_id: max 20 characters")

    if email_raw:
        if not validate_email_format(email_raw):
            errors.append("Invalid email")
        el = email_raw.lower()
        if el in db_emails_lower:
            errors.append("Email already exists")
        elif el in file_emails:
            errors.append("Duplicate email in file")

    if emp_raw:
        if emp_raw in db_employee_ids:
            errors.append("Employee ID already exists")
        elif emp_raw in file_employee_ids:
            errors.append("Duplicate employee ID in file")

    date_errs: List[str] = []
    coerced = coerce_teacher_row(row, warnings, date_errs)
    for e in date_errs:
        errors.append(e)

    display = {**{k: raw.get(k) for k in raw}, **coerced}
    display["row_number"] = row_number

    if errors:
        return False, display, errors, warnings, None

    if not name:
        return False, display, errors or ["Invalid row"], warnings, None

    if email_raw:
        file_emails.add(email_raw.lower())
    if emp_raw:
        file_employee_ids.add(emp_raw)

    coerced["name"] = name
    if email_raw:
        coerced["email"] = email_raw
    else:
        coerced.pop("email", None)
    if emp_raw:
        coerced["employee_id"] = emp_raw
    else:
        coerced.pop("employee_id", None)

    if "status" not in coerced or is_blank(coerced.get("status")):
        coerced["status"] = "active"

    return True, display, [], warnings, coerced


def validate_teacher_workbook_rows(
    rows: List[Dict[str, Any]],
    row_numbers: List[int],
    tenant_id: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    db_emails = _tenant_emails_lower(tenant_id)
    db_emp = _tenant_employee_ids(tenant_id)

    file_emails: Set[str] = set()
    file_emp: Set[str] = set()

    preview: List[Dict[str, Any]] = []
    valid_n = 0
    invalid_n = 0

    for raw, rn in zip(rows, row_numbers):
        ok, display, errs, warns, _coerced = _validate_and_coerce_row(
            raw,
            rn,
            db_emails_lower=db_emails,
            db_employee_ids=db_emp,
            file_emails=file_emails,
            file_employee_ids=file_emp,
        )
        if ok:
            valid_n += 1
        else:
            invalid_n += 1
        preview.append(
            {
                "row_number": rn,
                "values": display,
                "errors": errs,
                "warnings": warns,
                "valid": ok,
            }
        )

    return preview, {"valid": valid_n, "invalid": invalid_n, "total": len(rows)}


def _preassign_employee_ids(
    validated: List[Tuple[int, Dict[str, Any]]],
    tenant_id: str,
) -> None:
    """Fill missing employee_id with TCH{year}NNN values without colliding with DB or file."""
    year = datetime.utcnow().year
    prefix = f"TCH{year}"

    latest = (
        Teacher.query.filter(
            Teacher.tenant_id == tenant_id,
            Teacher.employee_id.like(f"{prefix}%"),
        )
        .order_by(Teacher.employee_id.desc())
        .first()
    )
    seq = 0
    if latest and latest.employee_id.startswith(prefix):
        try:
            seq = int(latest.employee_id[len(prefix) :])
        except ValueError:
            seq = 0

    used: Set[str] = set(_tenant_employee_ids(tenant_id))
    for _rn, coerced in validated:
        eid = coerced.get("employee_id")
        if eid:
            used.add(eid)

    for _rn, coerced in validated:
        if coerced.get("employee_id"):
            continue
        while True:
            seq += 1
            cand = f"{prefix}{seq:03d}"
            if cand not in used:
                coerced["employee_id"] = cand
                used.add(cand)
                break


def _teacher_kwargs_from_coerced(coerced: Dict[str, Any]) -> Dict[str, Any]:
    """Map coerced import row to Teacher() constructor kwargs (excluding id, tenant, user)."""
    doj = None
    if coerced.get("date_of_joining"):
        doj = datetime.strptime(coerced["date_of_joining"], "%Y-%m-%d").date()

    return {
        "employee_id": coerced["employee_id"],
        "designation": _clean_str(coerced.get("designation")),
        "department": _clean_str(coerced.get("department")),
        "qualification": _clean_str(coerced.get("qualification")),
        "specialization": _clean_str(coerced.get("specialization")),
        "experience_years": coerced.get("experience_years"),
        "phone": _clean_str(coerced.get("phone")),
        "address": _clean_str(coerced.get("address")),
        "date_of_joining": doj,
        "status": coerced.get("status") or "active",
    }


def _clean_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _dispatch_teacher_welcome(
    user_id: str,
    tenant_id: str,
    send_email: bool,
) -> None:
    from modules.notifications.enums import NotificationChannel, NotificationType
    from modules.notifications.services import notification_dispatcher

    channels = [NotificationChannel.IN_APP.value]
    if send_email:
        channels.append(NotificationChannel.EMAIL.value)

    notification_dispatcher.dispatch(
        user_id=user_id,
        tenant_id=tenant_id,
        notification_type=NotificationType.ANNOUNCEMENT.value,
        channels=channels,
        title="Welcome to Nexchool",
        body="Your teacher account has been created. Sign in with your credentials.",
        extra_data={},
    )


def import_teachers_from_rows(
    rows: List[Dict[str, Any]],
    row_numbers: List[int],
    *,
    tenant_id: str,
    send_email: bool,
) -> Dict[str, Any]:
    seed_roles_for_tenant(tenant_id)
    teacher_role = Role.query.filter_by(tenant_id=tenant_id, name="Teacher").first()
    if not teacher_role:
        return {
            "total": 0,
            "success": 0,
            "failed": 0,
            "failed_rows": [],
            "error": "Teacher role not found",
        }

    db_emails = _tenant_emails_lower(tenant_id)
    db_emp = _tenant_employee_ids(tenant_id)

    validated: List[Tuple[int, Dict[str, Any]]] = []
    failed_rows: List[Dict[str, Any]] = []

    file_emails: Set[str] = set()
    file_emp: Set[str] = set()

    for raw, rn in zip(rows, row_numbers):
        ok, _disp, errs, _warns, coerced = _validate_and_coerce_row(
            raw,
            rn,
            db_emails_lower=db_emails,
            db_employee_ids=db_emp,
            file_emails=file_emails,
            file_employee_ids=file_emp,
        )
        if ok and coerced:
            validated.append((rn, coerced))
        else:
            failed_rows.append(
                {
                    "row_number": rn,
                    "email": (raw.get("email") or "") if isinstance(raw, dict) else "",
                    "errors": errs,
                }
            )

    total = len(rows)
    if not validated:
        return {
            "total": total,
            "success": 0,
            "failed": len(failed_rows),
            "failed_rows": failed_rows,
        }

    allowed, limit_msg = _check_teacher_plan_limit(tenant_id)
    if not allowed:
        return {
            "total": total,
            "success": 0,
            "failed": total,
            "failed_rows": [
                {
                    "row_number": rn,
                    "email": "",
                    "errors": [limit_msg or "Plan limit"],
                }
                for rn in row_numbers
            ],
            "error": limit_msg,
        }

    tenant = Tenant.query.get(tenant_id)
    if tenant and tenant.plan_id and tenant.plan:
        cap = tenant.plan.max_teachers
        current = Teacher.query.filter_by(tenant_id=tenant_id).count()
        if current + len(validated) > cap:
            return {
                "total": total,
                "success": 0,
                "failed": total,
                "failed_rows": [
                    {
                        "row_number": rn,
                        "email": "",
                        "errors": [
                            f"Would exceed plan teacher limit ({cap}). "
                            f"Current: {current}, importing: {len(validated)}."
                        ],
                    }
                    for rn in row_numbers
                ],
                "error": "Teacher plan limit",
            }

    _preassign_employee_ids(validated, tenant_id)

    tkwargs = _teacher_kwargs_from_coerced
    success_count = 0

    for i in range(0, len(validated), BATCH_SIZE):
        chunk = validated[i : i + BATCH_SIZE]
        batch_created: List[Tuple[int, str]] = []
        for rn, coerced in chunk:
            emp_id = coerced["employee_id"]
            email_in = coerced.get("email")
            actual_email = (
                email_in.strip().lower()
                if email_in
                else f"{emp_id.lower()}@teacher.school"
            )
            pwd = generate_teacher_password(coerced["name"])
            try:
                with db.session.begin_nested():
                    user = User(
                        tenant_id=tenant_id,
                        email=actual_email,
                        name=coerced["name"],
                        email_verified=True,
                        force_password_reset=True,
                    )
                    user.set_password(pwd)
                    db.session.add(user)
                    db.session.flush()

                    ur = UserRole(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        user_id=user.id,
                        role_id=teacher_role.id,
                    )
                    db.session.add(ur)

                    teacher = Teacher(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        user_id=user.id,
                        **tkwargs(coerced),
                    )
                    db.session.add(teacher)
                    db.session.flush()
                    batch_created.append((rn, user.id))
            except IntegrityError as e:
                logger.warning("bulk_teacher_import: integrity row=%s: %s", rn, e)
                failed_rows.append(
                    {
                        "row_number": rn,
                        "email": coerced.get("email") or actual_email,
                        "errors": ["Database constraint violation (duplicate or invalid)"],
                    }
                )
            except Exception as e:
                logger.exception("bulk_teacher_import: row=%s failed: %s", rn, e)
                failed_rows.append(
                    {
                        "row_number": rn,
                        "email": coerced.get("email") or actual_email,
                        "errors": [str(e)],
                    }
                )

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.exception("bulk_teacher_import: batch commit failed: %s", e)
            for rn, _uid in batch_created:
                failed_rows.append(
                    {
                        "row_number": rn,
                        "email": "",
                        "errors": ["Batch commit failed"],
                    }
                )
            continue

        for rn, user_id in batch_created:
            success_count += 1
            logger.info(
                "bulk_teacher_import: created teacher user_id=%s row=%s",
                user_id,
                rn,
            )
            _dispatch_teacher_welcome(user_id, tenant_id, send_email)

    return {
        "total": total,
        "success": success_count,
        "failed": len(failed_rows),
        "failed_rows": failed_rows,
    }


def run_preview(file_bytes: bytes) -> Dict[str, Any]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise ValueError("Tenant context is required")

    header_keys, rows, row_numbers = parse_xlsx_to_rows(file_bytes)
    logger.info(
        "bulk_teacher_import preview: %s data rows, headers=%s",
        len(rows),
        header_keys,
    )

    preview, summary = validate_teacher_workbook_rows(rows, row_numbers, tenant_id)
    return {
        "preview": preview,
        "errors": [],
        "summary": summary,
        "headers": header_keys,
    }


def run_import(file_bytes: bytes, send_email: bool) -> Dict[str, Any]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise ValueError("Tenant context is required")

    _header_keys, rows, row_numbers = parse_xlsx_to_rows(file_bytes)
    logger.info("bulk_teacher_import: processing %s rows", len(rows))

    return import_teachers_from_rows(
        rows,
        row_numbers,
        tenant_id=tenant_id,
        send_email=send_email,
    )
