"""
Validation and coercion for bulk teacher import rows.

To add new Excel columns later:
1. Add the snake_case header key to OPTIONAL_TEACHER_FIELDS.
2. If the field needs typing (date, int, enum), extend coerce_teacher_row().
3. Map the coerced key in bulk_teacher_import_service._teacher_kwargs_from_coerced().
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

from modules.students.utils.bulk_validation import (
    is_blank,
    parse_date_yyyy_mm_dd,
    parse_int_soft,
    validate_phone_soft,
)

REQUIRED_TEACHER_FIELDS = ("name",)

# Columns accepted from Excel (extras are ignored). Includes User + Teacher profile fields.
OPTIONAL_TEACHER_FIELDS: Set[str] = {
    "email",
    "employee_id",  # legacy; ignored (server assigns)
    "phone",
    "designation",
    "department",
    "qualification",
    "specialization",
    "experience_years",
    "address",
    "date_of_joining",
    "status",
}


def filter_known_teacher_columns(row: Dict[str, Any]) -> Dict[str, Any]:
    allowed = set(REQUIRED_TEACHER_FIELDS) | OPTIONAL_TEACHER_FIELDS
    return {k: v for k, v in row.items() if k in allowed}


def coerce_teacher_row(
    row: Dict[str, Any],
    warnings: List[str],
    date_errors: List[str],
) -> Dict[str, Any]:
    out = dict(row)

    if "experience_years" in out and not is_blank(out.get("experience_years")):
        out["experience_years"] = parse_int_soft(out.get("experience_years"))

    if "date_of_joining" in out and not is_blank(out.get("date_of_joining")):
        iso, err = parse_date_yyyy_mm_dd(out["date_of_joining"])
        if err:
            date_errors.append(f"date_of_joining: {err}")
            out["date_of_joining"] = None
        else:
            out["date_of_joining"] = iso

    if "phone" in out and not is_blank(out.get("phone")):
        norm, ok = validate_phone_soft(str(out["phone"]).strip())
        out["phone"] = norm
        if not ok:
            warnings.append("phone: invalid format ignored")

    if "status" in out and not is_blank(out.get("status")):
        s = str(out["status"]).strip().lower()
        if s in ("active", "inactive"):
            out["status"] = s
        else:
            warnings.append("status: must be active or inactive; defaulting to active")
            out["status"] = "active"
    elif "status" in out:
        out["status"] = "active"

    return out
