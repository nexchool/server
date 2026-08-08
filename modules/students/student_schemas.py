"""
Student request validation / coercion helpers.

Keep style consistent with other modules: lightweight, defensive, non-blocking for optional fields.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from core import validation as v

# Canonical student lifecycle statuses. Keep in sync with the frontend at
# admin-web/src/constants/studentStatus.ts.
STUDENT_STATUS_VALUES = (
    "active",
    "inactive",
    "transferred",
    "graduated",
    # Flagged to leave at the end of the year — still here, still taught,
    # excluded from promotion. Distinct from `withdrawn`, which is past tense.
    "leaving",
    "suspended",
    "dropped_out",
    # A student who has left before completing. The billing code has excluded
    # this value since it was written, but nothing could ever set it — see
    # modules/students/lifecycle_service.py.
    "withdrawn",
)
DEFAULT_STUDENT_STATUS = "active"

# Statuses a student cannot be moved to by editing a record. Each is the
# outcome of a business workflow that has other work to do — closing an
# enrollment, recording when and why — so setting the word alone would leave
# the student half-moved (ADR: status is workflow-driven).
WORKFLOW_ONLY_STATUSES = frozenset({"withdrawn", "graduated", "transferred"})


def _trim_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v if v != "" else None
    return str(value).strip() or None


def parse_date(value: Any) -> tuple[bool, str | None]:
    """Validate date as YYYY-MM-DD (do not convert here)."""
    v = _trim_or_none(value)
    if v is None:
        return True, None
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return True, None
    except Exception:
        return False, "Invalid date format. Expected YYYY-MM-DD."


def parse_int(value: Any, *, min_value: int | None = None, max_value: int | None = None) -> tuple[bool, str | None]:
    v = _trim_or_none(value)
    if v is None:
        return True, None
    try:
        n = int(v)
    except Exception:
        return False, "Invalid number."
    if min_value is not None and n < min_value:
        return False, f"Must be >= {min_value}."
    if max_value is not None and n > max_value:
        return False, f"Must be <= {max_value}."
    return True, None


def parse_decimal(value: Any, *, min_value: float | None = None, max_value: float | None = None) -> tuple[bool, str | None]:
    v = _trim_or_none(value)
    if v is None:
        return True, None
    try:
        d = Decimal(v)
    except (InvalidOperation, ValueError):
        return False, "Invalid number."
    if min_value is not None and d < Decimal(str(min_value)):
        return False, f"Must be >= {min_value}."
    if max_value is not None and d > Decimal(str(max_value)):
        return False, f"Must be <= {max_value}."
    return True, None


def parse_bool(value: Any) -> tuple[bool, str | None]:
    """
    Accepts bool, 0/1, "true/false", "yes/no", "on/off".
    """
    if value is None or value == "":
        return True, None
    if isinstance(value, bool):
        return True, None
    if isinstance(value, (int, float)) and value in (0, 1):
        return True, None
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "false", "1", "0", "yes", "no", "on", "off"):
            return True, None
    return False, "Invalid boolean."


# Field validation spec, applied to both create and update payloads. Required
# fields and the academic_year/class rule stay in the route (they carry
# create-only logic); this covers formats, ranges, enums and lengths.
_STUDENT_SPEC = {
    # Emails
    "email": [v.email()],
    "guardian_email": [v.email()],
    "father_email": [v.email()],
    "mother_email": [v.email()],
    # Phones — the student's and guardian's own numbers are mobiles (they receive
    # OTPs and SMS), so both take the strict 10-digit rule. Parent and emergency
    # contacts stay lenient: those may be landlines with STD codes.
    "guardian_phone": [v.phone("Guardian phone")],
    "phone": [v.phone("Student phone")],
    "father_phone": [v.phone_loose()],
    "mother_phone": [v.phone_loose()],
    "emergency_contact_phone": [v.phone_loose()],
    "emergency_contact_alt_phone": [v.phone_loose()],
    # Government IDs
    "aadhar_number": [v.aadhar()],
    "guardian_aadhar_number": [v.aadhar("Guardian Aadhaar")],
    "current_pincode": [v.pincode()],
    "permanent_pincode": [v.pincode()],
    # Dates
    "date_of_birth": [v.is_date("Date of birth")],
    "admission_date": [v.is_date("Admission date")],
    # Numbers
    "height_cm": [v.integer(min_value=0, max_value=300, label="Height")],
    "weight_kg": [v.decimal(min_value=0, max_value=500, label="Weight")],
    "father_annual_income": [v.integer(min_value=0, label="Father's annual income")],
    "mother_annual_income": [v.integer(min_value=0, label="Mother's annual income")],
    "roll_number": [v.integer(min_value=0, label="Roll number")],
    # Booleans
    "is_same_as_permanent_address": [v.boolean()],
    "is_commuting_from_outstation": [v.boolean()],
    # Enum
    "student_status": [v.one_of(STUDENT_STATUS_VALUES, "student status")],
    # Length guards
    "blood_group": [v.max_length(10, "Blood group")],
    "apaar_id": [v.max_length(50, "APAAR ID")],
    "emis_number": [v.max_length(50, "EMIS number")],
    "udise_student_id": [v.max_length(50, "UDISE ID")],
    "religion": [v.max_length(50, "Religion")],
    "category": [v.max_length(50, "Category")],
    "caste": [v.max_length(50, "Caste")],
    "nationality": [v.max_length(50, "Nationality")],
    "mother_tongue": [v.max_length(50, "Mother tongue")],
    "place_of_birth": [v.max_length(120, "Place of birth")],
    "current_city": [v.max_length(80, "Current city")],
    "current_state": [v.max_length(80, "Current state")],
    "permanent_city": [v.max_length(80, "Permanent city")],
    "permanent_state": [v.max_length(80, "Permanent state")],
    "tc_number": [v.max_length(50, "TC number")],
    "house_name": [v.max_length(50, "House name")],
    "academic_result": [v.max_length(20, "Academic result")],
}


def validate_student_payload(data: dict, *, is_update: bool) -> dict[str, str] | None:
    """
    Validate formats, ranges, enums and lengths for a student payload. Returns a
    ``{field: message}`` dict (for ``validation_error_response``) or None.

    Optional fields are only checked when present. Required-field and
    academic-year logic stays in the route.
    """
    return v.run(data, _STUDENT_SPEC)

