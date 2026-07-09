"""
Central request-field validation, shared by every module's request schemas
(students / teachers / classes …).

One place for the rules and messages so backend validation stays consistent and
mirrors the frontend at admin-web/src/lib/validation/fields.ts.

Usage:

    from core.validation import run, required, phone, max_length

    SPEC = {
        "name": [required("Name")],
        "guardian_phone": [required("Guardian phone"), phone()],
    }
    errors = run(data, SPEC)          # -> {"field": "message"} or None
    if errors:
        return validation_error_response(errors)

Rules are simple callables ``(value) -> str | None``. Every non-``required``
rule treats an empty/missing value as "nothing to validate" and returns None,
so optional fields only get checked when a value is actually present.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Mapping

Rule = Callable[[Any], "str | None"]

# Patterns kept identical to admin-web/src/lib/validation/fields.ts
PHONE_RE = re.compile(r"^(?:\+91[\s-]?)?[6-9]\d{9}$")
AADHAR_RE = re.compile(r"^\d{12}$")
PINCODE_RE = re.compile(r"^\d{6}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else str(value).strip()


# ---- Rule factories ------------------------------------------------------


def required(label: str = "This field") -> Rule:
    def rule(value: Any) -> str | None:
        return f"{label} is required" if _is_empty(value) else None

    return rule


def max_length(n: int, label: str = "This field") -> Rule:
    def rule(value: Any) -> str | None:
        if _is_empty(value):
            return None
        if len(_as_str(value)) > n:
            return f"{label} must be {n} characters or fewer"
        return None

    return rule


def email(_label: str = "Email") -> Rule:
    def rule(value: Any) -> str | None:
        if _is_empty(value):
            return None
        return None if EMAIL_RE.match(_as_str(value)) else "Enter a valid email address"

    return rule


def phone(_label: str = "Phone") -> Rule:
    def rule(value: Any) -> str | None:
        if _is_empty(value):
            return None
        return None if PHONE_RE.match(_as_str(value)) else "Enter a valid 10-digit mobile number"

    return rule


def phone_loose(_label: str = "Phone") -> Rule:
    """Lenient phone for secondary contacts (may be landlines): 10-15 digits."""

    def rule(value: Any) -> str | None:
        if _is_empty(value):
            return None
        digits = re.sub(r"\D", "", _as_str(value))
        return None if 10 <= len(digits) <= 15 else "Enter a valid phone number"

    return rule


def aadhar(_label: str = "Aadhaar") -> Rule:
    def rule(value: Any) -> str | None:
        if _is_empty(value):
            return None
        return None if AADHAR_RE.match(_as_str(value)) else "Aadhaar must be 12 digits"

    return rule


def pincode(_label: str = "PIN code") -> Rule:
    def rule(value: Any) -> str | None:
        if _is_empty(value):
            return None
        return None if PINCODE_RE.match(_as_str(value)) else "PIN code must be 6 digits"

    return rule


def is_date(_label: str = "Date") -> Rule:
    def rule(value: Any) -> str | None:
        if _is_empty(value):
            return None
        try:
            datetime.strptime(_as_str(value), "%Y-%m-%d")
            return None
        except ValueError:
            return "Use the date format YYYY-MM-DD"

    return rule


def integer(
    *, min_value: int | None = None, max_value: int | None = None, label: str = "value"
) -> Rule:
    def rule(value: Any) -> str | None:
        if _is_empty(value):
            return None
        try:
            n = int(_as_str(value))
        except (ValueError, TypeError):
            return f"{label} must be a whole number"
        if min_value is not None and n < min_value:
            return f"{label} must be at least {min_value}"
        if max_value is not None and n > max_value:
            return f"{label} must be at most {max_value}"
        return None

    return rule


def decimal(
    *, min_value: float | None = None, max_value: float | None = None, label: str = "value"
) -> Rule:
    def rule(value: Any) -> str | None:
        if _is_empty(value):
            return None
        try:
            d = Decimal(_as_str(value))
        except (InvalidOperation, ValueError, TypeError):
            return f"{label} must be a number"
        if min_value is not None and d < Decimal(str(min_value)):
            return f"{label} must be at least {min_value}"
        if max_value is not None and d > Decimal(str(max_value)):
            return f"{label} must be at most {max_value}"
        return None

    return rule


def boolean(_label: str = "value") -> Rule:
    _ok = {"true", "false", "1", "0", "yes", "no", "on", "off"}

    def rule(value: Any) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and value in (0, 1):
            return None
        if isinstance(value, str) and value.strip().lower() in _ok:
            return None
        return "Invalid value"

    return rule


def one_of(values: Iterable[str], label: str = "value") -> Rule:
    allowed = {v for v in values}

    def rule(value: Any) -> str | None:
        if _is_empty(value):
            return None
        return None if _as_str(value) in allowed else f"Select a valid {label}"

    return rule


# ---- Runner --------------------------------------------------------------


def run(data: Mapping[str, Any], spec: Mapping[str, Iterable[Rule]]) -> dict[str, str] | None:
    """
    Apply ``spec`` to ``data``. Returns a ``{field: first_error_message}`` dict,
    or ``None`` when everything passes. Stops at the first failing rule per field.
    """
    if not isinstance(data, Mapping):
        return {"_": "Invalid JSON payload."}

    errors: dict[str, str] = {}
    for field, rules in spec.items():
        value = data.get(field)
        for rule in rules:
            err = rule(value)
            if err:
                errors[field] = err
                break
    return errors or None
