"""
Teacher request validation, built from the central validators in
core.validation. Mirrors admin-web/src/components/teachers/TeacherFormModal.tsx.
"""

from __future__ import annotations

from core import validation as v

# Mirrors the `status` column default and comment on Teacher (active / inactive).
# Kept here alongside the rest of the teacher contract so routes validate against
# one list rather than repeating literals.
TEACHER_STATUS_VALUES = (
    "active",
    "inactive",
)


def _department_not_yet_supported(value: str | None) -> str | None:
    """Reject a free-text department instead of silently discarding it.

    Migration 077 replaced Teacher.department (free text) with department_id
    (FK). Resolving a submitted name to a department_id — or exposing a
    picker — is Task 5's job. Until then, accepting the field and dropping
    it would look like a successful save while quietly losing the value;
    failing loudly here is recoverable, silent data loss is not.
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    return (
        "Department can no longer be set as free text; a department picker "
        "is coming soon. Leave this field blank for now."
    )


_TEACHER_SPEC = {
    "name": [v.required("Name"), v.max_length(120, "Name")],
    "email": [v.email()],
    "phone": [v.phone_loose()],
    "designation": [v.max_length(80, "Designation")],
    "department": [_department_not_yet_supported],
    "qualification": [v.max_length(120, "Qualification")],
    "specialization": [v.max_length(120, "Specialization")],
    "experience_years": [v.integer(min_value=0, max_value=80, label="Experience (years)")],
    "date_of_joining": [v.is_date("Date of joining")],
    "address": [v.max_length(255, "Address")],
}


def validate_teacher_payload(data: dict, *, is_update: bool = False) -> dict[str, str] | None:
    """Return a ``{field: message}`` dict of validation errors, or None.

    On update, ``name`` may be omitted, so its required rule is dropped.
    """
    spec = dict(_TEACHER_SPEC)
    if is_update:
        spec["name"] = [v.max_length(120, "Name")]
    return v.run(data, spec)
