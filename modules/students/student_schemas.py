"""
Student request validation / coercion helpers.

Keep style consistent with other modules: lightweight, defensive, non-blocking for optional fields.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


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


def validate_student_payload(data: dict, *, is_update: bool) -> str | None:
    """
    Validate obvious constraints only. Return error message if invalid; None if OK.
    Keep permissive: optional fields may be omitted or empty.
    """
    if not isinstance(data, dict):
        return "Invalid JSON payload."

    # Dates
    for key in ("date_of_birth", "admission_date"):
        ok, err = parse_date(data.get(key))
        if not ok:
            return f"{key}: {err}"

    # Numbers
    ok, err = parse_int(data.get("height_cm"), min_value=0, max_value=300)
    if not ok:
        return f"height_cm: {err}"
    ok, err = parse_decimal(data.get("weight_kg"), min_value=0, max_value=500)
    if not ok:
        return f"weight_kg: {err}"

    for key in ("father_annual_income", "mother_annual_income", "roll_number"):
        ok, err = parse_int(data.get(key), min_value=0)
        if not ok:
            return f"{key}: {err}"

    # Booleans
    for key in ("is_same_as_permanent_address", "is_commuting_from_outstation"):
        ok, err = parse_bool(data.get(key))
        if not ok:
            return f"{key}: {err}"

    # Lightweight length checks (avoid overly strict validation)
    max_len: dict[str, int] = {
        "blood_group": 10,
        "father_phone": 20,
        "mother_phone": 20,
        "guardian_aadhar_number": 20,
        "aadhar_number": 20,
        "apaar_id": 50,
        "emis_number": 50,
        "udise_student_id": 50,
        "religion": 50,
        "category": 50,
        "caste": 50,
        "nationality": 50,
        "mother_tongue": 50,
        "place_of_birth": 120,
        "current_city": 80,
        "current_state": 80,
        "current_pincode": 12,
        "permanent_city": 80,
        "permanent_state": 80,
        "permanent_pincode": 12,
        "emergency_contact_phone": 20,
        "emergency_contact_alt_phone": 20,
        "tc_number": 50,
        "house_name": 50,
        "student_status": 30,
    }
    for k, m in max_len.items():
        v = data.get(k)
        if v is None:
            continue
        if isinstance(v, str) and len(v) > m:
            return f"{k}: Too long (max {m})."

    # Create-only required logic remains in routes/services; do not duplicate here.
    return None

