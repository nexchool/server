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
from modules.students.class_enrollment_service import assign_student_to_class
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


def _existing_student_index(tenant_id: str) -> Dict[str, Dict[str, Any]]:
    """
    Look-up tables for deciding whether an imported row is a new student or an
    existing one being re-imported with more detail.

    `non_student_emails` matters as much as the match tables: a tenant's user
    list also holds teachers and staff, and an import row must never latch onto
    one of those accounts just because the address matches.
    """
    rows = (
        db.session.query(
            Student.id,
            Student.user_id,
            Student.admission_number,
            Student.class_id,
            User.email,
        )
        .join(User, User.id == Student.user_id)
        .filter(Student.tenant_id == tenant_id)
        .all()
    )

    by_admission: Dict[str, Dict[str, Any]] = {}
    by_email: Dict[str, Dict[str, Any]] = {}
    student_emails: Set[str] = set()

    for student_id, user_id, admission_number, class_id, email in rows:
        email_lower = email.strip().lower() if email else None
        entry = {
            "student_id": student_id,
            "user_id": user_id,
            "admission_number": admission_number,
            "class_id": class_id,
            "email_lower": email_lower,
        }
        if admission_number:
            by_admission[str(admission_number).strip().lower()] = entry
        if email_lower:
            by_email[email_lower] = entry
            student_emails.add(email_lower)

    return {
        "by_admission": by_admission,
        "by_email": by_email,
        "non_student_emails": _tenant_emails_lower(tenant_id) - student_emails,
    }


def _class_candidates_for_year(
    tenant_id: str, academic_year_id: str
) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """Map (grade_label_lower, section_lower) -> list of candidate classes.

    A school running multiple branches/programmes can have several classes that
    share the same grade label + section (e.g. GSEB Gujarati "10 A" and GSEB
    English "10 A", or the same grade+section in two branches). The class is only
    uniquely identified by (branch, programme, grade, section), so each candidate
    carries its branch (school unit) and programme identifiers and the caller
    narrows to exactly one using the required `branch` + `programme` columns.

    Class.name is a legacy nullable display column; grade-based classes (post
    multi-school migration) carry their label on grade.name. Each class is keyed
    under BOTH labels (when they differ) so a spreadsheet saying "10" or
    "Nursery" matches regardless of which column the school's data populates.
    """
    from modules.academic_programmes.models import AcademicProgramme
    from modules.grades.models import Grade
    from modules.school_units.models import SchoolUnit

    rows = (
        db.session.query(
            Class.id,
            Class.name,
            Grade.name,
            Class.section,
            AcademicProgramme.name,
            AcademicProgramme.board,
            AcademicProgramme.code,
            SchoolUnit.name,
            SchoolUnit.code,
        )
        .outerjoin(Grade, Grade.id == Class.grade_id)
        .outerjoin(AcademicProgramme, AcademicProgramme.id == Class.programme_id)
        .outerjoin(SchoolUnit, SchoolUnit.id == Class.school_unit_id)
        .filter(
            Class.tenant_id == tenant_id,
            Class.academic_year_id == academic_year_id,
        )
        .all()
    )
    out: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for (
        class_id,
        class_name,
        grade_name,
        section,
        programme_name,
        board,
        programme_code,
        unit_name,
        unit_code,
    ) in rows:
        section_key = (section or "").strip().lower()
        labels = {
            label
            for label in (
                (class_name or "").strip().lower(),
                (grade_name or "").strip().lower(),
            )
            if label
        }
        entry = {
            "id": class_id,
            "programme_name": programme_name,
            "programme_code": programme_code,
            "board": board,
            "unit_name": unit_name,
            "unit_code": unit_code,
        }
        for label in labels:
            out.setdefault((label, section_key), []).append(entry)
    return out


def _resolve_class_by_branch_programme(
    class_name: str,
    section: str,
    branch: Optional[str],
    programme: Optional[str],
    candidates: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve the exact class from the required branch + programme columns.

    Returns ``(class_id, error_message)``. `candidates` are the classes matching
    the grade label + section. Branch is matched (case-insensitive) against the
    school unit name or code; programme against the programme name, code, or
    board. Because a class is unique per (branch, programme, grade, section), a
    valid pair lands on exactly one class. Blank branch/programme return
    ``(None, None)`` — they are flagged as "Missing" separately, so this adds no
    duplicate error.
    """

    def norm(value: Any) -> str:
        return str(value or "").strip().lower()

    b = norm(branch)
    p = norm(programme)
    if not b or not p:
        return None, None

    matched = [
        c
        for c in candidates
        if b in {norm(c.get("unit_name")), norm(c.get("unit_code"))}
        and p in {norm(c.get("programme_name")), norm(c.get("programme_code")), norm(c.get("board"))}
    ]

    if len(matched) == 1:
        return matched[0]["id"], None

    branches = ", ".join(sorted({c.get("unit_name") or "(no branch)" for c in candidates}))
    programmes = ", ".join(
        sorted({c.get("programme_name") or "(no programme)" for c in candidates})
    )
    if not matched:
        return None, (
            f"No class for branch '{branch}' + programme '{programme}' at grade "
            f"'{class_name}' / section '{section}'. Available for this grade+section — "
            f"branches: [{branches}]; programmes: [{programmes}]."
        )
    return None, (
        f"Grade '{class_name}' / section '{section}' with branch '{branch}' + "
        f"programme '{programme}' matched {len(matched)} classes; contact support."
    )


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
    class_map: Dict[Tuple[str, str], List[Dict[str, Any]]],
    index: Dict[str, Dict[str, Any]],
    file_emails: Set[str],
) -> Tuple[bool, Dict[str, Any], List[str], List[str], Optional[Dict[str, Any]]]:
    """
    Returns (valid, display_values, hard_errors, warnings, coerced_or_none).

    A valid row carries `_action` ("create" or "update") and, for updates,
    `_match` describing the student it resolved to.
    """
    errors: List[str] = []
    warnings: List[str] = []
    row = filter_known_columns(raw)

    for req in REQUIRED_FIELDS:
        if is_blank(row.get(req)):
            errors.append(f"Missing {req}")

    email = (str(row.get("email")).strip() if not is_blank(row.get("email")) else None)
    admission_number = (
        str(row.get("admission_number")).strip()
        if not is_blank(row.get("admission_number"))
        else None
    )

    # Identify the row: admission number first (it is the school's own identity
    # for a student and survives an email change), then email. A match makes
    # this an update of the existing record rather than a duplicate; no match
    # means a new student and the admission number is assigned automatically.
    match: Optional[Dict[str, Any]] = None
    if admission_number:
        match = index["by_admission"].get(admission_number.lower())
        if not match:
            warnings.append(
                f"No student found with admission number '{admission_number}'; "
                "importing as a new student with an automatically assigned number"
            )
    if not match and email:
        match = index["by_email"].get(email.lower())

    if email:
        if not validate_email_format(email):
            errors.append("Invalid email")
        el = email.lower()
        if el in file_emails:
            errors.append("Duplicate email in file")
        elif el in index["non_student_emails"]:
            # A teacher or staff account owns this address. Creating would
            # collide on the unique index and updating would hijack their login.
            errors.append("Email already in use by another account in this school")
        elif match and match["email_lower"] and match["email_lower"] != el:
            # Matched by admission number but the sheet carries a different
            # address — could be a genuine email change or the wrong row. Either
            # way, silently reassigning a login is not something to guess at.
            errors.append(
                f"Admission number '{admission_number}' belongs to a student with a "
                f"different email ({match['email_lower']}); fix the sheet or update the email in the app"
            )

    class_name = (
        str(row.get("class_name")).strip() if not is_blank(row.get("class_name")) else None
    )
    section = str(row.get("section")).strip() if not is_blank(row.get("section")) else None
    branch = str(row.get("branch")).strip() if not is_blank(row.get("branch")) else None
    programme = (
        str(row.get("programme")).strip() if not is_blank(row.get("programme")) else None
    )
    # branch/programme/class_name/section are all required (flagged above if
    # missing); resolve to exactly one class only when the grade+section are present.
    class_id: Optional[str] = None
    if class_name and section:
        candidates = class_map.get((class_name.lower(), section.lower()), [])
        if not candidates:
            errors.append(
                f"No class found for grade '{class_name}' / section '{section}'"
            )
        else:
            class_id, class_err = _resolve_class_by_branch_programme(
                class_name, section, branch, programme, candidates
            )
            if class_err:
                errors.append(class_err)

    date_errs: List[str] = []
    coerced = coerce_row_types(row, warnings, date_errs)
    for e in date_errs:
        errors.append(e)

    for f in (
        "father_phone",
        "mother_phone",
        "guardian_phone",
        "emergency_contact_phone",
        "emergency_contact_alt_phone",
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

    if match:
        coerced["_action"] = "update"
        coerced["_match"] = match
        # Placement is deliberately not driven by the sheet: moving a student
        # cascades into enrollment, attendance and fee assignment, so a stale
        # column must not re-enrol anyone as a side effect of enriching data.
        if match["class_id"] and match["class_id"] != class_id:
            warnings.append(
                f"Class/section differs from the current placement for "
                f"'{class_name} {section}'; the student was not moved"
            )
        display["_action"] = "update"
    else:
        coerced["_action"] = "create"
        display["_action"] = "create"

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

    class_map = _class_candidates_for_year(tenant_id, academic_year_id)
    index = _existing_student_index(tenant_id)

    file_emails: Set[str] = set()

    preview: List[Dict[str, Any]] = []
    valid_n = 0
    invalid_n = 0
    create_n = 0
    update_n = 0

    for raw, rn in zip(rows, row_numbers):
        ok, display, errs, warns, coerced = _validate_and_coerce_row(
            raw,
            rn,
            class_map=class_map,
            index=index,
            file_emails=file_emails,
        )
        action = (coerced or {}).get("_action")
        if ok:
            valid_n += 1
            if action == "update":
                update_n += 1
            else:
                create_n += 1
        else:
            invalid_n += 1
        preview.append(
            {
                "row_number": rn,
                "values": display,
                "errors": errs,
                "warnings": warns,
                "valid": ok,
                "action": action,
            }
        )

    return preview, {
        "valid": valid_n,
        "invalid": invalid_n,
        "total": len(rows),
        "create": create_n,
        "update": update_n,
    }


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
        "address": _clean_str(coerced.get("address")),
        "guardian_name": _clean_str(coerced.get("guardian_name")),
        "guardian_relationship": _clean_str(coerced.get("guardian_relationship")),
        "guardian_phone": _clean_str(coerced.get("guardian_phone")),
        "guardian_email": _clean_str(coerced.get("guardian_email")),
        "guardian_address": _clean_str(coerced.get("guardian_address")),
        "guardian_occupation": _clean_str(coerced.get("guardian_occupation")),
        "guardian_aadhar_number": _clean_str(coerced.get("guardian_aadhar_number")),
        "blood_group": _clean_str(coerced.get("blood_group")),
        "height_cm": _clean_int(coerced.get("height_cm")),
        "weight_kg": weight,
        "medical_allergies": _clean_str(coerced.get("medical_allergies")),
        "medical_conditions": _clean_str(coerced.get("medical_conditions")),
        "disability_details": _clean_str(coerced.get("disability_details")),
        "identification_marks": _clean_str(coerced.get("identification_marks")),
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
        "is_commuting_from_outstation": _clean_bool(
            coerced.get("is_commuting_from_outstation")
        ),
        "commute_location": _clean_str(coerced.get("commute_location")),
        "commute_notes": _clean_str(coerced.get("commute_notes")),
        "emergency_contact_name": _clean_str(coerced.get("emergency_contact_name")),
        "emergency_contact_relationship": _clean_str(
            coerced.get("emergency_contact_relationship")
        ),
        "emergency_contact_phone": _clean_str(coerced.get("emergency_contact_phone")),
        "emergency_contact_alt_phone": _clean_str(
            coerced.get("emergency_contact_alt_phone")
        ),
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


# Identity and placement are never taken from a re-imported sheet: the
# admission number is ours to assign, the academic year comes from the import
# form, and a class move is an enrollment change (see the class-differs warning).
_UPDATE_SKIP_FIELDS = frozenset(
    {"admission_number", "academic_year_id", "class_id"}
)


def _apply_row_updates(
    student: Student,
    coerced: Dict[str, Any],
    *,
    academic_year_id: str,
) -> List[str]:
    """
    Copy the row's populated values onto an existing student. Returns the names
    of the fields that actually changed.

    Only cells that carry a value are applied. A blank cell means "the sheet has
    nothing to say about this field", never "erase what is on record" — the
    whole point of a re-import is to add detail, and schools routinely upload
    partial sheets covering one section or one set of columns.
    """
    kwargs = _student_kwargs_from_row(coerced, academic_year_id=academic_year_id)
    changed: List[str] = []

    for field, value in kwargs.items():
        if field in _UPDATE_SKIP_FIELDS:
            continue
        # Test the source cell, not the coerced value: booleans coerce a blank
        # to False, which would otherwise quietly clear a flag that is set.
        if is_blank(coerced.get(field)):
            continue
        if getattr(student, field, None) == value:
            continue
        setattr(student, field, value)
        changed.append(field)

    return changed


def _dispatch_welcome(
    user_id: str,
    tenant_id: str,
    send_email: bool,
) -> None:
    """Best-effort welcome notification. Runs AFTER the student row is committed,
    so any failure here must be logged and swallowed — it must never turn an
    already-successful import into a reported failure. (dispatch() already
    swallows per-channel send errors; this also guards the surrounding setup.)"""
    try:
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
    except Exception:
        logger.exception("bulk_import: welcome dispatch failed for user=%s", user_id)


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

    class_map = _class_candidates_for_year(tenant_id, academic_year_id)
    index = _existing_student_index(tenant_id)

    validated: List[Tuple[int, Dict[str, Any]]] = []
    failed_rows: List[Dict[str, Any]] = []

    file_emails: Set[str] = set()

    for raw, rn in zip(rows, row_numbers):
        ok, _disp, errs, _warns, coerced = _validate_and_coerce_row(
            raw,
            rn,
            class_map=class_map,
            index=index,
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

    # Only brand-new students consume plan capacity; re-imported rows update a
    # record that is already counted.
    new_student_rows = [
        (rn, c) for rn, c in validated if c.get("_action") != "update"
    ]

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
        if current + len(new_student_rows) > cap:
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

    _preassign_admission_numbers(new_student_rows, tenant_id)

    success_count = 0
    updated_count = 0
    skwargs = _student_kwargs_from_row

    for i in range(0, len(validated), BATCH_SIZE):
        chunk = validated[i : i + BATCH_SIZE]
        batch_created: List[Tuple[int, Dict[str, Any], str, str]] = []
        batch_updated: List[Tuple[int, Dict[str, Any], List[str]]] = []
        for rn, coerced in chunk:
            if coerced.get("_action") == "update":
                match = coerced["_match"]
                # Carry the existing number so _student_kwargs_from_row can build
                # its dict; _apply_row_updates then skips it as an identity field.
                coerced["admission_number"] = match["admission_number"]
                try:
                    with db.session.begin_nested():
                        student = Student.query.filter_by(
                            id=match["student_id"], tenant_id=tenant_id
                        ).first()
                        if not student:
                            raise RuntimeError("Student no longer exists")
                        changed = _apply_row_updates(
                            student, coerced, academic_year_id=academic_year_id
                        )
                        batch_updated.append((rn, coerced, changed))
                except Exception as e:
                    logger.exception("bulk_import: update row=%s failed: %s", rn, e)
                    failed_rows.append(
                        {
                            "row_number": rn,
                            "email": coerced.get("email", ""),
                            "errors": [str(e)],
                        }
                    )
                continue

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
                    enr = assign_student_to_class(
                        student.id,
                        coerced["class_id"],
                        academic_year_id,
                        commit=False,
                    )
                    if not enr.get("success"):
                        raise RuntimeError(enr.get("error", "enrollment failed"))
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
            for rn, coerced, _changed in batch_updated:
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
            index["by_email"][coerced["email"].lower()] = {
                "student_id": student_id,
                "user_id": user_id,
                "admission_number": coerced["admission_number"],
                "class_id": coerced["class_id"],
                "email_lower": coerced["email"].lower(),
            }

        # Updates deliberately skip _dispatch_welcome and _post_create_fees:
        # re-running those would mail every existing parent a fresh "welcome,
        # here is your account" and assign a second set of fee records.
        for rn, coerced, changed in batch_updated:
            updated_count += 1
            logger.info(
                "bulk_import: updated student admission=%s row=%s fields=%s",
                coerced.get("admission_number"),
                rn,
                ",".join(changed) if changed else "(none)",
            )

    return {
        "total": total,
        # `success` stays the count of newly created students so existing
        # callers keep their meaning; created/updated break it down.
        "success": success_count,
        "created": success_count,
        "updated": updated_count,
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
