"""
Bulk student import: parse Excel, validate, batch insert, notify.
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
from modules.academics.academic_year.models import AcademicYear
from modules.auth.models import User
from modules.classes.models import Class
from modules.rbac.models import Role, UserRole
from modules.rbac.role_seeder import seed_roles_for_tenant
from modules.students.models import Student
from modules.students.services import (
    _check_student_plan_limit,
    _clean_bool,
    _clean_decimal,
    _clean_int,
    _clean_str,
    generate_admission_number,
)
from modules.students.utils.bulk_validation import (
    REQUIRED_FIELDS,
    coerce_row_types,
    filter_known_columns,
    resolve_guardian_fields,
    validate_email_format,
    validate_phone_soft,
    is_blank,
)
from modules.students.utils.excel_parser import parse_xlsx_to_rows
from modules.students.utils.password_utils import default_student_import_password

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


def _tenant_emails_lower(tenant_id: str) -> Set[str]:
    rows = (
        db.session.query(User.email)
        .filter(User.tenant_id == tenant_id)
        .all()
    )
    return {r[0].strip().lower() for r in rows if r[0]}


def _tenant_admission_numbers(tenant_id: str) -> Set[str]:
    rows = (
        db.session.query(Student.admission_number)
        .filter(Student.tenant_id == tenant_id)
        .all()
    )
    return {r[0] for r in rows if r[0]}


def _class_map_for_year(tenant_id: str, academic_year_id: str) -> Dict[Tuple[str, str], str]:
    classes = Class.query.filter_by(
        tenant_id=tenant_id,
        academic_year_id=academic_year_id,
    ).all()
    return {
        (c.name.strip().lower(), c.section.strip().lower()): c.id
        for c in classes
    }


def _soft_phone_column(val: Any, field: str, warnings: List[str]) -> Optional[str]:
    if is_blank(val):
        return None
    norm, ok = validate_phone_soft(str(val).strip())
    if not ok:
        logger.warning("bulk_import: invalid %s ignored: %r", field, val)
        warnings.append(f"{field}: invalid format ignored")
    return norm


def _validate_and_coerce_row(
    raw: Dict[str, Any],
    row_number: int,
    *,
    class_map: Dict[Tuple[str, str], str],
    db_emails_lower: Set[str],
    file_emails: Set[str],
) -> Tuple[bool, Dict[str, Any], List[str], List[str], Optional[Dict[str, Any]]]:
    """
    Returns (valid, display_values, hard_errors, warnings, coerced_or_none).
    """
    errors: List[str] = []
    warnings: List[str] = []
    row = filter_known_columns(raw)

    for req in REQUIRED_FIELDS:
        if is_blank(row.get(req)):
            errors.append(f"Missing {req}")

    email = (str(row.get("email")).strip() if not is_blank(row.get("email")) else None)
    if not is_blank(row.get("admission_number")):
        warnings.append(
            "admission_number column is ignored; admission numbers are assigned automatically"
        )

    if email:
        if not validate_email_format(email):
            errors.append("Invalid email")
        el = email.lower()
        if el in db_emails_lower:
            errors.append("Email already exists")
        elif el in file_emails:
            errors.append("Duplicate email in file")

    class_name = (
        str(row.get("class_name")).strip() if not is_blank(row.get("class_name")) else None
    )
    section = str(row.get("section")).strip() if not is_blank(row.get("section")) else None
    class_id: Optional[str] = None
    if class_name and section:
        class_id = class_map.get((class_name.lower(), section.lower()))
        if not class_id:
            errors.append("Class not found for class_name and section")
    elif class_name or section:
        errors.append("Both class_name and section are required")

    date_errs: List[str] = []
    coerced = coerce_row_types(row, warnings, date_errs)
    for e in date_errs:
        errors.append(e)

    for f in (
        "father_phone",
        "mother_phone",
        "guardian_phone",
        "emergency_contact_phone",
    ):
        if f in coerced and not is_blank(coerced.get(f)):
            coerced[f] = _soft_phone_column(coerced.get(f), f, warnings)

    display = {**{k: raw.get(k) for k in raw}, **coerced}
    display["row_number"] = row_number

    if errors:
        return False, display, errors, warnings, None

    if not email or not class_id:
        return False, display, errors or ["Invalid row"], warnings, None

    file_emails.add(email.lower())

    coerced["email"] = email
    coerced["name"] = str(row["name"]).strip()
    coerced["class_id"] = class_id
    coerced["class_name"] = class_name
    coerced["section"] = section

    g_name, g_rel, g_phone = resolve_guardian_fields(coerced)
    coerced["guardian_name"] = g_name
    coerced["guardian_relationship"] = g_rel
    coerced["guardian_phone"] = g_phone

    return True, display, [], warnings, coerced


def validate_workbook_rows(
    header_keys: List[str],
    rows: List[Dict[str, Any]],
    row_numbers: List[int],
    tenant_id: str,
    academic_year_id: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Full validation with duplicate tracking. Returns preview rows + summary counts.
    """
    ay = AcademicYear.query.filter_by(
        id=academic_year_id, tenant_id=tenant_id
    ).first()
    if not ay:
        raise ValueError("academic_year_id not found for this tenant")

    class_map = _class_map_for_year(tenant_id, academic_year_id)
    db_emails = _tenant_emails_lower(tenant_id)

    file_emails: Set[str] = set()

    preview: List[Dict[str, Any]] = []
    valid_n = 0
    invalid_n = 0

    for raw, rn in zip(rows, row_numbers):
        ok, display, errs, warns, _coerced = _validate_and_coerce_row(
            raw,
            rn,
            class_map=class_map,
            db_emails_lower=db_emails,
            file_emails=file_emails,
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


def _student_kwargs_from_row(
    coerced: Dict[str, Any],
    *,
    academic_year_id: str,
) -> Dict[str, Any]:
    """Build kwargs for Student() from normalized import row."""
    dob = None
    if coerced.get("date_of_birth"):
        dob = datetime.strptime(coerced["date_of_birth"], "%Y-%m-%d").date()

    adm_date = None
    if coerced.get("admission_date"):
        adm_date = datetime.strptime(coerced["admission_date"], "%Y-%m-%d").date()

    weight = _clean_decimal(coerced.get("weight_kg"))

    kwargs: Dict[str, Any] = {
        "admission_number": coerced["admission_number"],
        "academic_year_id": academic_year_id,
        "class_id": coerced["class_id"],
        "roll_number": _clean_int(coerced.get("roll_number")),
        "date_of_birth": dob,
        "gender": _clean_str(coerced.get("gender")),
        "phone": _clean_str(coerced.get("phone")),
        "guardian_name": _clean_str(coerced.get("guardian_name")),
        "guardian_relationship": _clean_str(coerced.get("guardian_relationship")),
        "guardian_phone": _clean_str(coerced.get("guardian_phone")),
        "guardian_email": _clean_str(coerced.get("guardian_email")),
        "blood_group": _clean_str(coerced.get("blood_group")),
        "height_cm": _clean_int(coerced.get("height_cm")),
        "weight_kg": weight,
        "medical_allergies": _clean_str(coerced.get("medical_allergies")),
        "medical_conditions": _clean_str(coerced.get("medical_conditions")),
        "father_name": _clean_str(coerced.get("father_name")),
        "father_phone": _clean_str(coerced.get("father_phone")),
        "father_email": _clean_str(coerced.get("father_email")),
        "father_occupation": _clean_str(coerced.get("father_occupation")),
        "father_annual_income": _clean_int(coerced.get("father_annual_income")),
        "mother_name": _clean_str(coerced.get("mother_name")),
        "mother_phone": _clean_str(coerced.get("mother_phone")),
        "mother_email": _clean_str(coerced.get("mother_email")),
        "mother_occupation": _clean_str(coerced.get("mother_occupation")),
        "mother_annual_income": _clean_int(coerced.get("mother_annual_income")),
        "aadhar_number": _clean_str(coerced.get("aadhar_number")),
        "apaar_id": _clean_str(coerced.get("apaar_id")),
        "emis_number": _clean_str(coerced.get("emis_number")),
        "udise_student_id": _clean_str(coerced.get("udise_student_id")),
        "religion": _clean_str(coerced.get("religion")),
        "category": _clean_str(coerced.get("category")),
        "caste": _clean_str(coerced.get("caste")),
        "nationality": _clean_str(coerced.get("nationality")),
        "mother_tongue": _clean_str(coerced.get("mother_tongue")),
        "place_of_birth": _clean_str(coerced.get("place_of_birth")),
        "current_address": _clean_str(coerced.get("current_address")),
        "current_city": _clean_str(coerced.get("current_city")),
        "current_state": _clean_str(coerced.get("current_state")),
        "current_pincode": _clean_str(coerced.get("current_pincode")),
        "permanent_address": _clean_str(coerced.get("permanent_address")),
        "permanent_city": _clean_str(coerced.get("permanent_city")),
        "permanent_state": _clean_str(coerced.get("permanent_state")),
        "permanent_pincode": _clean_str(coerced.get("permanent_pincode")),
        "is_same_as_permanent_address": _clean_bool(
            coerced.get("is_same_as_permanent_address")
        ),
        "emergency_contact_name": _clean_str(coerced.get("emergency_contact_name")),
        "emergency_contact_relationship": _clean_str(
            coerced.get("emergency_contact_relationship")
        ),
        "emergency_contact_phone": _clean_str(coerced.get("emergency_contact_phone")),
        "admission_date": adm_date,
        "previous_school_name": _clean_str(coerced.get("previous_school_name")),
        "previous_school_class": _clean_str(coerced.get("previous_school_class")),
        "last_school_board": _clean_str(coerced.get("last_school_board")),
        "tc_number": _clean_str(coerced.get("tc_number")),
        "house_name": _clean_str(coerced.get("house_name")),
        "student_status": _clean_str(coerced.get("student_status")),
        "is_transport_opted": bool(coerced.get("is_transport_opted")),
    }
    return kwargs


def _dispatch_welcome(
    user_id: str,
    tenant_id: str,
    send_email: bool,
) -> None:
    from modules.notifications.enums import NotificationChannel, NotificationType
    from modules.notifications.services import notification_dispatcher

    # IN_APP: persists to DB so the student sees it after first login (no device token yet).
    # EMAIL: optional from import UI. PUSH skipped here — no FCM token before login.
    channels = [NotificationChannel.IN_APP.value]
    if send_email:
        channels.append(NotificationChannel.EMAIL.value)

    notification_dispatcher.dispatch(
        user_id=user_id,
        tenant_id=tenant_id,
        notification_type=NotificationType.ANNOUNCEMENT.value,
        channels=channels,
        title="Welcome to Nexchool",
        body="Your account has been created. Login using your credentials.",
        extra_data={},
    )


def _post_create_fees(student_id: str) -> None:
    try:
        from modules.finance.services import student_fee_service

        student_fee_service.auto_assign_fees_for_student(student_id)
    except Exception:
        logger.exception("bulk_import: auto_assign_fees failed for %s", student_id)


def _preassign_admission_numbers(
    validated: List[Tuple[int, Dict[str, Any]]],
    tenant_id: str,
) -> None:
    """Set coerced['admission_number'] for each row using the tenant format + DB sequence."""
    used: Set[str] = set(_tenant_admission_numbers(tenant_id))
    for _rn, coerced in validated:
        adm = generate_admission_number(tenant_id, reserved=used)
        coerced["admission_number"] = adm
        used.add(adm)


def import_students_from_rows(
    rows: List[Dict[str, Any]],
    row_numbers: List[int],
    *,
    tenant_id: str,
    academic_year_id: str,
    send_email: bool,
) -> Dict[str, Any]:
    """
    Validate and insert students. Commits in batches with savepoints per row.
    """
    ay = AcademicYear.query.filter_by(
        id=academic_year_id, tenant_id=tenant_id
    ).first()
    if not ay:
        return {
            "total": 0,
            "success": 0,
            "failed": 0,
            "failed_rows": [],
            "error": "academic_year_id not found",
        }

    seed_roles_for_tenant(tenant_id)
    student_role = Role.query.filter_by(tenant_id=tenant_id, name="Student").first()
    if not student_role:
        return {
            "total": 0,
            "success": 0,
            "failed": 0,
            "failed_rows": [],
            "error": "Student role not found",
        }

    class_map = _class_map_for_year(tenant_id, academic_year_id)
    db_emails = _tenant_emails_lower(tenant_id)

    validated: List[Tuple[int, Dict[str, Any]]] = []
    failed_rows: List[Dict[str, Any]] = []

    file_emails: Set[str] = set()

    for raw, rn in zip(rows, row_numbers):
        ok, _disp, errs, _warns, coerced = _validate_and_coerce_row(
            raw,
            rn,
            class_map=class_map,
            db_emails_lower=db_emails,
            file_emails=file_emails,
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

    allowed, limit_msg = _check_student_plan_limit(tenant_id)
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
        cap = tenant.plan.max_students
        current = Student.query.filter_by(tenant_id=tenant_id).count()
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
                            f"Would exceed plan student limit ({cap}). "
                            f"Current: {current}, importing: {len(validated)}."
                        ],
                    }
                    for rn in row_numbers
                ],
                "error": "Student plan limit",
            }

    _preassign_admission_numbers(validated, tenant_id)

    success_count = 0
    skwargs = _student_kwargs_from_row

    for i in range(0, len(validated), BATCH_SIZE):
        chunk = validated[i : i + BATCH_SIZE]
        batch_created: List[Tuple[int, Dict[str, Any], str, str]] = []
        for rn, coerced in chunk:
            pwd = default_student_import_password(coerced["name"])
            try:
                with db.session.begin_nested():
                    user = User(
                        tenant_id=tenant_id,
                        email=coerced["email"],
                        name=coerced["name"],
                        email_verified=True,
                        force_password_reset=False,
                    )
                    user.set_password(pwd)
                    db.session.add(user)
                    db.session.flush()

                    ur = UserRole(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        user_id=user.id,
                        role_id=student_role.id,
                    )
                    db.session.add(ur)

                    sk = skwargs(coerced, academic_year_id=academic_year_id)
                    student = Student(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        user_id=user.id,
                        **sk,
                    )
                    db.session.add(student)
                    db.session.flush()
                    batch_created.append((rn, coerced, user.id, student.id))
            except IntegrityError as e:
                logger.warning("bulk_import: integrity error row=%s: %s", rn, e)
                failed_rows.append(
                    {
                        "row_number": rn,
                        "email": coerced.get("email", ""),
                        "errors": ["Database constraint violation (duplicate or invalid)"],
                    }
                )
            except Exception as e:
                logger.exception("bulk_import: row=%s failed: %s", rn, e)
                failed_rows.append(
                    {
                        "row_number": rn,
                        "email": coerced.get("email", ""),
                        "errors": [str(e)],
                    }
                )

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.exception("bulk_import: batch commit failed: %s", e)
            for rn, coerced, _uid, _sid in batch_created:
                failed_rows.append(
                    {
                        "row_number": rn,
                        "email": coerced.get("email", ""),
                        "errors": ["Batch commit failed"],
                    }
                )
            continue

        for rn, coerced, user_id, student_id in batch_created:
            success_count += 1
            logger.info(
                "bulk_import: created student user_id=%s admission=%s row=%s",
                user_id,
                coerced["admission_number"],
                rn,
            )
            _dispatch_welcome(user_id, tenant_id, send_email)
            _post_create_fees(student_id)
            db_emails.add(coerced["email"].lower())

    return {
        "total": total,
        "success": success_count,
        "failed": len(failed_rows),
        "failed_rows": failed_rows,
    }


def run_preview(file_bytes: bytes, academic_year_id: str) -> Dict[str, Any]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise ValueError("Tenant context is required")

    header_keys, rows, row_numbers = parse_xlsx_to_rows(file_bytes)
    logger.info(
        "bulk_import preview: %s data rows, headers=%s", len(rows), header_keys
    )

    preview, summary = validate_workbook_rows(
        header_keys, rows, row_numbers, tenant_id, academic_year_id
    )
    return {
        "preview": preview,
        "errors": [],
        "summary": summary,
        "headers": header_keys,
    }


def run_import(
    file_bytes: bytes,
    academic_year_id: str,
    send_email: bool,
) -> Dict[str, Any]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise ValueError("Tenant context is required")

    _header_keys, rows, row_numbers = parse_xlsx_to_rows(file_bytes)
    logger.info("bulk_import: processing %s rows", len(rows))

    return import_students_from_rows(
        rows,
        row_numbers,
        tenant_id=tenant_id,
        academic_year_id=academic_year_id,
        send_email=send_email,
    )
