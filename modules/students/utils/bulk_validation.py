"""
Validation and coercion for bulk student import rows.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("name", "email", "class_name", "section")

# Optional columns that map to Student / User (ignored if absent)
OPTIONAL_STUDENT_FIELDS: Set[str] = {
    "admission_number",  # legacy column; ignored with a warning (server assigns)
    "roll_number",
    "gender",
    "date_of_birth",
    "phone",
    "father_name",
    "father_phone",
    "father_email",
    "father_occupation",
    "father_annual_income",
    "mother_name",
    "mother_phone",
    "mother_email",
    "mother_occupation",
    "mother_annual_income",
    "guardian_name",
    "guardian_phone",
    "guardian_email",
    "guardian_relationship",
    "current_address",
    "current_city",
    "current_state",
    "current_pincode",
    "permanent_address",
    "permanent_city",
    "permanent_state",
    "permanent_pincode",
    "is_same_as_permanent_address",
    "aadhar_number",
    "apaar_id",
    "emis_number",
    "udise_student_id",
    "religion",
    "category",
    "caste",
    "nationality",
    "mother_tongue",
    "place_of_birth",
    "blood_group",
    "height_cm",
    "weight_kg",
    "medical_allergies",
    "medical_conditions",
    "emergency_contact_name",
    "emergency_contact_phone",
    "emergency_contact_relationship",
    "admission_date",
    "previous_school_name",
    "previous_school_class",
    "last_school_board",
    "tc_number",
    "house_name",
    "student_status",
    "is_transport_opted",
}

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def validate_email_format(email: str) -> bool:
    return bool(email and EMAIL_RE.match(email.strip()))


def validate_phone_soft(phone: Optional[str]) -> Tuple[Optional[str], bool]:
    """
    Returns (normalized phone or None, is_valid).
    Invalid -> log warning, treat as absent (soft).
    """
    if is_blank(phone):
        return None, True
    raw = str(phone).strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 10 and len(digits) <= 15:
        return raw, True
    logger.warning("bulk_import: invalid phone ignored: %r", raw)
    return None, False


def parse_date_yyyy_mm_dd(val: Any) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (iso string or None, error message or None).
    Accepts YYYY-MM-DD string or Excel-serialized date string from parser.
    """
    if is_blank(val):
        return None, None
    if isinstance(val, str):
        s = val.strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(s, fmt).date().isoformat(), None
            except ValueError:
                continue
        return None, "Invalid date"
    return None, "Invalid date"


DATE_FIELDS_OPTIONAL = ("date_of_birth", "admission_date")


def parse_bool(val: Any) -> Optional[bool]:
    if is_blank(val):
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        if val in (0, 1):
            return bool(int(val))
        return None
    s = str(val).strip().lower()
    if s in ("true", "1", "yes", "y", "on"):
        return True
    if s in ("false", "0", "no", "n", "off"):
        return False
    return None


def parse_int_soft(val: Any) -> Optional[int]:
    if is_blank(val):
        return None
    try:
        if isinstance(val, float) and val == int(val):
            return int(val)
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(str(val).strip())
        except ValueError:
            return None


def parse_decimal_soft(val: Any) -> Optional[Decimal]:
    if is_blank(val):
        return None
    try:
        return Decimal(str(val).strip())
    except (InvalidOperation, ValueError):
        return None


def coerce_row_types(
    row: Dict[str, Any],
    warnings: List[str],
    date_errors: List[str],
) -> Dict[str, Any]:
    """Apply typed coercions for known optional fields; unknown keys pass through."""
    out = dict(row)

    int_fields = (
        "roll_number",
        "father_annual_income",
        "mother_annual_income",
        "height_cm",
    )
    for f in int_fields:
        if f in out and not is_blank(out.get(f)):
            n = parse_int_soft(out[f])
            out[f] = n

    if "weight_kg" in out and not is_blank(out.get("weight_kg")):
        d = parse_decimal_soft(out["weight_kg"])
        out["weight_kg"] = d

    for f in DATE_FIELDS_OPTIONAL:
        if f in out and not is_blank(out.get(f)):
            iso, err = parse_date_yyyy_mm_dd(out[f])
            if err:
                date_errors.append(f"{f}: {err}")
                out[f] = None
            else:
                out[f] = iso

    if "is_same_as_permanent_address" in out:
        out["is_same_as_permanent_address"] = parse_bool(
            out.get("is_same_as_permanent_address")
        )
    if "is_transport_opted" in out:
        b = parse_bool(out.get("is_transport_opted"))
        out["is_transport_opted"] = False if b is None else b

    # Student phone soft
    if "phone" in out:
        norm, ok = validate_phone_soft(
            None if is_blank(out.get("phone")) else str(out["phone"])
        )
        out["phone"] = norm
        if not ok:
            warnings.append("phone: invalid format ignored")

    return out


def resolve_guardian_fields(row: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    create_student requires guardian_* — derive from parent columns or placeholders.
    """
    g_name = row.get("guardian_name")
    if not is_blank(g_name):
        name = str(g_name).strip()
        rel = (
            str(row.get("guardian_relationship")).strip()
            if not is_blank(row.get("guardian_relationship"))
            else "Guardian"
        )
        phone_raw = row.get("guardian_phone")
    else:
        if not is_blank(row.get("father_name")):
            name = str(row["father_name"]).strip()
            rel = "Father"
            phone_raw = row.get("father_phone")
        elif not is_blank(row.get("mother_name")):
            name = str(row["mother_name"]).strip()
            rel = "Mother"
            phone_raw = row.get("mother_phone")
        else:
            name = "Parent"
            rel = "Parent"
            phone_raw = None

    phone, ok = validate_phone_soft(
        None if is_blank(phone_raw) else str(phone_raw).strip()
    )
    if not phone:
        for cand in (
            row.get("father_phone"),
            row.get("mother_phone"),
            row.get("emergency_contact_phone"),
        ):
            phone, ok = validate_phone_soft(
                None if is_blank(cand) else str(cand).strip()
            )
            if phone:
                break
    if not phone:
        logger.warning(
            "bulk_import: no valid guardian phone; using placeholder for student email %s",
            row.get("email"),
        )
        phone = "0000000000"

    return name, rel, phone


def filter_known_columns(row: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only required + optional known keys (extras ignored)."""
    allowed = set(REQUIRED_FIELDS) | OPTIONAL_STUDENT_FIELDS
    return {k: v for k, v in row.items() if k in allowed}
